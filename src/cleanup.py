import os
import time
from datetime import datetime, timedelta
from config import AUDIO_DIR, TRANSCRIPT_DIR
from database import get_db
from logger import app_logger

MAX_AUDIO_AGE_DAYS = 30
MAX_AUDIO_COUNT = 1000

def cleanup_old_files():
    app_logger.info("开始清理旧文件...")
    
    cutoff_time = time.time() - (MAX_AUDIO_AGE_DAYS * 24 * 60 * 60)
    deleted_count = 0
    
    for root, dirs, files in os.walk(AUDIO_DIR):
        for file in files:
            file_path = os.path.join(root, file)
            if os.path.getmtime(file_path) < cutoff_time:
                os.remove(file_path)
                deleted_count += 1
                app_logger.info(f"删除旧音频文件: {file_path}")
    
    for root, dirs, files in os.walk(TRANSCRIPT_DIR):
        for file in files:
            file_path = os.path.join(root, file)
            if os.path.getmtime(file_path) < cutoff_time:
                os.remove(file_path)
                deleted_count += 1
                app_logger.info(f"删除旧转录文件: {file_path}")
    
    app_logger.info(f"清理完成，共删除 {deleted_count} 个文件")
    return deleted_count

def cleanup_session_state(session_state_dict, max_age_seconds=3600):
    current_time = time.time()
    to_delete = []
    
    for session_id, state in session_state_dict.items():
        if 'last_update' in state:
            if current_time - state['last_update'] > max_age_seconds:
                to_delete.append(session_id)
    
    for session_id in to_delete:
        del session_state_dict[session_id]
        app_logger.info(f"清理过期会话状态: {session_id}")
    
    return len(to_delete)
