"""
统一的 LLM 调用入口，按优先级依次尝试多个供应商。

密钥只从 .env 读取，代码里不出现明文。
任何一次失败都会让该供应商进入冷却期，避免每次请求都白等超时。
"""

import os
import threading
import time

from dotenv import load_dotenv
from openai import OpenAI

from logger import app_logger

load_dotenv()

REQUEST_TIMEOUT = 8
FAIL_COOLDOWN = 300

# (名称, base_url, 环境变量名, 模型)
PROVIDERS = [
    ("openrouter-primary", "https://openrouter.ai/api/v1", "OPENROUTER_API_KEY",
     os.getenv("OPENROUTER_PRIMARY_MODEL", "nvidia/nemotron-3.5-super-vl:free")),
    ("openrouter-lightning", "https://openrouter.ai/api/v1", "OPENROUTER_API_KEY",
     os.getenv("OPENROUTER_FALLBACK_MODEL", "nvidia/nemotron-3.5-lightning:free")),
    ("openrouter-dots", "https://openrouter.ai/api/v1", "OPENROUTER_API_KEY",
     os.getenv("OPENROUTER_FALLBACK_MODEL_2", "dots-studio/dots-3-note-preview:free")),
    ("nvidia-nim", "https://integrate.api.nvidia.com/v1", "NVIDIA_API_KEY",
     os.getenv("NVIDIA_MODEL", "nvidia/nemotron-3-super-120b-a12b")),
]

_lock = threading.Lock()
_failed_until = {}
_preferred = None


def _available(provider):
    name, base_url, key_env, model = provider
    if not os.getenv(key_env):
        return False
    return time.time() >= _failed_until.get(name, 0)


def _ordered():
    global _preferred
    usable = [p for p in PROVIDERS if _available(p)]
    if _preferred:
        usable.sort(key=lambda p: 0 if p[0] == _preferred else 1)
    return usable


def chat(prompt):
    """按优先级尝试，返回首个成功的文本；全部失败返回 None。"""
    global _preferred

    providers = _ordered()
    if not providers:
        app_logger.warning("没有可用的 LLM 供应商，跳过")
        return None

    for name, base_url, key_env, model in providers:
        try:
            client = OpenAI(
                base_url=base_url,
                api_key=os.getenv(key_env),
                timeout=REQUEST_TIMEOUT,
                max_retries=0,
            )
            started = time.time()
            response = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
            )
            content = (response.choices[0].message.content or "").strip()
            if not content:
                raise ValueError("空响应")
            with _lock:
                _preferred = name
            app_logger.info(f"LLM 命中 {name}/{model}（{time.time()-started:.2f}s）")
            return content
        except Exception as e:
            with _lock:
                _failed_until[name] = time.time() + FAIL_COOLDOWN
            app_logger.warning(f"LLM {name} 失败，冷却 {FAIL_COOLDOWN} 秒: {e}")

    app_logger.warning("所有 LLM 供应商均失败，本次跳过")
    return None


def reset_cooldowns():
    with _lock:
        _failed_until.clear()
