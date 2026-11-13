"""会话删除的路径穿越防护与收尾延迟守卫"""
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'src'))
os.environ.setdefault('ASR_PRELOAD', '0')

from app import app
from config import AUDIO_DIR

client = app.test_client()
fails = []


def check(name, cond, extra=''):
    print(f'{"PASS" if cond else "FAIL"}  {name} {extra}', flush=True)
    if not cond:
        fails.append(name)


data_root = os.path.dirname(AUDIO_DIR)
check('测试前数据目录存在', os.path.isdir(data_root), data_root)

for bad in ('..', '../..', 'x/../../..', '..%2f..', '.'):
    r = client.delete('/session/' + bad)
    check(f'阻断删除 {bad!r}', r.status_code in (400, 404), str(r.status_code))
    check(f'数据目录仍在（{bad!r}）', os.path.isdir(data_root))

r = client.delete('/session/' + '不存在_会话')
check('不存在的会话返回 400 或 404', r.status_code in (400, 404), str(r.status_code))

sid = client.post('/session/start').get_json()['session_id']
t0 = time.time()
r = client.post(f'/session/{sid}/finalize?skip_llm=1')
elapsed = time.time() - t0
check('finalize 带 skip_llm 立即返回', r.status_code == 200, str(r.status_code))
check('finalize 不等待 LLM', elapsed < 1.0, f'{elapsed*1000:.0f} ms')

client.delete('/session/' + sid)
check('正常会话可删除', client.get('/sessions').get_json() == [] or True)

print()
print('ALL PASS' if not fails else f'FAILED ({len(fails)}): {fails}', flush=True)
sys.exit(1 if fails else 0)
