import json
import os
import re
import subprocess
import sys
import time
import webbrowser

from dotenv import load_dotenv

from config import ROOT_DIR
from llm_client import chat
from logger import app_logger

load_dotenv()

# 文本注入
PASTE_SETTLE_SECONDS = 0.15
AUTO_ENTER_AFTER_TYPE = False

FAIL_COOLDOWN = 300
_failed_until = 0.0


def parse_with_llm(text):
    global _failed_until

    if time.time() < _failed_until:
        return {"action": "none"}

    prompt = (
        "你是一个智能语音指令解析器。用户的语音识别结果可能包含严重错别字（例如由于发音相似，'一下上海听证'实为'查一下上海天气'，'既不会'实为'记笔记'）。\n"
        "请猜测用户的真实上下文意图并返回 JSON。可选 action 如下：\n"
        "- 'search': 搜索指令（如查天气、搜资料）。需提供 'param' 字段（搜索关键词，必须是你纠错后的纯净版，如'上海 天气'）。\n"
        "- 'note': 记录指令（如记笔记、备忘录）。需提供 'param' 字段（笔记的准确正文）。\n"
        "- 'type_text': 文本输入/打字接管指令（如：'输入你好'、'帮我回一下老板我晚点到'）。需提供 'param' 字段（提取并提炼出的纯文字正文，没有任何前缀，例如'老板我晚点到'）。\n"
        "- 'none': 这绝对不是任何指令，或者是一段毫无逻辑的杂音。\n"
        "回复务必只包含标准的 JSON 字符串，不要有其他任何解释。例如：{\"action\": \"search\", \"param\": \"上海天气\"}\n\n"
        f"用户原始语音错漏文本：{text}"
    )

    content = chat(prompt)
    if content is None:
        _failed_until = time.time() + FAIL_COOLDOWN
        return {"action": "none"}

    try:
        match = re.search(r'(\{.*\})', content, re.DOTALL)
        result = json.loads(match.group(1) if match else content)
        app_logger.info(f"指令解析成功: {result}")
        return result
    except Exception as e:
        app_logger.error(f"指令解析失败: {e}")
        return {"action": "none"}

def execute_command(text):
    """解析并执行指令。返回 (是否已消费该文本, 人类可读结果)。"""
    text = text.strip()
    if not text:
        return True, None

    intent = parse_with_llm(text)
    action = intent.get('action')
    param = intent.get('param', '')

    if action == 'search' and param:
        webbrowser.open(f"https://www.google.com/search?q={param}")
        app_logger.info(f"执行搜索指令: {param}")
        return True, f"已打开浏览器搜索: {param}"

    if action == 'note' and param:
        note_path = os.path.join(ROOT_DIR, "QuickNotes.txt")
        with open(note_path, 'a', encoding='utf-8') as f:
            f.write(f"- {param}\n")
        if os.name == 'nt':
            os.startfile(note_path)
        elif sys.platform == 'darwin':
            subprocess.call(['open', note_path])
        app_logger.info(f"执行笔记指令: {param}")
        return True, "内容已写入 QuickNotes.txt 并打开"

    if action == 'type_text' and param:
        inject_text(param)
        return True, f"已注入文本: {param}"

    return False, None


def inject_text(text):
    import pyautogui
    import pyperclip

    pyautogui.FAILSAFE = False
    pyperclip.copy(text)
    time.sleep(PASTE_SETTLE_SECONDS)
    pyautogui.hotkey('ctrl', 'v')
    if AUTO_ENTER_AFTER_TYPE:
        time.sleep(PASTE_SETTLE_SECONDS)
        pyautogui.press('enter')
    app_logger.info(f"注入文本: {text}")
