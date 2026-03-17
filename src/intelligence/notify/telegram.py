"""Telegram Bot API 推送。"""
import logging
import httpx
from intelligence.config import NOTIFY_TELEGRAM_TOKEN, NOTIFY_TELEGRAM_CHAT_ID

logger = logging.getLogger("intelligence.notify.telegram")
_TIMEOUT = 10


def push(title: str, body: str):
    if not NOTIFY_TELEGRAM_TOKEN or not NOTIFY_TELEGRAM_CHAT_ID:
        return
    text = f"*{title}*\n\n{body}"
    url = f"https://api.telegram.org/bot{NOTIFY_TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": NOTIFY_TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "Markdown",
    }
    try:
        resp = httpx.post(url, json=payload, timeout=_TIMEOUT)
        resp.raise_for_status()
        logger.info(f"推送成功: {title}")
    except Exception as e:
        logger.warning(f"推送失败: {e}")
