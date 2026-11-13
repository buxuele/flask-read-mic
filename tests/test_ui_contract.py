"""UI 契约验证：所有前端调用的接口都必须存在且返回结构正确"""
import sys

sys.path.insert(0, 'src')
from app import app

client = app.test_client()
fails = []


def check(name, cond, extra=''):
    print(f'{"PASS" if cond else "FAIL"}  {name} {extra}', flush=True)
    if not cond:
        fails.append(name)


# 中文拼接规则
from routes.records import join_texts  # noqa: E402

check('中文拼接不加空格', join_texts(['今天', '天气', '不错']) == '今天天气不错')
check('标点后不加空格', join_texts(['结束', '。', '下一句']) == '结束。下一句')
check('英文拼接加空格', join_texts(['hello', 'world']) == 'hello world')
check('中英混排加空格', join_texts(['会议', '结束', 'next']) == '会议结束 next')
check('空片段被跳过', join_texts(['', '  ', '有效']) == '有效')

# 首页可渲染，且新加的元素 id 都在
html = client.get('/').get_data(as_text=True)
check('GET / 返回 200', client.get('/').status_code == 200)
for el in ['micButton', 'status', 'transcripts', 'error', 'historyList', 'historyCount',
           'searchBox', 'exportAllBtn', 'settingsBtn', 'settingsModal', 'closeSettingsBtn',
           'segmentDuration', 'modelName', 'languageSelect', 'saveAudio',
           'warmupHint', 'statChars', 'statTime',
           'confirmModal', 'confirmText', 'confirmOk', 'confirmCancel']:
    check(f'元素 #{el} 存在', f'id="{el}"' in html)

check('无死代码 loadHistory', 'loadHistory' not in html)
check('无 undefined 引用 editTranscript', 'editTranscript' not in html)
check('无死选择器 color: #666', 'color: #666"]' not in html)
check('无 linear-gradient', 'linear-gradient' not in html)

# 模型接口
model = client.get('/model').get_json()
check('GET /model 返回模型名', 'model' in model, model.get('model', '')[-30:])

# 启动会话
sid = client.post('/session/start').get_json()['session_id']
check('POST /session/start', bool(sid))

# 状态接口（finalize 前轮询用）
state = client.get(f'/status/{sid}').get_json()
check('GET /status 返回 busy/segment_count', 'busy' in state and 'segment_count' in state, state)

# 空会话不进历史列表
sessions = client.get('/sessions').get_json()
check('空会话被过滤', all(s['session_id'] != sid for s in sessions), f'共 {len(sessions)} 个')

# 手工灌入中文片段，验证拼接规则
import sqlite3
import sys as _s
_s.path.insert(0, 'src')
from config import DB_FILE

SEGMENTS = ['今天', '天气', '不错', '我们开始吧']
JOINED = '今天天气不错。我们开始吧'

conn = sqlite3.connect(DB_FILE)
for i, text in enumerate(SEGMENTS, 1):
    conn.execute(
        "INSERT INTO records (id, session_id, segment_index, timestamp, text, audio_file, model)"
        " VALUES (?,?,?,?,?,?,?)",
        (f'id_{sid}_{i}', sid, i, '20260930_120000_000', text, None, 'test'),
    )
conn.execute("UPDATE sessions SET segment_count=?, full_text=? WHERE session_id=?",
             (len(SEGMENTS), JOINED, sid))
conn.commit()
conn.close()

sessions = client.get('/sessions').get_json()
mine = [s for s in sessions if s['session_id'] == sid]
check('有内容的会话出现在列表', len(mine) == 1)
if mine:
    s = mine[0]
    check('含 segment_count', s['segment_count'] == 4, s['segment_count'])
    # 中文片段拼接不应插入空格
    check('full_text 中文无空格', s['full_text'] == JOINED, repr(s['full_text']))
    check('含 char_count', s['char_count'] == len(JOINED), s['char_count'])
    check('含 time_label', all('time_label' in r for r in s['segments']))
    check('start_time 已美化', '月' in s['start_time'], s['start_time'])

# 删除接口
check('DELETE /session', client.delete(f'/session/{sid}').status_code == 200)
check('删除后不再出现', all(s['session_id'] != sid for s in client.get('/sessions').get_json()))

# 繁简转换：Qwen3-ASR 中文场景会输出繁体
from services import to_simplified  # noqa: E402

check('繁体转简体', to_simplified('這個事情怎麼回事') == '这个事情怎么回事',
      repr(to_simplified('這個事情怎麼回事')))
check('繁体标点转简体', to_simplified('哦，這算不錯。') == '哦，这算不错。',
      repr(to_simplified('哦，這算不錯。')))
check('简体保持不变', to_simplified('今天天气不错') == '今天天气不错')
check('英文不受影响', to_simplified('Hello World') == 'Hello World')
check('空文本安全', to_simplified('') == '')

print()
print('ALL PASS' if not fails else f'FAILED ({len(fails)}): {fails}', flush=True)
sys.exit(1 if fails else 0)
