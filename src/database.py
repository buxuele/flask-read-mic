import sqlite3
from flask import g
from config import DB_FILE
from logger import db_logger

MAX_RETRIES = 3

def get_db():
    if 'db' not in g:
        for attempt in range(MAX_RETRIES):
            try:
                g.db = sqlite3.connect(DB_FILE, timeout=10)
                g.db.row_factory = sqlite3.Row
                g.db.execute("PRAGMA journal_mode=WAL")
                break
            except Exception as e:
                db_logger.warning(f"数据库连接尝试 {attempt + 1}/{MAX_RETRIES} 失败: {e}")
                if attempt == MAX_RETRIES - 1:
                    db_logger.error(f"数据库连接失败，已重试 {MAX_RETRIES} 次")
                    raise
    return g.db

def close_db(e=None):
    db = g.pop('db', None)
    if db is not None:
        db.close()

def init_db():
    try:
        conn = sqlite3.connect(DB_FILE, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.executescript('''
        CREATE TABLE IF NOT EXISTS sessions (
            session_id TEXT PRIMARY KEY,
            start_time TEXT NOT NULL,
            end_time TEXT,
            segment_count INTEGER DEFAULT 0,
            full_text TEXT DEFAULT '',
            merged_audio TEXT
        );
        CREATE TABLE IF NOT EXISTS records (
            id TEXT PRIMARY KEY,
            session_id TEXT NOT NULL,
            segment_index INTEGER NOT NULL,
            timestamp TEXT NOT NULL,
            text TEXT NOT NULL,
            audio_file TEXT,
            model TEXT,
            FOREIGN KEY (session_id) REFERENCES sessions(session_id)
        );
        ''')
        conn.commit()
        conn.close()
        db_logger.info("数据库表初始化成功")
    except Exception as e:
        db_logger.error(f"数据库初始化失败: {e}")
        raise
