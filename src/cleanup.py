import os
import shutil
import sqlite3
import time

from config import AUDIO_DIR, DB_FILE, MAX_AUDIO_AGE_DAYS, MAX_AUDIO_FILES, TRANSCRIPT_DIR
from logger import app_logger

SESSION_MAX_AGE_SECONDS = 3600


def _drop_session_files(session_id):
    shutil.rmtree(os.path.join(AUDIO_DIR, session_id), ignore_errors=True)
    for name in os.listdir(TRANSCRIPT_DIR):
        if name.startswith(session_id):
            os.remove(os.path.join(TRANSCRIPT_DIR, name))


def _drop_session_rows(session_id):
    """文件与数据库必须同步清理，否则历史列表会指向不存在的文件"""
    with sqlite3.connect(DB_FILE) as conn:
        conn.execute("DELETE FROM records WHERE session_id = ?", (session_id,))
        conn.execute("DELETE FROM sessions WHERE session_id = ?", (session_id,))


def cleanup_old_sessions():
    """按会话维度删除过期数据：文件与数据库记录一起清掉"""
    if not os.path.isdir(AUDIO_DIR):
        return 0

    cutoff = time.time() - MAX_AUDIO_AGE_DAYS * 24 * 60 * 60
    sessions = [d for d in os.listdir(AUDIO_DIR) if os.path.isdir(os.path.join(AUDIO_DIR, d))]
    sessions.sort(key=lambda d: os.path.getmtime(os.path.join(AUDIO_DIR, d)))

    overflow = len(sessions) - MAX_AUDIO_FILES
    doomed = sessions[:overflow] if overflow > 0 else []
    doomed += [s for s in sessions if os.path.getmtime(os.path.join(AUDIO_DIR, s)) < cutoff]

    for session_id in set(doomed):
        _drop_session_files(session_id)
        _drop_session_rows(session_id)
        app_logger.info(f"清理过期会话: {session_id}")

    return len(set(doomed))


def cleanup_orphan_transcripts(active_sessions):
    """删除不属于任何现存会话的转录 txt"""
    deleted = 0
    for name in os.listdir(TRANSCRIPT_DIR):
        if any(name.startswith(s) for s in active_sessions):
            continue
        os.remove(os.path.join(TRANSCRIPT_DIR, name))
        deleted += 1
    return deleted


def cleanup_session_state(session_state_dict, max_age_seconds=SESSION_MAX_AGE_SECONDS):
    cutoff = time.time() - max_age_seconds
    stale = [
        session_id
        for session_id, state in session_state_dict.items()
        if cutoff > state.get('last_update', 0)
    ]
    for session_id in stale:
        del session_state_dict[session_id]
        app_logger.info(f"清理过期会话状态: {session_id}")
    return len(stale)
