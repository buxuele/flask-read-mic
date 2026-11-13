"""
统一启动器：同时拉起识别服务与语音输入代理，任一退出则整体收尾。

进程模型：
    识别服务   subprocess，用 pythonw 隐藏控制台
    语音代理   subprocess，前台运行（需要托盘与日志）
    本脚本     负责等待就绪、优雅关闭、级联清理子进程

Windows 下 venv 的 python.exe 是包装器，会再 fork 一个真实解释器，
直接 terminate() 包装器不会传导到孙进程，会留下孤儿占用端口。
因此用 Job Object 把整棵进程树纳入同一个作业，退出时一次性回收。
"""

import ctypes
import json
import os
import signal
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from ctypes import wintypes

ROOT = os.path.realpath(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "src")
sys.path.insert(0, SRC)

from config import LAN_API_ENABLED, LAN_API_RUNTIME_FILE, SERVER_HOST, SERVER_PORT  # noqa: E402

HEALTH_URL = f"http://127.0.0.1:{SERVER_PORT}/model"
START_TIMEOUT = 40

# ---------------- 终端输出 ----------------
IS_TTY = sys.stdout.isatty()

if IS_TTY and os.name == "nt":
    try:
        _kernel32 = ctypes.windll.kernel32
        _handle = _kernel32.GetStdHandle(-11)
        _mode = ctypes.c_uint32()
        _kernel32.GetConsoleMode(_handle, ctypes.byref(_mode))
        _kernel32.SetConsoleMode(_handle, _mode.value | 0x0004)
    except Exception:
        IS_TTY = False

ACCENT = (252, 3, 119)
OK = (154, 219, 55)
DIM = (125, 125, 125)
BAD = (255, 96, 96)
RULE = "─" * 46


def _paint(text, rgb):
    if not IS_TTY:
        return text
    return f"\033[38;2;{rgb[0]};{rgb[1]};{rgb[2]}m{text}\033[0m"


def _title():
    print()
    print("  " + _paint("语音转录", ACCENT))
    print("  " + _paint(RULE, DIM))


def _row(label, value, color=None):
    text = f"  {label}    {value}"
    print(_paint(text, color) if color else text)


def _progress(label, text, color=DIM):
    line = f"  {label}    {text}"
    if IS_TTY:
        sys.stdout.write("\r" + line.ljust(72))
    else:
        print(line)
    sys.stdout.flush()


def _progress_done(label, text, color=OK):
    line = f"  {label}    {text}"
    if IS_TTY:
        sys.stdout.write("\r" + line.ljust(72) + "\n")
    else:
        print(line)
    sys.stdout.flush()


def _footer():
    print()
    print("  " + _paint(RULE, DIM))
    print("  " + _paint("双击 Ctrl 说话", OK) + _paint("    Ctrl+C 退出", DIM))
    print()
    sys.stdout.flush()


_children = []
_job = None

IS_WINDOWS = os.name == "nt"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


