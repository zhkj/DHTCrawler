"""通知调度器 — 格式化告警 + 路由到各渠道。"""
import logging

from intelligence.notify import dingtalk, feishu, telegram

logger = logging.getLogger("intelligence.notify")

_CONFIDENCE_LABEL = {"high": "HIGH", "medium": "MEDIUM", "low": "LOW"}
_CONFIDENCE_COLOR = {"high": "red", "medium": "orange", "low": "grey"}


def _format_alert(alert: dict) -> tuple[str, str]:
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


def push_all(alert: dict):
    """向所有已配置的渠道推送告警。"""
    title, body = _format_alert(alert)
    feishu.push(title, body)
    dingtalk.push(title, body)
    telegram.push(title, body)


def push_pending_review(alert: dict):
    """推送待审批通知（仅飞书，带交互卡片）。"""
    confidence = alert.get("confidence", "low")
    conf_label = _CONFIDENCE_LABEL.get(confidence, confidence)
    conf_color = _CONFIDENCE_COLOR.get(confidence, "grey")

    feishu.push_review_card(
        torrent_name=alert.get("torrent_name", "未知"),
        keywords=", ".join(alert.get("matched_keywords", [])),
        info_hash=alert.get("info_hash", ""),
        confidence=conf_label,
        conf_color=conf_color,
    )
