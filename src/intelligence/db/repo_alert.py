"""告警规则 & 告警日志 Repository。"""
from intelligence.db.client import get_db

# ── 告警规则 ──────────────────────────────────────────────────────

def save_alert_rule(user_id: str, keywords: list[str]):
    db = get_db()
    db.alerts.update_one(
        {"user_id": user_id},
        {"$set": {"keywords": keywords}},
        upsert=True,
    )


def get_alert_rules(user_id: str) -> list[str]:
    db = get_db()
    doc = db.alerts.find_one({"user_id": user_id})
    return doc["keywords"] if doc else []


def get_all_alert_rules() -> list[dict]:
    db = get_db()
    return list(db.alerts.find({}, {"_id": 0}))


# ── 告警日志 ──────────────────────────────────────────────────────

def save_alert_log(log: dict):
    db = get_db()
    db.alerts_log.insert_one(log)


def get_alert_logs(user_id: str = None, limit: int = 20,
                   unread_only: bool = False) -> list[dict]:
    db = get_db()
    query = {}
    if user_id:
        query["user_id"] = user_id
    if unread_only:
        query["read"] = False
    return list(
        db.alerts_log.find(query, {"_id": 0})
        .sort("triggered_at", -1)
        .limit(limit)
    )


def mark_alerts_read(user_id: str):
    db = get_db()
    db.alerts_log.update_many(
        {"user_id": user_id, "read": False},
        {"$set": {"read": True}},
    )


# ── Human-in-the-Loop ────────────────────────────────────────────

def get_pending_alerts(limit: int = 50) -> list[dict]:
    db = get_db()
    return list(
        db.alerts_log.find({"status": "pending_review"}, {"_id": 0})
        .sort("triggered_at", -1)
        .limit(limit)
    )


def approve_alert(info_hash: str, user_id: str = "__system__"):
    db = get_db()
    db.alerts_log.update_one(
        {"info_hash": info_hash, "user_id": user_id, "status": "pending_review"},
        {"$set": {"status": "approved", "read": False}},
    )


def reject_alert(info_hash: str, user_id: str = "__system__", reason: str = ""):
    db = get_db()
    db.alerts_log.update_one(
        {"info_hash": info_hash, "user_id": user_id, "status": "pending_review"},
        {"$set": {"status": "rejected", "reject_reason": reason, "read": True}},
    )


# ── 误报反馈 ──────────────────────────────────────────────────────

def save_false_positive(keyword: str, info_hash: str, reason: str = ""):
    db = get_db()
    db.false_positives.update_one(
        {"keyword": keyword},
        {"$inc": {"count": 1},
         "$push": {"examples": {"info_hash": info_hash, "reason": reason}},
         "$set": {"keyword": keyword}},
        upsert=True,
    )


def get_false_positives() -> list[dict]:
    db = get_db()
    return list(db.false_positives.find({}, {"_id": 0}).sort("count", -1))
