import os

# 路径配置
AUDIO_DIR = 'recordings/audio'
TRANSCRIPT_DIR = 'recordings/transcripts'
DB_FILE = 'recordings/data.db'

# 确保目录存在
os.makedirs(AUDIO_DIR, exist_ok=True)
os.makedirs(TRANSCRIPT_DIR, exist_ok=True)

# 模型配置
DEVICE = "cuda"
COMPUTE_TYPE = "float16"

# Flask 配置
MAX_CONTENT_LENGTH = 50 * 1024 * 1024
