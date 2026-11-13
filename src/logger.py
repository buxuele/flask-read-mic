import logging
import os
from logging.handlers import RotatingFileHandler
from datetime import datetime

LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'logs')
os.makedirs(LOG_DIR, exist_ok=True)

_configured = set()


def setup_logger(name):
    if name in _configured:
        return logging.getLogger(name)

    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)
    logger.propagate = False

    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )

    file_handler = RotatingFileHandler(
        os.path.join(LOG_DIR, f'{name}_{datetime.now():%Y%m%d}.log'),
        maxBytes=10 * 1024 * 1024,
        backupCount=5,
        encoding='utf-8'
    )
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    # pythonw.exe 没有控制台，挂上 StreamHandler 会让 logging 直接抛异常，
    # 进而把整个进程带崩。检测不到可用控制台就只写文件。
    if _has_console():
        stream_handler = logging.StreamHandler()
        stream_handler.setFormatter(formatter)
        logger.addHandler(stream_handler)

    _configured.add(name)
    return logger


def _has_console():
    if os.name != 'nt':
        return True
    try:
        import ctypes

        return bool(ctypes.windll.kernel32.GetConsoleWindow())
    except Exception:
        return False


app_logger = setup_logger('app')
transcribe_logger = setup_logger('transcribe')
db_logger = setup_logger('database')
