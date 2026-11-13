from flask import Flask

import os

import config
from config import (
    API_ENABLED,
    API_KEY,
    MAX_CONTENT_LENGTH,
    SERVER_DEBUG,
    SERVER_HOST,
    SERVER_PORT,
)
from cleanup import cleanup_old_sessions
from database import init_db, close_db
from routes.main import main_bp
from routes.sessions import sessions_bp
from routes.records import records_bp
from routes.api import api_bp
from services import preload_in_background
from logger import app_logger


def create_app():
    app = Flask(__name__)
    app.config['MAX_CONTENT_LENGTH'] = MAX_CONTENT_LENGTH

    app_logger.info("正在初始化应用...")

    init_db()
    app_logger.info("数据库初始化完成")

    cleanup_old_sessions()

    app.register_blueprint(main_bp)
    app.register_blueprint(sessions_bp)
    app.register_blueprint(records_bp)

    if API_ENABLED:
        if not API_KEY:
            app_logger.error("API 已启用但未配置 API_KEY，所有请求将被拒绝")
        else:
            app.register_blueprint(api_bp)
            app_logger.info(f"局域网 API 已启用：{config.API_PREFIX}")

    # 启动即后台预热模型，让用户看到加载进度而不是首次录音时干等十几秒。
    # 测试与脚本化场景可设 ASR_PRELOAD=0 关闭，避免白占显存。
    if os.getenv('ASR_PRELOAD', '1') == '1':
        preload_in_background()
    else:
        app_logger.info("已跳过模型预热（ASR_PRELOAD=0）")

    app.teardown_appcontext(close_db)
    return app


app = create_app()

def _preflight():
    """启动前先探端口。run_all.py 已做好端口扫描，这一步只要兜住未走启动器的直跑场景。"""
    import socket

    sock = socket.socket()
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        sock.bind((SERVER_HOST, SERVER_PORT))
        return True
    except OSError as e:
        errno = getattr(e, "errno", None)
        winerror = getattr(e, "winerror", None)
        if errno in (13, 10013) or winerror == 10013:
            app_logger.error(f"端口 {SERVER_PORT} 落在 Windows TCP 排除范围（WinError 10013），请换端口")
            app_logger.error("查看：netsh interface ipv4 show excludedportrange protocol=tcp")
        elif errno == 10048 or winerror == 10048:
            app_logger.error(f"端口 {SERVER_PORT} 已被占用，请先关掉旧进程")
        else:
            app_logger.error(f"端口绑定失败：{e}")
        return False
    finally:
        sock.close()


if __name__ == '__main__':
    if not _preflight():
        raise SystemExit(1)

    from lan_server import start_lan_api

    start_lan_api()

    shown_host = '127.0.0.1' if SERVER_HOST == '0.0.0.0' else SERVER_HOST
    app_logger.info(f"启动 Flask 应用 - http://{shown_host}:{SERVER_PORT}")
    app.run(debug=SERVER_DEBUG, host=SERVER_HOST, port=SERVER_PORT, threaded=True)
