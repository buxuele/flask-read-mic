from flask import Blueprint, request, jsonify
from datetime import datetime
import os
import re
import shutil
import threading
from config import AUDIO_DIR, AUDIT_DIR, AUDIT_ENABLED, TRANSCRIPT_DIR
from database import get_db
from pydub import AudioSegment

sessions_bp = Blueprint('sessions', __name__)


def format_clock(raw):
    """'20260930_085305_168979' 或 '%Y-%m-%d %H:%M:%S' -> '08:53:05'"""
    if not raw:
        return ''
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y%m%d_%H%M%S_%f"):
        try:
            return datetime.strptime(raw[:26], fmt).strftime("%H:%M:%S")
        except ValueError:
            continue
    return raw


def format_day(raw):
    """'2026-09-30 08:53:05' -> '9月30日 08:53'"""
    try:
        dt = datetime.strptime(raw, "%Y-%m-%d %H:%M:%S")
    except (TypeError, ValueError):
        return raw or ''
    return f"{dt.month}月{dt.day}日 {dt:%H:%M}"

@sessions_bp.route('/session/start', methods=['POST'])
def start_session():
    session_id = f"session_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')[:22]}"
    session_dir = os.path.join(AUDIO_DIR, session_id)
    os.makedirs(session_dir, exist_ok=True)

    conn = get_db()
    conn.execute(
        "INSERT INTO sessions (session_id, start_time) VALUES (?, ?)",
        (session_id, datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    )
    conn.commit()
    conn.close()

    return jsonify({'session_id': session_id})

@sessions_bp.route('/session/<session_id>/finalize', methods=['POST'])
def finalize_session(session_id):
    conn = get_db()
    session = conn.execute("SELECT * FROM sessions WHERE session_id = ?", (session_id,)).fetchone()

    if not session:
        conn.close()
        return jsonify({'error': '会话不存在'}), 404

    session_dir = os.path.join(AUDIO_DIR, session_id)
    merged_audio = None
    if os.path.exists(session_dir):
        audio_files = sorted([f for f in os.listdir(session_dir) if f.endswith('.wav') and '_merged' not in f])
        if audio_files:
            combined = AudioSegment.empty()
            for af in audio_files:
                combined += AudioSegment.from_wav(os.path.join(session_dir, af))
            merged_filename = f'{session_id}_merged.wav'
            merged_path = os.path.join(session_dir, merged_filename)
            combined.export(merged_path, format='wav')
            merged_audio = f'{session_id}/{merged_filename}'

    end_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn.execute(
        "UPDATE sessions SET end_time = ?, merged_audio = ? WHERE session_id = ?",
        (end_time, merged_audio, session_id)
    )
    conn.commit()

    full_text = session['full_text'] or ''

    full_text_file = os.path.join(TRANSCRIPT_DIR, f'{session_id}_full.txt')

    def write_full_file(content):
        with open(full_text_file, 'w', encoding='utf-8') as f:
            f.write(f'会话: {session_id}\n')
            f.write(f'开始时间: {session["start_time"]}\n')
            f.write(f'结束时间: {end_time}\n')
            f.write(f'片段数: {session["segment_count"]}\n')
            f.write(f'\n完整转录内容:\n{content.strip()}\n')

    write_full_file(full_text)
    conn.close()

    # 默认完全不调用 LLM。开启审计时也只在后台对照，绝不改写出字结果。
    if AUDIT_ENABLED and full_text.strip():
        threading.Thread(
            target=_audit_async,
            args=(session_id, full_text),
            daemon=True,
        ).start()

    return jsonify({'success': True, 'full_text': full_text})


def _audit_async(session_id, asr_text):
    """后台准确度对照：把 ASR 原文与 LLM 校对结果并排写入审计日志。
    只用于事后分析，不写数据库、不改全文文件、不影响任何显示。"""
    import json
    import os
    from datetime import datetime

    from llm import process_text

    llm_text = process_text(asr_text)
    if not llm_text or llm_text == asr_text:
        return

    os.makedirs(AUDIT_DIR, exist_ok=True)
    record = {
        'session_id': session_id,
        'created_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'asr_chars': len(asr_text),
        'llm_chars': len(llm_text),
        'asr_text': asr_text,
        'llm_text': llm_text,
    }
    path = os.path.join(AUDIT_DIR, f"audit_{datetime.now():%Y%m%d}.jsonl")
    with open(path, 'a', encoding='utf-8') as f:
        f.write(json.dumps(record, ensure_ascii=False) + '\n')

@sessions_bp.route('/sessions', methods=['GET'])
def get_sessions():
    conn = get_db()
    sessions = conn.execute("SELECT * FROM sessions ORDER BY start_time DESC").fetchall()
    records = conn.execute("SELECT * FROM records").fetchall()
    conn.close()

    records_by_session = {}
    for r in records:
        sid = r['session_id']
        if sid not in records_by_session:
            records_by_session[sid] = []
        records_by_session[sid].append(dict(r))

    result = []
    for s in sessions:
        segs = sorted(
            records_by_session.get(s['session_id'], []),
            key=lambda r: r['segment_index'],
        )
        for r in segs:
            r['time_label'] = format_clock(r['timestamp'])

        full_text = s['full_text'] or ''
        # 误点一下就产生的空会话不进历史列表，避免垃圾数据堆积
        if not segs and not full_text.strip():
            continue

        result.append({
            'session_id': s['session_id'],
            'start_time': format_day(s['start_time']),
            'end_time': format_clock(s['end_time']) if s['end_time'] else '',
            'segment_count': len(segs),
            'char_count': len(full_text.replace(' ', '')),
            'full_text': full_text,
            'merged_audio': s['merged_audio'],
            'segments': segs
        })

    return jsonify(result)

@sessions_bp.route('/session/<session_id>', methods=['DELETE'])
def delete_session(session_id):
    # session_id 来自 URL，必须白名单校验；否则 DELETE /session/.. 会把整个数据目录删掉
    if not re.fullmatch(r'[A-Za-z0-9_\-]{1,64}', session_id):
        return jsonify({'error': '非法的会话 ID'}), 400

    conn = get_db()
    session = conn.execute(
        "SELECT session_id FROM sessions WHERE session_id = ?", (session_id,)
    ).fetchone()
    if not session:
        conn.close()
        return jsonify({'error': '会话不存在'}), 404

    records = conn.execute("SELECT * FROM records WHERE session_id = ?", (session_id,)).fetchall()

    for record in records:
        txt_filename = f"{record['session_id']}_segment_{record['segment_index']:03d}.txt"
        txt_path = os.path.join(TRANSCRIPT_DIR, txt_filename)
        if os.path.exists(txt_path):
            os.remove(txt_path)

    full_text_file = os.path.join(TRANSCRIPT_DIR, f'{session_id}_full.txt')
    if os.path.exists(full_text_file):
        os.remove(full_text_file)

    session_dir = os.path.join(AUDIO_DIR, session_id)
    if os.path.exists(session_dir):
        shutil.rmtree(session_dir)

    conn.execute("DELETE FROM records WHERE session_id = ?", (session_id,))
    conn.execute("DELETE FROM sessions WHERE session_id = ?", (session_id,))
    conn.commit()
    conn.close()

    return jsonify({'success': True})
