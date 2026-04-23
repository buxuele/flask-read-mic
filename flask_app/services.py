import os
import site
import sys
from faster_whisper import WhisperModel

# 自动定位并通过系统路径加载 NVIDIA CUDA DLL 文件
def add_cuda_to_path():
    # 优先查找当前 Python 环境下的 site-packages
    try:
        paths = site.getsitepackages()
        for p in paths:
            nvidia_base = os.path.join(p, "nvidia")
            if os.path.exists(nvidia_base):
                for sub_pkg in os.listdir(nvidia_base):
                    bin_path = os.path.join(nvidia_base, sub_pkg, "bin")
                    if os.path.exists(bin_path):
                        if bin_path not in os.environ["PATH"]:
                            os.environ["PATH"] = bin_path + os.pathsep + os.environ["PATH"]
    except Exception as e:
        print(f"Warning: Failed to auto-configure CUDA DLL paths: {e}")

add_cuda_to_path()

from config import DEVICE, COMPUTE_TYPE

_models = {}

def get_model(model_name='medium'):
    if model_name not in _models:
        print(f"Loading model: {model_name} on {DEVICE} ({COMPUTE_TYPE})")
        _models[model_name] = WhisperModel(model_name, device=DEVICE, compute_type=COMPUTE_TYPE)
        print(f"Model {model_name} loaded.")
    return _models[model_name]

def transcribe_audio(wav_path, model_name, language):
    model = get_model(model_name)
    
    # 显著加强 Prompt 诱导：要求多标点、结构化、无语气词
    prompt = "这是一段访谈对谈录音，包含详细的逗号、问号、感叹号。标点符号要多，结构要清晰，去掉无意义的语气助词。" if language == 'zh' else "This is a structured interview with plenty of commas, periods, and question marks. Punctuation should be rich and grammar should be perfect."
    
    segments, _ = model.transcribe(
        wav_path,
        language=language,
        vad_filter=True,
        vad_parameters=dict(min_silence_duration_ms=1000),
        beam_size=5,
        without_timestamps=True,
        initial_prompt=prompt
    )
    text = " ".join([s.text.strip() for s in segments if s.text.strip()])

    if language == 'zh' and text:
        from opencc import OpenCC
        cc = OpenCC('t2s')
        text = cc.convert(text)

    return text
