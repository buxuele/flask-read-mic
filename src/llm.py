import os
import time

from dotenv import load_dotenv

from llm_client import chat
from logger import app_logger

load_dotenv()

LLM_TIMEOUT = 8
FAIL_COOLDOWN = 300

PROMPT = (
    "你是一个中文语音转录稿校对器。输入是语音识别后的连续文本，可能缺少标点、"
    "断句混乱、有同音错别字。请完成三件事：\n"
    "1. 补全标点（逗号、句号、问号、感叹号），让长句断成自然的短句；\n"
    "2. 修正明显的同音错别字，但保留原意，不要改写或扩写内容；\n"
    "3. 去掉语气助词和口头禅（如“呃”“那个”“就是说”）。\n"
    "只输出校对后的纯文本，不要任何解释、前后缀或 Markdown 标记。\n\n"
    "原始文本：{text}"
)

_failed_until = 0.0


def process_text(text):
    global _failed_until

    text = text.strip()
    if not text:
        return text

    if time.time() < _failed_until:
        return text

    result = chat(PROMPT.format(text=text))
    if result is None:
        _failed_until = time.time() + FAIL_COOLDOWN
        return text
    return result
