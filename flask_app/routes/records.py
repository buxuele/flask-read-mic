from flask import Blueprint, request, jsonify, send_file
import os
import time
from datetime import datetime
from io import BytesIO
from pydub import AudioSegment
from config import AUDIO_DIR, TRANSCRIPT_DIR
from database import get_db
from services import transcribe_audio
from logger import transcribe_logger
from cleanup import cleanup_session_state

records_bp = Blueprint('records', __name__)

SESSION_STATE = {}

@records_bp.route('/transcribe', methods=['POST'])
def transcribe():
    try:
        cleanup_session_state(SESSION_STATE, max_age_seconds=3600)
        
        if 'audio' not in request.files:
            return jsonify({'error': '没有上传文件'}), 400

        file = request.files['audio']
        session_id = request.form.get('session_id')
        model_name = request.form.get('model', 'medium')
        language = request.form.get('language', 'zh')
        save_audio = request.form.get('save_audio', 'true') == 'true'
        mode = request.form.get('mode', 'dictate')

        if not file.filename:
            return jsonify({'error': '文件名为空'}), 400

        if not session_id:
            return jsonify({'error': '缺少会话ID'}), 400

        transcribe_logger.info(f"开始转录 - 会话: {session_id}, 模型: {model_name}, 语言: {language}")

        conn = get_db()
        session = conn.execute("SELECT * FROM sessions WHERE session_id = ?", (session_id,)).fetchone()

        if not session:
            conn.close()
            return jsonify({'error': '会话不存在'}), 400

        segment_index = session['segment_count'] + 1
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S_%f')[:-3]
        now = datetime.now()

        session_dir = os.path.join(AUDIO_DIR, session_id)
        os.makedirs(session_dir, exist_ok=True)

        webm_filename = f'segment_{segment_index:03d}.webm'
        wav_filename = f'segment_{segment_index:03d}.wav'
        txt_filename = f'{session_id}_segment_{segment_index:03d}.txt'

        webm_path = os.path.join(session_dir, webm_filename)
        wav_path = os.path.join(session_dir, wav_filename)
        txt_path = os.path.join(TRANSCRIPT_DIR, txt_filename)

        audio_bytes = file.read()
        webm_io = BytesIO(audio_bytes)

        audio = AudioSegment.from_file(webm_io, format='webm')
        
        if session_id not in SESSION_STATE:
            SESSION_STATE[session_id] = {
                'audio': AudioSegment.empty(), 
                'start_index': segment_index, 
                'last_text': '',
                'last_update': time.time()
            }
            
        state = SESSION_STATE[session_id]
        state['audio'] += audio
        state['last_update'] = time.time()
        
        wav_io = BytesIO()
        state['audio'].export(wav_io, format='wav')
        wav_io.seek(0)

        text = transcribe_audio(wav_io, model_name, language)
        
        is_sealed = False
        last_text = state.get('last_text', '')
        
        if text and text[-1] in ['。', '！', '？', '.', '!', '?']:
            is_sealed = True
        elif mode == 'command' and text and text == last_text:
            is_sealed = True
        elif len(state['audio']) > 15000:
            is_sealed = True
            
        state['last_text'] = text
            
        replace_start_index = state['start_index']
        
        if replace_start_index < segment_index:
            conn.execute("UPDATE records SET text = '' WHERE session_id = ? AND segment_index >= ? AND segment_index < ?", 
                        (session_id, replace_start_index, segment_index))
                        
        if is_sealed:
            del SESSION_STATE[session_id]
            
            if mode == 'command' and text.strip():
                from commander import execute_command
                cmd_result = execute_command(text)
                if cmd_result:
                    text = f"收到指令：{text}\n{cmd_result}"

        if save_audio:
            with open(wav_path, 'wb') as f:
                f.write(wav_io.getvalue())

        with open(txt_path, 'w', encoding='utf-8') as f:
            f.write(f'会话: {session_id}\n')
            f.write(f'片段: {segment_index}\n')
            f.write(f'时间: {now.strftime("%Y-%m-%d %H:%M:%S")}\n')
            f.write(f'音频文件: {wav_filename if save_audio else "未保存"}\n')
            f.write(f'转录内容:\n{text}\n')

        audio_file_ref = f'{session_id}/{wav_filename}' if save_audio else None

        conn.execute(
            "INSERT INTO records (id, session_id, segment_index, timestamp, text, audio_file, model) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (timestamp, session_id, segment_index, now.strftime("%Y-%m-%d %H:%M:%S"), text, audio_file_ref, model_name)
        )
        
        rows = conn.execute("SELECT text FROM records WHERE session_id = ? ORDER BY segment_index", (session_id,)).fetchall()
        full_text = " ".join([r['text'] for r in rows if r['text'].strip()])
        
        conn.execute(
            "UPDATE sessions SET segment_count = ?, full_text = ? WHERE session_id = ?",
            (segment_index, full_text, session_id)
        )
        conn.commit()
        conn.close()

        transcribe_logger.info(f"转录完成 - 会话: {session_id}, 片段: {segment_index}")
        
        return jsonify({
            'text': text,
            'id': timestamp,
            'session_id': session_id,
            'segment_index': segment_index,
            'replace_start_index': replace_start_index
        })
        
    except Exception as e:
        transcribe_logger.error(f"转录失败: {e}")
        return jsonify({'error': f'转录失败: {str(e)}'}), 500

