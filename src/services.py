import os
import threading

import numpy as np

from config import (
    ASR_BATCH_SIZE,
    ASR_DEVICE,
    ASR_DTYPE,
    ASR_MAX_NEW_TOKENS,
    ASR_MODEL_ID,
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


_DTYPE_NAMES = ('bfloat16', 'float16', 'float32')

STATUS_IDLE = 'idle'        # 尚未开始加载
STATUS_LOADING = 'loading'  # 正在加载权重
STATUS_WARMING = 'warming'  # 权重就绪，正在跑首次推理预热 CUDA kernel
STATUS_READY = 'ready'      # 可用
STATUS_ERROR = 'error'      # 加载失败

_load_lock = threading.RLock()   # 用可重入锁，warmup 内部还会再调 get_model
_infer_lock = threading.Lock()
_model = None
_status = STATUS_IDLE
_error = None


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


def preload_in_background():
    """启动即后台预热。权重加载约 4 秒，首次推理预热约 13 秒，
    两者都做完，第一次真实录音才能秒出结果。"""
    global _status, _error

    def worker():
        global _status, _error
        try:
            with _load_lock:
                model = get_model()
                _status = STATUS_WARMING
                # 用 1 秒静音跑一次推理，把 CUDA kernel 编译成本提前付掉
                transcribe_audio(np.zeros(SAMPLE_RATE, dtype=np.float32), language=None)
            _status = STATUS_READY
            transcribe_logger.info("模型已就绪，可以开始录音")
        except Exception as e:
            _status = STATUS_ERROR
            _error = str(e)
            transcribe_logger.error(f"模型预热失败: {e}")

    threading.Thread(target=worker, name='model-warmup', daemon=True).start()


def transcribe_audio(samples, language, context=""):
    """samples: 16kHz 单声道 float32 ndarray。language: 规范语言名或 None。"""
    samples = np.asarray(samples, dtype=np.float32)
    if samples.size == 0:
        return ""

    # 加载锁与推理锁必须分开，否则同线程重复获取非重入锁会死锁
    with _load_lock:
        model = get_model()

    with _infer_lock:
        results = model.transcribe(
            audio=(samples, SAMPLE_RATE),
            context=context,
            language=language,
        )

    text = results[0].text.strip()
    detected = results[0].language
    if detected == "Chinese":
        text = to_simplified(text)
    return text
