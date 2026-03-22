"""飞书自定义机器人 Webhook 推送。"""
import logging

import httpx

from intelligence.config import NOTIFY_FEISHU_WEBHOOK

logger = logging.getLogger("intelligence.notify.feishu")
_TIMEOUT = 10


def push(title: str, body: str):
    if not NOTIFY_FEISHU_WEBHOOK:
        return
    payload = {
        "msg_type": "interactive",
        "card": {
            "header": {"title": {"tag": "plain_text", "content": title}},
            "elements": [
                {"tag": "div", "text": {"tag": "plain_text", "content": body}},
            ],
        },
    }
    try:
        resp = httpx.post(NOTIFY_FEISHU_WEBHOOK, json=payload, timeout=_TIMEOUT)
        resp.raise_for_status()
        logger.info(f"推送成功: {title}")
    except Exception as e:
        logger.warning(f"推送失败: {e}")


def push_review_card(torrent_name: str, keywords: str, info_hash: str,
                     confidence: str, conf_color: str):
    """推送待审批卡片（带置信度标识）。"""
    if not NOTIFY_FEISHU_WEBHOOK:
        return
    payload = {
        "msg_type": "interactive",
        "card": {
            "header": {
                "title": {
                    "tag": "plain_text",
                    "content": f"[待审批] DHT 告警 - 置信度: {confidence}",
                },
                "template": conf_color,
            },
            "elements": [
                {
                    "tag": "div",
                    "text": {
                        "tag": "lark_md",
                        "content": (
                            f"**种子:** {torrent_name}\n"
                            f"**命中关键词:** {keywords}\n"
                            f"**info_hash:** `{info_hash}`\n"
                            f"**置信度:** {confidence}\n\n"
                            f"请在 Web 控制台审批此告警。"
                        ),
                    },
                },
                {
                    "tag": "note",
                    "elements": [{
                        "tag": "plain_text",
                        "content": "HITL: 此告警置信度不足，需人工确认后才会正式推送。",
                    }],
                },
            ],
        },
    }
    try:
        resp = httpx.post(NOTIFY_FEISHU_WEBHOOK, json=payload, timeout=_TIMEOUT)
        resp.raise_for_status()
        logger.info(f"待审批推送: {info_hash[:16]}...")
    except Exception as e:
        logger.warning(f"待审批推送失败: {e}")
