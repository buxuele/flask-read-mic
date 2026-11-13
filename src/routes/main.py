from flask import Blueprint, render_template, send_file, jsonify, abort
import os

from config import ASR_MODEL_ID, AUDIO_DIR
from services import model_status

main_bp = Blueprint('main', __name__)


@main_bp.route('/')
def index():
    return render_template('index.html')


@main_bp.route('/model')
def get_model():
    return jsonify({'model': ASR_MODEL_ID})


@main_bp.route('/model/status')
def get_model_status():
    """前端轮询模型加载进度：idle / loading / warming / ready / error"""
    return jsonify(model_status())


@main_bp.route('/audio/<path:filename>')
def get_audio(filename):
    """<path:> 会放行 ../，必须解析后校验仍在 AUDIO_DIR 内，否则可读取 .env 等任意文件"""
    audio_path = os.path.realpath(os.path.join(AUDIO_DIR, filename))
    root = os.path.realpath(AUDIO_DIR)
    if os.path.commonpath([audio_path, root]) != root:
        abort(403)
    if not os.path.isfile(audio_path):
        abort(404)
    return send_file(audio_path, mimetype='audio/wav')
