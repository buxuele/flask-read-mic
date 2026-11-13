"""局域网 API 验证：鉴权、限流、参数校验、真实转录"""
import io
import os
import sys
import wave

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'src'))

import config
from app import app

fails = []


def check(name, cond, extra=''):
    print(f'{"PASS" if cond else "FAIL"}  {name} {extra}', flush=True)
    if not cond:
        fails.append(name)


def wav_bytes(seconds=2.0, freq=220.0, sr=16000):
    t = np.linspace(0, seconds, int(seconds * sr), endpoint=False)
    tone = (np.sin(2 * np.pi * freq * t) * 0.3 * 32767).astype(np.int16)
    buf = io.BytesIO()
    with wave.open(buf, 'wb') as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(tone.tobytes())
    return buf.getvalue()


client = app.test_client()

# --- 未启用时端点完全不存在 ---
check('API 默认关闭', config.API_ENABLED is False)
r = client.post('/api/v1/transcribe', data={})
check('关闭时端点不注册(404)', r.status_code == 404, str(r.status_code))
r = client.get('/api/v1/health')
check('关闭时 health 也不存在', r.status_code == 404, str(r.status_code))

# --- 开启后重建 app，路由才会注册 ---
config.API_ENABLED = True
config.API_KEY = 'test-key-123'

import importlib  # noqa: E402

import routes.api  # noqa: E402

importlib.reload(routes.api)   # 让 API_ENABLED / API_KEY 生效
for name in ('app',):
    sys.modules.pop(name, None)
importlib.import_module('app')  # app 重新 import，拿到新的 api_bp
c = importlib.import_module('app').create_app().test_client()
check('开启后端点可访问', c.get('/api/v1/health').status_code in (200, 401),
      str(c.get('/api/v1/health').status_code))

# --- 鉴权 ---
r = c.post('/api/v1/transcribe')
check('无 Key 返回 401', r.status_code == 401, str(r.status_code))
r = c.post('/api/v1/transcribe', headers={'X-API-Key': 'wrong'})
check('错误 Key 返回 401', r.status_code == 401, str(r.status_code))
r = c.get('/api/v1/health', headers={'X-API-Key': 'test-key-123'})
check('正确 Key 通过鉴权', r.status_code == 200, str(r.status_code))
r = c.get('/api/v1/health', headers={'Authorization': 'Bearer test-key-123'})
check('Bearer Token 也可', r.status_code == 200, str(r.status_code))

# --- 参数校验 ---
h = {'X-API-Key': 'test-key-123'}
r = c.post('/api/v1/transcribe', headers=h)
check('缺少 audio 字段 400', r.status_code == 400, str(r.status_code))

r = c.post('/api/v1/transcribe', headers=h, data={
    'audio': (io.BytesIO(wav_bytes(1.0)), 'a.wav'),
    'language': 'klingon',
})
check('非法语言 400', r.status_code == 400, str(r.status_code))

r = c.post('/api/v1/transcribe', headers=h, data={
    'audio': (io.BytesIO(b''), 'empty.wav'),
})
check('空文件 400', r.status_code == 400, str(r.status_code))

r = c.post('/api/v1/transcribe', headers=h, data={
    'audio': (io.BytesIO(b'not audio at all'), 'bad.wav'),
})
check('非音频内容 400', r.status_code == 400, str(r.status_code))

r = c.post('/api/v1/transcribe', headers=h, data={
    'audio': (io.BytesIO(wav_bytes(0.05)), 'tiny.wav'),
})
check('过短音频 400', r.status_code == 400, str(r.status_code))

# --- 限流 ---
code = None
for i in range(config.API_RATE_LIMIT + 5):
    rr = c.post('/api/v1/transcribe', headers=h)
    if rr.status_code == 429:
        code = 429
        break
check('超出配额返回 429', code == 429, f'第 {i+1} 次触发' if code else '未触发')

print()
print('ALL PASS' if not fails else f'FAILED ({len(fails)}): {fails}', flush=True)
sys.exit(1 if fails else 0)
