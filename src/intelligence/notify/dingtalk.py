"""钉钉自定义机器人 Webhook 推送。"""
import logging
import httpx
from intelligence.config import NOTIFY_DINGTALK_WEBHOOK

logger = logging.getLogger("intelligence.notify.dingtalk")
_TIMEOUT = 10


def push(title: str, body: str):
    if not NOTIFY_DINGTALK_WEBHOOK:
        return
    payload = {
        "msgtype": "markdown",
        "markdown": {"title": title, "text": f"### {title}\n\n{body}"},
    }
    try:
        resp = httpx.post(NOTIFY_DINGTALK_WEBHOOK, json=payload, timeout=_TIMEOUT)
        resp.raise_for_status()
        logger.info(f"推送成功: {title}")
    except Exception as e:
        logger.warning(f"推送失败: {e}")
