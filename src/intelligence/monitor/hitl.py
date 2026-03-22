"""
Human-in-the-Loop 审批流程。
approve -> 正式推送，reject -> 记录误报反馈。
"""
import logging

from intelligence.db import (
    approve_alert,
    get_db,
    reject_alert,
    save_false_positive,
)
from intelligence.monitor.confidence import refresh_false_positives
from intelligence.notify import push_all

logger = logging.getLogger("intelligence.monitor.hitl")


def approve_and_push(info_hash: str, user_id: str = "__system__"):
    """人工审批通过 -> 触发正式推送。"""
    approve_alert(info_hash, user_id)

    db = get_db()
    alert = db.alerts_log.find_one(
        {"info_hash": info_hash, "user_id": user_id}, {"_id": 0},
    )
    if alert:
        push_all(alert)
        logger.info(f"[HITL] 告警已审批并推送: {info_hash[:16]}...")


def reject_and_learn(info_hash: str, user_id: str = "__system__",
                     reason: str = "误报"):
    """人工拒绝告警 -> 记录误报反馈，优化后续匹配。"""
    reject_alert(info_hash, user_id, reason)

    db = get_db()
    alert = db.alerts_log.find_one(
        {"info_hash": info_hash, "user_id": user_id}, {"_id": 0},
    )
    if alert:
        for kw in alert.get("matched_keywords", []):
            save_false_positive(kw, info_hash, reason)
        logger.info(
            f"[HITL] 告警已拒绝，误报关键词已记录: "
            f"{alert.get('matched_keywords', [])}"
        )

    refresh_false_positives()
