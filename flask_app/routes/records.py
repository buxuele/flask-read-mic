from flask import Blueprint, request, jsonify, send_file
import os
import traceback
from datetime import datetime
from io import BytesIO
from pydub import AudioSegment
from config import AUDIO_DIR, TRANSCRIPT_DIR
from database import get_db
from services import transcribe_audio

records_bp = Blueprint('records', __name__)

SESSION_STATE = {} # 句子级动态生命周期：{ session_id: {'audio': AudioSegment, 'start_index': int} }

@records_bp.route('/transcribe', methods=['POST'])
def transcribe():
    if 'audio' not in request.files:
        return jsonify({'error': '没有上传文件'}), 400

    file = request.files['audio']
    session_id = request.form.get('session_id')
    model_name = request.form.get('model', 'medium')
    language = request.form.get('language', 'zh')
    save_audio = request.form.get('save_audio', 'true') == 'true'

    if not file.filename:
        return jsonify({'error': '文件名为空'}), 400

    if not session_id:
        return jsonify({'error': '缺少会话ID'}), 400

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

    # 1. 将上传的文件读入内存
    audio_bytes = file.read()
    webm_io = BytesIO(audio_bytes)

    # 2. 实现以句子为维度的智能安全累加
    audio = AudioSegment.from_file(webm_io, format='webm')
    
    if session_id not in SESSION_STATE:
        SESSION_STATE[session_id] = {'audio': AudioSegment.empty(), 'start_index': segment_index}
        
    state = SESSION_STATE[session_id]
    state['audio'] += audio
    
    wav_io = BytesIO()
    state['audio'].export(wav_io, format='wav')
    wav_io.seek(0)

    # 3. 将连贯的累计前文大段去进行绝对安全的极精确推理
    text = transcribe_audio(wav_io, model_name, language)
    
    # 4. 判断这一句话是否说完封板：存在终止标点，且字数不为空，或者时长超过了极端情况15秒
    is_sealed = False
    if text and text[-1] in ['。', '！', '？', '.', '!', '?']:
        is_sealed = True
    elif len(state['audio']) > 15000:  # 防止无限堆积假死，最多15秒强行封板
        is_sealed = True
        
    replace_start_index = state['start_index']
    
    # 封板或者没封板，我们在本窗口内执行数据库游标擦除，但决不会伤到上一个窗口封板的死数据！
    if replace_start_index < segment_index:
        conn.execute("UPDATE records SET text = '' WHERE session_id = ? AND segment_index >= ? AND segment_index < ?", 
                     (session_id, replace_start_index, segment_index))
                     
    if is_sealed:
        del SESSION_STATE[session_id] # 封禁存档，下一秒直接重启全新的一段

    # 4. 如果需要保存音频文件，则写磁盘
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

    # 直接将当前最优的综合句子长段插入最新记录

    conn.execute(
        "INSERT INTO records (id, session_id, segment_index, timestamp, text, audio_file, model) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (timestamp, session_id, segment_index, now.strftime("%Y-%m-%d %H:%M:%S"), text, audio_file_ref, model_name)
    )
    
    # 因为存在覆盖机制，必须采取从 DB 获取最新拼接而不能盲目追加
    rows = conn.execute("SELECT text FROM records WHERE session_id = ? ORDER BY segment_index", (session_id,)).fetchall()
    full_text = " ".join([r['text'] for r in rows if r['text'].strip()])
    
    conn.execute(
        "UPDATE sessions SET segment_count = ?, full_text = ? WHERE session_id = ?",
        (segment_index, full_text, session_id)
    )
    conn.commit()
    conn.close()

    return jsonify({
        'text': text,
        'id': timestamp,
        'session_id': session_id,
        'segment_index': segment_index,
        'replace_start_index': replace_start_index
    })

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
