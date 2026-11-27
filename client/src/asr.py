import threading
import time

import requests

import config

_local = threading.local()


def session():
    if not hasattr(_local, "session"):
        _local.session = requests.Session()
    return _local.session


def _headers():
    return {"X-API-Key": config.ASR_KEY}


def transcribe(wav_bytes, language=None, context=None):
    if not config.ASR_URL:
        raise RuntimeError("未配置 ASR_URL")
    if not config.ASR_KEY:
        raise RuntimeError("未配置 ASR_KEY")

    for attempt in range(3):
        try:
            response = session().post(
                f"{config.ASR_URL}/transcribe",
                headers=_headers(),
                files={"audio": ("speech.wav", wav_bytes, "audio/wav")},
                data=_form(language, context),
                timeout=(5, 60),
            )
        except (requests.ConnectionError, requests.Timeout):
            if attempt == 2:
                raise
            time.sleep(0.8)
            continue
        if response.status_code in (429, 502, 503, 504) and attempt < 2:
            try:
                wait = float(response.headers.get("Retry-After", "2"))
            except ValueError:
                wait = 2.0
            time.sleep(min(wait, 4.0))
            continue
        break
    if response.status_code != 200:
        try:
            detail = response.json().get("error", "")
        except ValueError:
            detail = response.text[:200]
        raise RuntimeError(f"识别失败 {response.status_code} {detail}".strip())

    payload = response.json()
    return (payload.get("text") or "").strip()


def _form(language, context):
    data = {"language": language or config.LANGUAGE}
    if context:
        data["context"] = context[:1000]
    return data


def health(timeout=3):
    if not config.ASR_URL:
        return False
    try:
        response = session().get(f"{config.ASR_URL}/health", headers=_headers(), timeout=timeout)
    except requests.RequestException:
        return False
    return response.status_code == 200
