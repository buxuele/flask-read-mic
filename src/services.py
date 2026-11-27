import os
import queue
import threading
import time
from concurrent.futures import Future

import numpy as np

from config import (
    ASR_BATCH_SIZE,
    ASR_BATCH_WINDOW_SECONDS,
    ASR_DEVICE,
    ASR_DTYPE,
    ASR_MAX_NEW_TOKENS,
    ASR_MODEL_ID,
    ASR_REQUEST_TIMEOUT,
    SAMPLE_RATE,
)
from logger import transcribe_logger

# torch 冷启动要 3 秒，而模型只在真正转录时才用到。
# 除非显式设置 ASR_EAGER_IMPORT=1，否则一律等到 get_model() 再导入。
_EAGER = os.getenv('ASR_EAGER_IMPORT') == '1'
if _EAGER:
    import torch

# Qwen3-ASR 在中文场景会混入繁体（如「這個」「麼」），统一转简体输出
_CONVERTER = None


def to_simplified(text):
    global _CONVERTER
    if not text:
        return text
    if _CONVERTER is None:
        from opencc import OpenCC
        _CONVERTER = OpenCC('t2s')
    return _CONVERTER.convert(text)


STATUS_IDLE = 'idle'        # 尚未开始加载
STATUS_LOADING = 'loading'  # 正在加载权重
STATUS_WARMING = 'warming'  # 权重就绪，正在跑首次推理预热 CUDA kernel
STATUS_READY = 'ready'      # 可用
STATUS_ERROR = 'error'      # 加载失败

_load_lock = threading.RLock()
_model = None
_status = STATUS_IDLE
_error = None

# 推理队列：单工作线程 + 短窗口攒批。
# 这样并发请求会被合并成一次批量推理，而不是在全局锁上串行排队。
_queue = queue.Queue()
_worker_lock = threading.Lock()
_worker_started = False


def model_status():
    """给前端轮询用：模型当前处于哪个阶段"""
    return {'status': _status, 'error': _error, 'model': ASR_MODEL_ID}


def _cuda_available():
    import torch

    return torch.cuda.is_available()


def get_model():
    """懒加载并缓存 ASR 模型。必须在持有 _load_lock 的状态下调用。"""
    global _model, _status, _error
    if _model is not None:
        return _model

    _status = STATUS_LOADING
    _error = None

    import torch

    # 必须先于任何 AutoModel 调用完成 qwen3_asr 架构注册
    from qwen_asr import Qwen3ASRModel

    if _cuda_available():
        device = ASR_DEVICE
        dtype = getattr(torch, ASR_DTYPE)
    else:
        device, dtype = "cpu", torch.float32
        transcribe_logger.warning("未检测到 CUDA，ASR 回落至 CPU/float32，速度会很慢")

    transcribe_logger.info(f"正在加载模型: {ASR_MODEL_ID} on {device} ({dtype})")
    _model = Qwen3ASRModel.from_pretrained(
        ASR_MODEL_ID,
        dtype=dtype,
        device_map=device,
        attn_implementation="sdpa",
        max_inference_batch_size=ASR_BATCH_SIZE,
        max_new_tokens=ASR_MAX_NEW_TOKENS,
    )
    transcribe_logger.info(f"模型 {ASR_MODEL_ID} 权重加载完成")
    return _model


def _ensure_worker():
    global _worker_started
    if _worker_started:
        return
    with _worker_lock:
        if _worker_started:
            return
        threading.Thread(target=_batch_worker, name='asr-batch', daemon=True).start()
        _worker_started = True


def _collect_batch():
    first = _queue.get()
    batch = [first]
    deadline = time.monotonic() + ASR_BATCH_WINDOW_SECONDS
    while len(batch) < ASR_BATCH_SIZE:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        try:
            batch.append(_queue.get(timeout=remaining))
        except queue.Empty:
            break
    return batch


def _finish(entry, result):
    _, _, _, future = entry
    if future.done():
        return
    text = result.text.strip()
    if getattr(result, 'language', None) == 'Chinese':
        text = to_simplified(text)
    future.set_result(text)


def _run_direct(model, entry):
    samples, language, context, _ = entry
    results = model.transcribe(
        audio=(samples, SAMPLE_RATE),
        context=context,
        language=language,
    )
    _finish(entry, results[0])


def _run_batch(batch):
    audios = [(entry[0], SAMPLE_RATE) for entry in batch]
    languages = [entry[1] for entry in batch]
    contexts = [entry[2] for entry in batch]

    with _load_lock:
        model = get_model()
        if len(batch) == 1:
            _run_direct(model, batch[0])
            return
        try:
            results = model.transcribe(
                audio=audios,
                context=contexts,
                language=languages,
            )
            for entry, result in zip(batch, results):
                _finish(entry, result)
        except Exception as e:
            transcribe_logger.warning(f"批量推理失败，回退逐条: {e}")
            for entry in batch:
                _run_direct(model, entry)


def _batch_worker():
    while True:
        batch = _collect_batch()
        try:
            _run_batch(batch)
        except Exception as e:
            transcribe_logger.error(f"推理队列处理失败: {e}")
            for entry in batch:
                future = entry[3]
                if not future.done():
                    future.set_exception(e)


def transcribe_audio(samples, language, context=""):
    """samples: 16kHz 单声道 float32 ndarray。language: 规范语言名或 None。"""
    samples = np.asarray(samples, dtype=np.float32)
    if samples.size == 0:
        return ""

    _ensure_worker()
    future = Future()
    _queue.put((samples, language, context, future))
    return future.result(timeout=ASR_REQUEST_TIMEOUT)


def preload_in_background():
    """启动即后台预热。先加载权重并释放锁，再通过队列跑一次静音推理。
    不能持锁提交请求，否则工作线程等锁、预热线程等结果，会死锁。"""
    global _status, _error

    def worker():
        global _status, _error
        try:
            with _load_lock:
                get_model()
            _status = STATUS_WARMING
            transcribe_audio(np.zeros(SAMPLE_RATE, dtype=np.float32), language=None)
            _status = STATUS_READY
            transcribe_logger.info("模型已就绪，可以开始录音")
        except Exception as e:
            _status = STATUS_ERROR
            _error = str(e)
            transcribe_logger.error(f"模型预热失败: {e}")

    threading.Thread(target=worker, name='model-warmup', daemon=True).start()
