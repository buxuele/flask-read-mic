import sqlite3
from config import DB_FILE

def get_db():
    conn = sqlite3.connect(DB_FILE, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn

def init_db():
    with get_db() as conn:
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