# ---------------- Windows Job Object：级联回收整棵进程树 ----------------
def _create_job():
    """把后续创建的子进程都挂进同一个作业，退出时连带孙进程一起回收"""
    if not IS_WINDOWS:
        return None
    try:
        kernel32 = ctypes.windll.kernel32

        class JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
            _fields_ = [
                ("PerProcessUserTimeLimit", ctypes.c_longlong),
                ("PerJobUserTimeLimit", ctypes.c_longlong),
                ("LimitFlags", wintypes.DWORD),
                ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t),
                ("ActiveProcessLimit", wintypes.DWORD),
                ("Affinity", ctypes.POINTER(ctypes.c_ulong)),
                ("PriorityClass", wintypes.DWORD),
                ("SchedulingClass", wintypes.DWORD),
            ]

        class IO_COUNTERS(ctypes.Structure):
            _fields_ = [(n, ctypes.c_ulonglong) for n in (
                "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
                "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]

        class JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
            _fields_ = [
                ("BasicLimitInformation", JOBOBJECT_BASIC_LIMIT_INFORMATION),
                ("IoInfo", IO_COUNTERS),
                ("ProcessMemoryLimit", ctypes.c_size_t),
                ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryUsed", ctypes.c_size_t),
                ("PeakJobMemoryUsed", ctypes.c_size_t),
            ]

        handle = kernel32.CreateJobObjectW(None, None)
        if not handle:
            return None

        info = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
        info.BasicLimitInformation.LimitFlags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        kernel32.SetInformationJobObject(
            handle, 9, ctypes.byref(info), ctypes.sizeof(info)
        )
        return handle
    except Exception:
        return None


def _assign_to_job(proc):
    if not IS_WINDOWS or _job is None:
        return
    try:
        ctypes.windll.kernel32.AssignProcessToJobObject(_job, proc._handle)
    except Exception:
        pass


# ---------------- 健康检查（端口经 _pick_port 后会变，取 ACTIVE_PORT） ----------------
ACTIVE_PORT = SERVER_PORT


def _health_ok(timeout=1):
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{ACTIVE_PORT}/model", timeout=timeout) as resp:
            return resp.status == 200
    except (urllib.error.URLError, OSError):
        return False


def _model_status():
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{ACTIVE_PORT}/model/status", timeout=2) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, ValueError):
        return None


def _show_lan_api(timeout=10):
    """读取独立 API 线程写下的运行信息，打印真实地址与密钥"""
    if not LAN_API_ENABLED:
        return
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with open(LAN_API_RUNTIME_FILE, encoding="utf-8") as f:
                info = json.load(f)
            _row("内网", info["url"])
            _row("密钥", info["key"], DIM)
            return
        except (OSError, ValueError):
            time.sleep(0.3)
    _row("内网", "未就绪，查看 src/logs/app_*.log", BAD)


_PHASES = {
    "loading": "正在加载权重",
    "warming": "正在预热 GPU",
}


def wait_model_ready(timeout=120):
    """显示模型加载进度，直到 ready 或出错"""
    deadline = time.time() + timeout
    shown = None
    while time.time() < deadline:
        info = _model_status()
        if not info:
            time.sleep(0.3)
            continue
        state = info.get("status")
        if state == "ready":
            _progress_done("模型", "就绪")
            return True
        if state == "error":
            _progress_done("模型", "加载失败", BAD)
            _row("原因", info.get("error") or "未知", BAD)
            _row("日志", "src/logs/transcribe_*.log", DIM)
            return False
        phase = _PHASES.get(state)
        if phase and phase != shown:
            shown = phase
            _progress("模型", phase + "...")
        time.sleep(0.4)
    _progress_done("模型", "加载超时", BAD)
    return False


def _progress_worker():
    if wait_model_ready():
        _footer()


def _port_error_kind(e):
    """Windows 上 e.errno 是 13 (EACCES) / 10048 (EADDRINUSE)，winegine 的 winerror 才是 10013"""
    errno = getattr(e, "errno", None)
    winerror = getattr(e, "winerror", None)
    if errno in (13, 98, 10013) or winerror in (13, 10013):
        return "excluded"
    if errno in (10048, 98) or winerror == 10048:
        return "inuse"
    return "other"


# Chromium 拒绝访问的端口，命中会直接 ERR_UNSAFE_PORT，网页端等于打不开
CHROME_UNSAFE_PORTS = {
    1, 7, 9, 11, 13, 15, 17, 19, 20, 21, 22, 23, 25, 37, 42, 43, 53, 69, 77, 79,
    87, 95, 101, 102, 103, 104, 109, 110, 111, 113, 115, 117, 119, 123, 135,
    137, 139, 143, 161, 179, 389, 427, 465, 512, 513, 514, 515, 526, 530, 531,
    532, 540, 548, 554, 556, 563, 587, 601, 636, 989, 990, 993, 995, 1719,
    1720, 1723, 2049, 3659, 4045, 4190, 5060, 5061, 6000, 6566, 6697, 10080,
}


def _browser_rejects(port):
    return port in CHROME_UNSAFE_PORTS or 6665 <= port <= 6669


def _pick_port(start, tries=40):
    """从 start 起逐个 +1 试绑定，返回第一个可用的端口。

    同时避开 Windows 排除端口与 Chromium 不安全端口，否则要么服务起不来，
    要么服务起来了但浏览器拒绝访问。
    环境变量 ASR_SERVER_PORT 已指定（复用场景）时直接采用，不再扫描。
    """
    import socket

    forced = os.getenv("ASR_SERVER_PORT")
    if forced:
        return int(forced), True

    for offset in range(tries):
        port = start + offset
        if _browser_rejects(port):
            print(f"[i] 端口 {port} 被浏览器列为不安全端口，自动跳过")
            continue
        sock = socket.socket()
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((SERVER_HOST, port))
            return port, False
        except OSError as e:
            kind = _port_error_kind(e)
            if kind == "excluded":
                print(f"[i] 端口 {port} 落在 Windows TCP 排除范围，自动尝试下一个")
            elif kind == "inuse":
                print(f"[i] 端口 {port} 已被占用，自动尝试下一个")
            if offset == tries - 1:
                print(f"[x] 从 {start} 起连续 {tries} 个端口都不行，请手动指定 ASR_SERVER_PORT")
                return None, False
        finally:
            sock.close()
    return None, False


def _spawn(cmd, cwd, hide=False):
    exe = sys.executable
    if hide and IS_WINDOWS:
        pythonw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
        if os.path.exists(pythonw):
            exe = pythonw
    proc = subprocess.Popen(
        cmd,
        cwd=cwd,
        creationflags=NO_WINDOW if hide else 0,
    )
    _assign_to_job(proc)
    _children.append(proc)
    return proc


def start_server():
    return _spawn([sys.executable, os.path.join(SRC, "app.py")], cwd=SRC, hide=True)


def start_agent():
    return _spawn([sys.executable, os.path.join(SRC, "desktop_agent.py")], cwd=SRC)


def shutdown():
    print("\n" + _paint("  正在关闭...", DIM))
    for proc in _children:
        if proc.poll() is not None:
            continue
        try:
            proc.terminate()
        except Exception:
            pass

    deadline = time.time() + 5
    for proc in _children:
        while proc.poll() is None and time.time() < deadline:
            time.sleep(0.1)
        if proc.poll() is None:
            try:
                proc.kill()
            except Exception:
                pass

    # 关闭 Job 会连带终止仍在运行的孙进程（uv 包装器派生的真实解释器）
    global _job
    if _job:
        try:
            ctypes.windll.kernel32.CloseHandle(_job)
        except Exception:
            pass
        _job = None

    print(_paint("  已退出", DIM))


def main():
    global _job, ACTIVE_PORT

    _job = _create_job()
    _title()

    if _health_ok():
        _row("服务", f"http://127.0.0.1:{ACTIVE_PORT}")
        _row("状态", "复用已在运行的实例", DIM)
        _show_lan_api()
    else:
        port, _ = _pick_port(SERVER_PORT)
        if port is None:
            shutdown()
            return 1

        ACTIVE_PORT = port
        # 子进程从这个环境变量拿真实端口，config / desktop_agent / API 全同步
        os.environ["ASR_SERVER_PORT"] = str(port)
        _row("服务", f"http://127.0.0.1:{port}")

        started = time.time()
        try:
            os.remove(LAN_API_RUNTIME_FILE)
        except OSError:
            pass
        start_server()

        deadline = started + START_TIMEOUT
        while time.time() < deadline and not _health_ok():
            time.sleep(0.3)
        if not _health_ok():
            _row("服务", f"启动失败，{START_TIMEOUT} 秒内未就绪", BAD)
            _row("日志", "src/logs/app_*.log", DIM)
            shutdown()
            return 1

        _show_lan_api()

    start_agent()

    # 进度与操作提示放后台线程，避免和主流程输出交错
    threading.Thread(target=_progress_worker, name="model-progress", daemon=True).start()

    try:
        for proc in _children:
            proc.wait()
    except KeyboardInterrupt:
        pass
    finally:
        shutdown()
    return 0


if __name__ == "__main__":
    try:
        signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    except (AttributeError, ValueError):
        pass
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        shutdown()
        sys.exit(0)