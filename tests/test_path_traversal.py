"""路径穿越防护验证"""
import sys

sys.path.insert(0, 'src')
from app import app

client = app.test_client()
fails = []


def check(name, cond, extra=''):
    print(f'{"PASS" if cond else "FAIL"}  {name} {extra}', flush=True)
    if not cond:
        fails.append(name)


attacks = [
    '../.env',
    '../../.env',
    '../../../Windows/win.ini',
    '..\\..\\.env',
    'sess/../../.env',
    '/../../.env',
]
for path in attacks:
    # follow_redirects 必须开：308 只是 Werkzeug 的路径规范化，真实客户端会重发
    r = client.get('/audio/' + path, follow_redirects=True)
    blocked = r.status_code in (403, 404)
    leaked = b'OPENROUTER' in r.data or b'microsoft' in r.data.lower()
    check(f'阻断 {path!r}', blocked and not leaked, f'status={r.status_code}')

# URL 编码绕过
r = client.get('/audio/..%2f..%2f.env', follow_redirects=True)
check('阻断 URL 编码穿越', r.status_code in (403, 404) and b'OPENROUTER' not in r.data,
      f'status={r.status_code}')

r = client.get('/audio/nonexistent.wav')
check('不存在的文件返回 404', r.status_code == 404, str(r.status_code))

r = client.get('/audio/')
check('空路径不 500', r.status_code in (403, 404, 308), str(r.status_code))

print()
print('ALL PASS' if not fails else f'FAILED ({len(fails)}): {fails}', flush=True)
sys.exit(1 if fails else 0)
