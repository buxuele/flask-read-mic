import os
import re
import sys
import json
import webbrowser
import subprocess
from openai import OpenAI
from dotenv import load_dotenv
from logger import app_logger

load_dotenv()

def parse_with_llm(text):
    try:
        api_key = os.getenv('OPENROUTER_API_KEY')
        if not api_key:
            app_logger.error("OPENROUTER_API_KEY 未配置")
            return {"action": "none"}
            
        client = OpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=api_key,
        )
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
        
        response = client.chat.completions.create(
            model="nvidia/nemotron-3-super-120b-a12b:free", 
            messages=[{"role": "user", "content": prompt}],
        )
        
        content = response.choices[0].message.content.strip()
        
        match = re.search(r'(\{.*\})', content, re.DOTALL)
        if match:
            result = json.loads(match.group(1))
            app_logger.info(f"指令解析成功: {result}")
            return result
        return json.loads(content)
    except Exception as e:
        app_logger.error(f"指令解析失败: {e}")
        return {"action": "none"}

def execute_command(text):
    text = text.strip()
    if not text:
        return None

    intent = parse_with_llm(text)
    action = intent.get('action')
    param = intent.get('param', '')

    if action == 'search' and param:
        url = f"https://www.google.com/search?q={param}"
        webbrowser.open(url)
        app_logger.info(f"执行搜索指令: {param}")
        return f"[已执行指令] 打开浏览器搜索: {param}"

    elif action == 'note' and param:
        note_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "QuickNotes.txt")
        with open(note_path, 'a', encoding='utf-8') as f:
            f.write(f"- {param}\n")
        
        if os.name == 'nt':
            os.startfile(note_path)
        elif sys.platform == 'darwin':
            subprocess.call(['open', note_path])
        
        app_logger.info(f"执行笔记指令: {param}")
        return f"[已执行指令] 内容已写入 QuickNotes.txt 并打开。"

    elif action == 'type_text' and param:
        try:
            import pyperclip
            import pyautogui
            import time
            pyperclip.copy(param)
            time.sleep(0.1) # Small delay to ensure clipboard is populated
            pyautogui.hotkey('ctrl', 'v')
            app_logger.info(f"执行注入指令: {param}")
            return f"[已执行指令] 自动注入文本: {param}"
        except Exception as e:
            app_logger.error(f"注入文本失败: {e}")
            return f"[注入失败] {e}"

    return None
