"""
局域网 API 线程：与主网页服务同进程，共用同一份已加载模型。

监听 0.0.0.0 的独立端口，供同网段的 Mac、手机或脚本直接调用。
启动后把真实地址与密钥打印到日志，并写入 runtime 文件供启动器展示。
"""

import json
import os
import secrets
import socket
import threading

from flask import Flask
from werkzeug.serving import make_server

import config
from config import (
    API_MAX_UPLOAD_MB,
    API_PREFIX,
    LAN_API_CORS,
    LAN_API_HOST,
    LAN_API_KEY_FILE,
    LAN_API_PORT,
    LAN_API_RUNTIME_FILE,
)
from logger import app_logger

# 浏览器拒绝访问的端口，命中会 ERR_UNSAFE_PORT
_UNSAFE = {
    1, 7, 9, 11, 13, 15, 17, 19, 20, 21, 22, 23, 25, 37, 42, 43, 53, 69, 77, 79,
    87, 95, 101, 102, 103, 104, 109, 110, 111, 113, 115, 117, 119, 123, 135,
    137, 139, 143, 161, 179, 389, 427, 465, 512, 513, 514, 515, 526, 530, 531,
    532, 540, 548, 554, 556, 563, 587, 601, 636, 989, 990, 993, 995, 1719,
    1720, 1723, 2049, 3659, 4045, 4190, 5060, 5061, 6000, 6566, 6697, 10080,
}

_server = None
_info = None


def _browser_rejects(port):
    return port in _UNSAFE or 6665 <= port <= 6669


def _pick_port(start, tries=20):
    for offset in range(tries):
        port = start + offset
        if _browser_rejects(port):
            continue
        sock = socket.socket()
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((LAN_API_HOST, port))
            return port
        except OSError:
            continue
        finally:
            sock.close()
    return None


def ensure_key():
    env_key = os.getenv("ASR_API_KEY", "").strip()
    if env_key:
        return env_key
    if os.path.exists(LAN_API_KEY_FILE):
        key = open(LAN_API_KEY_FILE, encoding="utf-8").read().strip()
        if key:
            return key
    key = secrets.token_urlsafe(24)
    os.makedirs(os.path.dirname(LAN_API_KEY_FILE), exist_ok=True)
    with open(LAN_API_KEY_FILE, "w", encoding="utf-8") as f:
        f.write(key)
    return key


def lan_ip():
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.connect(("8.8.8.8", 80))
        ip = sock.getsockname()[0]
        sock.close()
        return ip
    except OSError:
        try:
            return socket.gethostbyname(socket.gethostname())
        except OSError:
            return "127.0.0.1"


def start_lan_api():
    """启动局域网 API 线程。重复调用只会返回已有实例。"""
    global _server, _info
    if _server is not None:
        return _info
    if not config.LAN_API_ENABLED:
        app_logger.info("局域网 API 已关闭（ASR_LAN_API=0）")
        return None

    port = _pick_port(LAN_API_PORT)
    if port is None:
        app_logger.error(f"局域网 API 无法找到可用端口（从 {LAN_API_PORT} 起）")
        return None

    key = ensure_key()

    # api 蓝图里的开关与密钥是模块级变量，这里注入独立线程的配置
    import routes.api as api_module

    api_module.API_ENABLED = True
    api_module.API_KEY = key
    api_module.API_ALLOW_CORS = LAN_API_CORS

    app = Flask("lan_api")
    app.config["MAX_CONTENT_LENGTH"] = API_MAX_UPLOAD_MB * 1024 * 1024
    app.register_blueprint(api_module.api_bp)

    _server = make_server(LAN_API_HOST, port, app, threaded=True)
    thread = threading.Thread(target=_server.serve_forever, name="lan-api", daemon=True)
    thread.start()

    ip = lan_ip()
    _info = {
        "url": f"http://{ip}:{port}{API_PREFIX}",
        "local_url": f"http://127.0.0.1:{port}{API_PREFIX}",
        "port": port,
        "key": key,
    }
    try:
        os.makedirs(os.path.dirname(LAN_API_RUNTIME_FILE), exist_ok=True)
        with open(LAN_API_RUNTIME_FILE, "w", encoding="utf-8") as f:
            json.dump(_info, f, ensure_ascii=False)
    except OSError as e:
        app_logger.warning(f"写入 API 运行信息失败: {e}")

    app_logger.info(f"局域网 API 已启动: {_info['url']}")
    return _info


def stop_lan_api():
    global _server
    if _server is not None:
        _server.shutdown()
        _server = None
