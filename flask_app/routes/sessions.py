from flask import Blueprint, request, jsonify
from datetime import datetime
import os
import shutil
from config import AUDIO_DIR, TRANSCRIPT_DIR
from database import get_db
from pydub import AudioSegment

sessions_bp = Blueprint('sessions', __name__)

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
    with open(full_text_file, 'w', encoding='utf-8') as f:
        f.write(f'会话: {session_id}\n')
        f.write(f'开始时间: {session["start_time"]}\n')
        f.write(f'结束时间: {end_time}\n')
        f.write(f'片段数: {session["segment_count"]}\n')
        f.write(f'\n完整转录内容:\n{full_text.strip()}\n')

    conn.close()
    return jsonify({'success': True, 'full_text': full_text})

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
        segs = records_by_session.get(s['session_id'], [])
        
        # 将后端时间直接美化并发送
        try:
            dt = datetime.strptime(s['start_time'], "%Y-%m-%d %H:%M:%S")
            fmt_time = f"{dt.month}月{dt.day}日 {dt.strftime('%H:%M:%S')}"
        except:
            fmt_time = s['start_time']

        result.append({
            'session_id': s['session_id'],
            'start_time': fmt_time,
            'end_time': s['end_time'] or '',
            'segment_count': len(segs),
            'full_text': s['full_text'] or '',
            'merged_audio': s['merged_audio'],
            'segments': segs
        })

    return jsonify(result)

@sessions_bp.route('/session/<session_id>', methods=['DELETE'])
def delete_session(session_id):
    conn = get_db()
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
