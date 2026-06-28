import os
import sys
import time
import threading
import io
import pystray
from PIL import Image, ImageDraw
import keyboard
import sounddevice as sd
import soundfile as sf
import requests
import numpy as np

# Configurations
HOTKEY = 'ctrl'
API_URL = 'http://127.0.0.1:5000/transcribe'
SAMPLE_RATE = 16000
CHANNELS = 1

is_recording = False
is_running = True
audio_data = []

def create_image(color):
    """Create a minimalist circular icon to represent status"""
    image = Image.new('RGBA', (64, 64), (255, 255, 255, 0))
    dc = ImageDraw.Draw(image)
    dc.ellipse((16, 16, 48, 48), fill=color)
    return image

icon = pystray.Icon("flask-read-mic-agent", create_image('gray'), "智能语音助手 (常驻)")

def audio_callback(indata, frames, time_info, status):
    if is_recording:
        audio_data.append(indata.copy())

def start_recording():
    global is_recording, audio_data
    is_recording = True
    audio_data = []
    icon.icon = create_image('#d9234a')
    print("[Agent] 识别到热键，开始录音...")

def stop_recording():
    global is_recording, audio_data
    is_recording = False
    icon.icon = create_image('gray')
    print("[Agent] 热键释放，结束录音，准备上传...")
    
    if len(audio_data) > 0:
        data = np.concatenate(audio_data, axis=0)
        wav_io = io.BytesIO()
        # subtype 'PCM_16' ensures it matches standard wave behavior for whisper
        sf.write(wav_io, data, SAMPLE_RATE, format='WAV', subtype='PCM_16')
        wav_io.seek(0)
        
        # Use a distinct session name pattern for the desktop agent
        session_id = f"desk_{int(time.time())}"
        
        def upload():
            try:
                files = {'audio': (f'{session_id}.wav', wav_io, 'audio/wav')}
                payload = {
                    'session_id': session_id,
                    'model': 'medium',
                    'language': 'zh',
                    'mode': 'command', # triggers commander.py inside the backend
                    'save_audio': 'false'
                }
                print(f"[Agent] 正在发送 {len(data)} 个音频采样...")
                res = requests.post(API_URL, files=files, data=payload)
                if res.status_code == 200:
                    print("[Agent] 上传完成且后端执行完毕!")
                else:
                    print(f"[Agent] 上传异常，状态码: {res.status_code}")
            except Exception as e:
                print("[Agent] 服务器请求失败:", e)
        
        # Non-blocking upload so that the GUI thread is clean
        threading.Thread(target=upload, daemon=True).start()

    audio_data = []

def key_monitor_loop():
    global is_recording, is_running
    # Begin endless silent recording stream, we grab data from it on demand
    stream = sd.InputStream(samplerate=SAMPLE_RATE, channels=CHANNELS, callback=audio_callback)
    stream.start()
    
    try:
        while is_running:
            time.sleep(0.05)
            # Reliable status check bypassing any OS auto-repeat caveats
            if keyboard.is_pressed(HOTKEY):
                if not is_recording:
                    start_recording()
            else:
                if is_recording:
                    stop_recording()
    except Exception as e:
        print("[Agent] Key monitor error:", e)
    finally:
        stream.stop()
        stream.close()

def setup(icon):
    icon.visible = True
    threading.Thread(target=key_monitor_loop, daemon=True).start()

def quit_app(icon, item):
    global is_running
    is_running = False
    icon.stop()

icon.menu = pystray.Menu(pystray.MenuItem('安全退出', quit_app))

if __name__ == "__main__":
    print("[Agent] 后台常驻程序启动成功，现在请随时任意位置按住 Ctrl 键不松开说话...")
    icon.run(setup)
