"""UI 静态契约检查：确保前端引用的接口、元素存在，且无死代码与被禁样式"""
import pathlib
import re
import sys

sys.path.insert(0, pathlib.Path(__file__).resolve().parent.parent / 'src')

HTML = pathlib.Path(__file__).resolve().parent.parent / 'src' / 'templates' / 'index.html'
text = HTML.read_text(encoding='utf-8')

fails = []


def check(name, cond, extra=''):
    print(f'{"PASS" if cond else "FAIL"}  {name} {extra}', flush=True)
    if not cond:
        fails.append(name)


REQUIRED = [
    ('模型名剥掉盘符路径', "split(/[\\\\/]/).pop()"),
    ('空格键开始停止', "e.code === 'Space'"),
    ('Esc 关闭弹窗兼停止录音', "e.key === 'Escape'"),
    ('finalize 前等待最后一片', 'waitForTranscription'),
    ('侧边栏防抖刷新', 'scheduleReload'),
    ('删除二次确认', 'confirmAction'),
    ('中文无空格拼接', 'cjkEdge'),
    ('错误提示自动消失', 'errorTimer'),
    ('模型预热提示', 'warmupHint'),
    ('麦克风权限错误处理', 'NotAllowedError'),
    ('实时字数统计', 'statChars'),
    ('历史空状态', 'empty-hint'),
    ('焦点可见性', 'focus-visible'),
    ('危险按钮样式', 'danger-btn'),
    ('剪贴板失败兜底', '复制失败'),
    ('响应式断点', '@media (max-width: 860px)'),
    ('窄屏侧栏覆盖层', 'position: fixed'),
    ('窄屏侧栏遮罩', 'sidebar-scrim'),
    ('窄屏默认折叠', 'max-width: 560px)'),
    ('减弱动效偏好', 'prefers-reduced-motion'),
    ('刷新页面保护', 'beforeunload'),
    ('后台可见性提示', 'visibilitychange'),
    ('文本可选择', 'user-select: text'),
    ('上传失败重试', 'UPLOAD_RETRIES'),
    ('搜索防抖', 'searchTimer'),
    ('搜索结果计数', 'searchCount'),
    ('骨架屏', 'renderSkeleton'),
    ('批量插入防卡顿', 'createDocumentFragment'),
    ('主区空状态引导', 'empty-stage'),
    ('空闲隐藏可视化器', 'visualizer-container idle'),
    ('纵向堆叠不并排', 'flex-direction: column'),
]

FORBIDDEN = [
    ('无死 CSS .controls', '.controls {'),
    ('无死 CSS .history-item', '.history-item'),
    ('无死 CSS .setting-input', '.setting-input'),
    ('无死 CSS editing 态', 'transcript-text.editing'),
    ('禁止渐变', 'linear-gradient'),
    ('统一主色无橙色', '#f88'),
    ('无死函数 loadHistory', 'loadHistory'),
    ('无死函数 editTranscript', 'editTranscript'),
    ('无死函数 deleteTranscript', 'deleteTranscript'),
    ('无失效选择器', 'color: #666"]'),
    ('无指令模式入口', '指令模式'),
    ('无指令模式按钮', 'modeCommand'),
    ('无模式切换样式', '.mode-toggle'),
]

# innerHTML 只允许清空赋值（= ''），任何拼接 HTML 的写法都禁止
inner_html_assigns = re.findall(r'innerHTML\s*=\s*([^;\n]+)', text)
risky = [a.strip() for a in inner_html_assigns if a.strip() not in ("''", '""')]
check('innerHTML 仅用于清空', not risky, str(risky))

for name, needle in REQUIRED:
    check(name, needle in text)

for name, needle in FORBIDDEN:
    check(name, needle not in text)

# 标签配对
for tag in ('div', 'button', 'span', 'svg'):
    opened = len(re.findall(r'<' + tag + r'[\s>]', text))
    closed = len(re.findall(r'</' + tag + r'>', text))
    check(f'<{tag}> 配对', opened == closed, f'{opened}/{closed}')

# CSS 类是否都被用到
css = text[text.find('<style>'):text.find('</style>')]
body = text[text.find('</style>'):]
classes = set(re.findall(r'\.([a-zA-Z][\w-]*)\s*[,{:]', css))
unused = sorted(c for c in classes if c not in body)
check('无未被使用的 CSS 类', not unused, str(unused))

print()
print('ALL PASS' if not fails else f'FAILED ({len(fails)}): {fails}', flush=True)
sys.exit(1 if fails else 0)