@records_bp.route('/record/<record_id>', methods=['GET'])
def get_record(record_id):
    conn = get_db()
    record = conn.execute("SELECT * FROM records WHERE id = ?", (record_id,)).fetchone()
    conn.close()
    if record:
        return jsonify(dict(record))
    return jsonify({'error': '记录不存在'}), 404

@records_bp.route('/record/<record_id>', methods=['PUT'])
def update_record(record_id):
    data = request.json
    conn = get_db()
    record = conn.execute("SELECT * FROM records WHERE id = ?", (record_id,)).fetchone()

    if not record:
        conn.close()
        return jsonify({'error': '记录不存在'}), 404

    new_text = data.get('text', record['text'])
    conn.execute("UPDATE records SET text = ? WHERE id = ?", (new_text, record_id))
    conn.commit()

    txt_filename = f"{record['session_id']}_segment_{record['segment_index']:03d}.txt"
    txt_path = os.path.join(TRANSCRIPT_DIR, txt_filename)
    with open(txt_path, 'w', encoding='utf-8') as f:
        f.write(f'会话: {record["session_id"]}\n')
        f.write(f'片段: {record["segment_index"]}\n')
        f.write(f'时间: {record["timestamp"]}\n')
        f.write(f'音频文件: {record["audio_file"] or "未保存"}\n')
        f.write(f'转录内容:\n{new_text}\n')

    conn.close()
    return jsonify({'success': True})

@records_bp.route('/record/<record_id>', methods=['DELETE'])
def delete_record(record_id):
    conn = get_db()
    record = conn.execute("SELECT * FROM records WHERE id = ?", (record_id,)).fetchone()

    if not record:
        conn.close()
        return jsonify({'error': '记录不存在'}), 404

    conn.execute("DELETE FROM records WHERE id = ?", (record_id,))
    conn.commit()
    conn.close()

    txt_filename = f"{record['session_id']}_segment_{record['segment_index']:03d}.txt"
    txt_path = os.path.join(TRANSCRIPT_DIR, txt_filename)
    if os.path.exists(txt_path):
        os.remove(txt_path)

    if record['audio_file']:
        audio_path = os.path.join(AUDIO_DIR, record['audio_file'])
        if os.path.exists(audio_path):
            os.remove(audio_path)

    return jsonify({'success': True})

@records_bp.route('/export', methods=['POST'])
def export_records():
    data = request.json
    session_ids = data.get('session_ids', [])

    conn = get_db()
    if session_ids:
        placeholders = ','.join('?' * len(session_ids))
        sessions = conn.execute(f"SELECT * FROM sessions WHERE session_id IN ({placeholders})", session_ids).fetchall()
    else:
        sessions = conn.execute("SELECT * FROM sessions ORDER BY start_time").fetchall()

    content_parts = []
    for s in sessions:
        records = conn.execute(
            "SELECT * FROM records WHERE session_id = ? ORDER BY segment_index",
            (s['session_id'],)
        ).fetchall()

        content_parts.append(f"会话: {s['session_id']}")
        content_parts.append(f"开始时间: {s['start_time']}")
        content_parts.append(f"结束时间: {s['end_time'] or '进行中'}")
        content_parts.append(f"片段数: {len(records)}")
        content_parts.append("")
        content_parts.append("完整内容:")
        content_parts.append((s['full_text'] or '').strip())
        content_parts.append("")
        content_parts.append("=" * 60)
        content_parts.append("")

    conn.close()

    content = '\n'.join(content_parts)
    buffer = BytesIO()
    buffer.write(content.encode('utf-8'))
    buffer.seek(0)

    return send_file(
        buffer,
        mimetype='text/plain',
        as_attachment=True,
        download_name=f'transcripts_{datetime.now().strftime("%Y%m%d_%H%M%S")}.txt'
    )
