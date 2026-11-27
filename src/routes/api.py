"""
局域网语音识别 API。

    POST /api/v1/transcribe   上传音频，返回识别文本
    GET  /api/v1/health       健康检查（需鉴权）

鉴权：请求头 `X-API-Key: <key>` 或 `Authorization: Bearer <key>`。
接口默认关闭，需在 config.py 里把 API_ENABLED 打开并配置 API_KEY。
"""

import io
import time
from collections import defaultdict
from threading import Lock

import numpy as np
from flask import Blueprint, jsonify, request

import config
from config import (
    API_ALLOW_CORS,
    API_CORS_ORIGINS,
    API_ENABLED,
    API_KEY,
    API_MAX_SECONDS,
    API_RATE_LIMIT,
    API_RATE_WINDOW,
    LANGUAGE_MAP,
    SAMPLE_RATE,
)
from logger import app_logger
from services import transcribe_audio

api_bp = Blueprint('api', __name__, url_prefix=config.API_PREFIX)

_rate_state = defaultdict(list)
_rate_lock = Lock()

SUPPORTED_FORMATS = {'wav', 'webm', 'mp3', 'm4a', 'ogg', 'flac'}


def _client_ip():
    # 只在可信反向代理后才应采信 X-Forwarded-For，这里保守取直连地址
    return request.remote_addr or 'unknown'


def _rate_limited():
    now = time.time()
    ip = _client_ip()
    with _rate_lock:
        hits = [t for t in _rate_state[ip] if now - t < API_RATE_WINDOW]
        if len(hits) >= API_RATE_LIMIT:
            _rate_state[ip] = hits
            return True
        hits.append(now)
        _rate_state[ip] = hits
        return False


def _key_ok():
    if not API_KEY:
        return False
    provided = request.headers.get('X-API-Key', '')
    if not provided:
        auth = request.headers.get('Authorization', '')
        if auth.lower().startswith('bearer '):
            provided = auth[7:].strip()
    return provided == API_KEY


def _guard(fn):
    """统一前置校验：开关、鉴权、限流"""

    def wrapper(*args, **kwargs):
        # 浏览器 CORS 预检不带自定义头，必须在鉴权前放行
        if request.method == 'OPTIONS':
            return '', 204
        if not API_ENABLED:
            return jsonify({'error': 'API 未启用'}), 503
        if not _key_ok():
            return jsonify({'error': '无效的 API Key'}), 401
        if _rate_limited():
            return jsonify({'error': '请求过于频繁，请稍后再试'}), 429
        return fn(*args, **kwargs)

    wrapper.__name__ = fn.__name__
    return wrapper


def _decode_audio(raw):
    """任意常见容器 -> 16kHz 单声道 float32 ndarray"""
    import numpy as np
    from pydub import AudioSegment

    segment = AudioSegment.from_file(io.BytesIO(raw))
    segment = segment.set_channels(1).set_frame_rate(SAMPLE_RATE)
    return np.array(segment.get_array_of_samples(), dtype=np.float32) / 32768.0


@api_bp.after_request
def _add_cors(response):
    if API_ALLOW_CORS:
        response.headers['Access-Control-Allow-Origin'] = API_CORS_ORIGINS
        response.headers['Access-Control-Allow-Headers'] = 'Content-Type, X-API-Key, Authorization'
        response.headers['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS'
    return response


@api_bp.route('/transcribe', methods=['POST', 'OPTIONS'])
@_guard
def transcribe():
    if request.method == 'OPTIONS':
        return '', 204

    if 'audio' not in request.files:
        return jsonify({'error': '缺少 audio 文件字段'}), 400

    file = request.files['audio']
    if not file.filename:
        return jsonify({'error': '文件名为空'}), 400

    language = request.form.get('language', 'auto')
    if language not in LANGUAGE_MAP:
        return jsonify({'error': f'不支持的语言：{language}，可选 {list(LANGUAGE_MAP)}'}), 400

    context = request.form.get('context', '')[:1000]

    raw = file.read()
    if not raw:
        return jsonify({'error': '音频内容为空'}), 400

    # 裸 PCM 跳过解码与重采样，客户端直接传 16kHz 单声道 int16 小端。
    # 手机或脚本端录音本来就是 PCM，这一步能省掉一次 ffmpeg 解码。
    wants_pcm = (
        request.form.get('format') == 'pcm'
        or file.mimetype in ('audio/pcm', 'audio/l16', 'application/octet-stream')
    )
    if wants_pcm:
        if len(raw) % 2 != 0:
            return jsonify({'error': 'PCM 字节数必须为偶数，int16 小端'}), 400
        samples = np.frombuffer(raw, dtype='<i2').astype(np.float32) / 32768.0
    else:
        try:
            samples = _decode_audio(raw)
        except Exception as e:
            return jsonify({'error': f'音频解码失败：{e}'}), 400

    duration = len(samples) / SAMPLE_RATE
    if duration > API_MAX_SECONDS:
        return jsonify({'error': f'音频过长 {duration:.0f}s，上限 {API_MAX_SECONDS}s'}), 413
    if duration < 0.1:
        return jsonify({'error': '音频太短'}), 400

    try:
        text = transcribe_audio(samples, language=LANGUAGE_MAP[language], context=context)
    except Exception as e:
        app_logger.error(f"API 转录失败: {e}")
        return jsonify({'error': f'识别失败：{e}'}), 500

    app_logger.info(f"API 转录 {duration:.1f}s 来自 {_client_ip()} -> {text[:40]}")
    return jsonify({
        'text': text,
        'language': language,
        'duration': round(duration, 2),
        'model': config.ASR_MODEL_ID,
    })


@api_bp.route('/health', methods=['GET'])
@_guard
def health():
    from services import _cuda_available

    try:
        import torch

        version = torch.__version__
    except ImportError:
        version = '未加载'

    return jsonify({
        'status': 'ok',
        'model': config.ASR_MODEL_ID,
        'device': config.ASR_DEVICE if _cuda_available() else 'cpu',
        'torch': version,
        'languages': list(LANGUAGE_MAP),
        'max_seconds': API_MAX_SECONDS,
    })
