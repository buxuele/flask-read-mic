from flask import Blueprint, render_template, send_file, jsonify
import os
from config import AUDIO_DIR

main_bp = Blueprint('main', __name__)

@main_bp.route('/')
def index():
    return render_template('index.html')

@main_bp.route('/audio/<path:filename>')
def get_audio(filename):
    audio_path = os.path.join(AUDIO_DIR, filename)
    if os.path.exists(audio_path):
        return send_file(audio_path, mimetype='audio/wav')
    return jsonify({'error': '音频文件不存在'}), 404
