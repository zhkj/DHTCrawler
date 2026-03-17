"""
告警外部推送 — 支持飞书 / 钉钉 / Telegram webhook
Monitor Agent 触发告警后通过回调调用此模块推送通知。
支持 Human-in-the-Loop：待审批告警发送特殊格式卡片。
"""
import logging
import httpx
from config import (
    NOTIFY_FEISHU_WEBHOOK, NOTIFY_DINGTALK_WEBHOOK, NOTIFY_TELEGRAM_TOKEN,
    NOTIFY_TELEGRAM_CHAT_ID,
)

logger = logging.getLogger("intelligence.notifier")

_TIMEOUT = 10

_CONFIDENCE_LABEL = {"high": "HIGH", "medium": "MEDIUM", "low": "LOW"}
_CONFIDENCE_COLOR = {"high": "red", "medium": "orange", "low": "grey"}


def _format_alert(alert: dict) -> tuple[str, str]:
    """将告警记录格式化为标题和正文。"""
    alert_type = "信号词告警" if alert.get("type") == "signal" else "自定义告警"
    torrent_name = alert.get("torrent_name", "未知")
    keywords = ", ".join(alert.get("matched_keywords", []))
    categories = alert.get("categories", [])
    cat_str = f" [{', '.join(categories)}]" if categories else ""
    info_hash = alert.get("info_hash", "")
    triggered = str(alert.get("triggered_at", ""))[:19]
    confidence = alert.get("confidence", "unknown")
    conf_label = _CONFIDENCE_LABEL.get(confidence, confidence)

    title = f"DHT 告警: {alert_type}{cat_str}"
    body = (
        f"种子: {torrent_name}\n"
        f"命中关键词: {keywords}\n"
        f"置信度: {conf_label}\n"
        f"info_hash: {info_hash}\n"
        f"时间: {triggered}"
    )
    return title, body


# ── 飞书 ────────────────────────────────────────────────────────────

def push_feishu(alert: dict):
    """推送到飞书自定义机器人 webhook。"""
    if not NOTIFY_FEISHU_WEBHOOK:
        return
    title, body = _format_alert(alert)
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
        logger.info(f"[Notify] 飞书推送成功: {title}")
    except Exception as e:
        logger.warning(f"[Notify] 飞书推送失败: {e}")


def push_pending_review(alert: dict):
    """
    推送待审批告警到飞书（带置信度标识和审批提示）。
    Human-in-the-Loop: 中低置信度告警需要人工确认。
    """
    if not NOTIFY_FEISHU_WEBHOOK:
        return

    confidence = alert.get("confidence", "low")
    conf_label = _CONFIDENCE_LABEL.get(confidence, confidence)
    conf_color = _CONFIDENCE_COLOR.get(confidence, "grey")
    torrent_name = alert.get("torrent_name", "未知")
    keywords = ", ".join(alert.get("matched_keywords", []))
    info_hash = alert.get("info_hash", "")

    payload = {
        "msg_type": "interactive",
        "card": {
            "header": {
                "title": {
                    "tag": "plain_text",
                    "content": f"[待审批] DHT 告警 - 置信度: {conf_label}",
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
                            f"**置信度:** {conf_label}\n\n"
                            f"请在 Web 控制台审批此告警。"
                        ),
                    },
                },
                {
                    "tag": "note",
                    "elements": [
                        {
                            "tag": "plain_text",
                            "content": "Human-in-the-Loop: 此告警置信度不足，需人工确认后才会正式推送。",
                        },
                    ],
                },
            ],
        },
    }
    try:
        resp = httpx.post(NOTIFY_FEISHU_WEBHOOK, json=payload, timeout=_TIMEOUT)
        resp.raise_for_status()
        logger.info(f"[Notify] 飞书待审批推送: {info_hash[:16]}... conf={conf_label}")
    except Exception as e:
        logger.warning(f"[Notify] 飞书待审批推送失败: {e}")


# ── 钉钉 ────────────────────────────────────────────────────────────

def push_dingtalk(alert: dict):
    """推送到钉钉自定义机器人 webhook。"""
    if not NOTIFY_DINGTALK_WEBHOOK:
        return
    title, body = _format_alert(alert)
    payload = {
        "msgtype": "markdown",
        "markdown": {
            "title": title,
            "text": f"### {title}\n\n{body}",
        },
    }
    try:
        resp = httpx.post(NOTIFY_DINGTALK_WEBHOOK, json=payload, timeout=_TIMEOUT)
        resp.raise_for_status()
        logger.info(f"[Notify] 钉钉推送成功: {title}")
    except Exception as e:
        logger.warning(f"[Notify] 钉钉推送失败: {e}")


# ── Telegram ────────────────────────────────────────────────────────

def push_telegram(alert: dict):
    """推送到 Telegram Bot。"""
    if not NOTIFY_TELEGRAM_TOKEN or not NOTIFY_TELEGRAM_CHAT_ID:
        return
    title, body = _format_alert(alert)
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
        logger.info(f"[Notify] Telegram 推送成功: {title}")
    except Exception as e:
        logger.warning(f"[Notify] Telegram 推送失败: {e}")


# ── 统一推送 ────────────────────────────────────────────────────────

def push_all(alert: dict):
    """向所有已配置的渠道推送告警。作为 Monitor Agent 的回调使用。"""
    push_feishu(alert)
    push_dingtalk(alert)
    push_telegram(alert)
