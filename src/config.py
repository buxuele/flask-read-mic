import os

# 所有路径锚定到 src/ 目录，不受启动时工作目录影响
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(BASE_DIR)

# 路径配置
DATA_DIR = os.path.join(BASE_DIR, 'recordings')
AUDIO_DIR = os.path.join(DATA_DIR, 'audio')
TRANSCRIPT_DIR = os.path.join(DATA_DIR, 'transcripts')
DB_FILE = os.path.join(DATA_DIR, 'data.db')

os.makedirs(AUDIO_DIR, exist_ok=True)
os.makedirs(TRANSCRIPT_DIR, exist_ok=True)

# 模型配置：本地权重目录优先，缺失时回落到 HuggingFace 仓库 ID
LOCAL_ASR_DIR = os.path.join(ROOT_DIR, 'models', 'Qwen3-ASR-0.6B')
ASR_MODEL_ID = LOCAL_ASR_DIR if os.path.isdir(LOCAL_ASR_DIR) else "Qwen/Qwen3-ASR-0.6B"
ASR_DTYPE = "bfloat16"
ASR_DEVICE = "cuda:0"
ASR_MAX_NEW_TOKENS = 256
ASR_BATCH_SIZE = 8

# 滑窗与切片：单次送入模型的音频上限，超出则最旧片段被挤掉并触发封窗
MAX_WINDOW_SECONDS = 8
SAMPLE_RATE = 16000

# 作为 context 喂回模型的历史文本长度上限，防止 prompt 无界膨胀
CONTEXT_CHARS = 500

# 语言映射：前端选项 -> Qwen3-ASR 规范语言名。None 表示自动语种识别
LANGUAGE_MAP = {
    "zh": "Chinese",
    "en": "English",
    "auto": None,
}

# 资源清理：超过天数的文件删除，会话数超过上限时从最旧的整段删除
MAX_AUDIO_AGE_DAYS = 30
MAX_AUDIO_FILES = 200

# ---------- 服务监听 ----------
SERVER_HOST = "127.0.0.1"      # 改为 "0.0.0.0" 才允许局域网访问
# 端口要同时避开两类禁区：
# 1. Windows TCP 排除范围（常见 5041-5840，Hyper-V / WSL 预留），绑定报 WinError 10013
# 2. Chromium 不安全端口清单（如 6000 是 X11），浏览器直接 ERR_UNSAFE_PORT
# 6100 两者都不冲突。run_all.py 会从这里起自动 +1 找可用端口，
# 并通过 ASR_SERVER_PORT 把真实端口传给全部组件。
SERVER_PORT = int(os.getenv("ASR_SERVER_PORT", "6100"))
SERVER_DEBUG = False            # 绝不能开：Werkzeug 调试器可被用来执行任意代码

# ---------- 功能开关 ----------
# 指令模式暂时停用：后端意图解析代码保留，前端不再暴露入口。
# 以后要恢复，只需把这里改成 True 并重新加回界面按钮。
COMMAND_MODE_ENABLED = False

# ---------- 转录质量审计 ----------
# 默认关闭。开启后只在后台用 LLM 对照 ASR 结果并写审计日志，
# 绝不改写用户看到的文字，也不参与任何出字路径。
AUDIT_ENABLED = os.getenv("ASR_AUDIT", "0") == "1"
AUDIT_DIR = os.path.join(DATA_DIR, "audit")

# ---------- 局域网 API ----------
# 独立线程监听 0.0.0.0，供同网段的 Mac、手机直接调用。
# 与主网页服务同进程，共用同一份已加载模型，不会额外占显存。
LAN_API_ENABLED = os.getenv("ASR_LAN_API", "1") == "1"
LAN_API_HOST = os.getenv("ASR_LAN_HOST", "0.0.0.0")
LAN_API_PORT = int(os.getenv("ASR_LAN_PORT", "6101"))
LAN_API_CORS = True             # 手机浏览器跨域调用时必需
LAN_API_KEY_FILE = os.path.join(DATA_DIR, ".lan_api_key")
LAN_API_RUNTIME_FILE = os.path.join(DATA_DIR, ".lan_api.json")

API_ENABLED = False             # 网页同域 API 开关，与上面的独立线程互不影响
API_KEY = os.getenv("ASR_API_KEY", "")   # 留空则自动生成并持久化
API_PREFIX = "/api/v1"
API_MAX_UPLOAD_MB = 25          # 单次请求音频上限，ASR 场景没必要更大
API_RATE_LIMIT = 30             # 每分钟每 IP 允许的请求数
API_RATE_WINDOW = 60            # 限流窗口（秒）
API_MAX_SECONDS = 300           # 单次音频最长时长，超出直接拒绝
API_ALLOW_CORS = False          # 网页同域 API 的 CORS，默认关闭
API_CORS_ORIGINS = "*"

# Flask 配置
MAX_CONTENT_LENGTH = API_MAX_UPLOAD_MB * 1024 * 1024
