"""
MongoDB 数据访问层，读取爬虫采集的数据。
"""
import pymongo
from config import MONGO_HOST, MONGO_PORT, MONGO_DB


def get_db():
    client = pymongo.MongoClient(MONGO_HOST, MONGO_PORT)
    return client[MONGO_DB]


def get_recent_torrents(limit: int = 100) -> list[dict]:
    """获取最近采集的种子元数据（bt_infos 集合）。"""
    db = get_db()
    return list(db.bt_infos.find({}, {"_id": 0}).sort("date", -1).limit(limit))


def get_torrent_by_hash(info_hash: str) -> dict | None:
    """根据 info_hash 查询种子详情。"""
    db = get_db()
    return db.bt_infos.find_one({"info_hash": info_hash}, {"_id": 0})


def get_recent_info_hashs(limit: int = 500) -> list[dict]:
    """获取最近采集的原始 info_hash 记录。"""
    db = get_db()
    return list(db.info_hashs.find({}, {"_id": 0}).sort("date", -1).limit(limit))


def watch_new_torrents():
    """
    MongoDB Change Stream：监听 bt_infos 集合的新增记录。
    用于 Monitor Agent 实时触发。
    需要 MongoDB 4.0+ 且为 replica set 模式。
    """
    db = get_db()
    with db.bt_infos.watch([{"$match": {"operationType": "insert"}}]) as stream:
        for change in stream:
            yield change["fullDocument"]


def save_alert(user_id: str, keywords: list[str]):
    """保存用户告警规则（长期记忆）。"""
    db = get_db()
    db.alerts.update_one(
        {"user_id": user_id},
        {"$set": {"keywords": keywords}},
        upsert=True,
    )


def get_alerts(user_id: str) -> list[str]:
    """读取用户告警规则。"""
    db = get_db()
    doc = db.alerts.find_one({"user_id": user_id})
    return doc["keywords"] if doc else []


def get_all_alert_rules() -> list[dict]:
    """获取所有用户的告警规则，供 Monitor Agent 使用。"""
    db = get_db()
    return list(db.alerts.find({}, {"_id": 0}))


def save_alert_log(log: dict):
    """写入一条告警触发记录。"""
    db = get_db()
    db.alerts_log.insert_one(log)


def get_alert_logs(user_id: str = None, limit: int = 20, unread_only: bool = False) -> list[dict]:
    """读取告警记录，支持按用户和未读过滤。"""
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
    """将用户的所有未读告警标记为已读。"""
    db = get_db()
    db.alerts_log.update_many(
        {"user_id": user_id, "read": False},
        {"$set": {"read": True}},
    )


# ── Human-in-the-Loop: 待审批告警 ──────────────────────────────────

def get_pending_alerts(limit: int = 50) -> list[dict]:
    """获取待人工审批的告警。"""
    db = get_db()
    return list(
        db.alerts_log.find(
            {"status": "pending_review"},
            {"_id": 0},
        ).sort("triggered_at", -1).limit(limit)
    )


def approve_alert(info_hash: str, user_id: str = "__system__"):
    """审批通过告警，触发正式推送。"""
    db = get_db()
    db.alerts_log.update_one(
        {"info_hash": info_hash, "user_id": user_id, "status": "pending_review"},
        {"$set": {"status": "approved", "read": False}},
    )


def reject_alert(info_hash: str, user_id: str = "__system__", reason: str = ""):
    """拒绝告警（误报），记录反馈。"""
    db = get_db()
    db.alerts_log.update_one(
        {"info_hash": info_hash, "user_id": user_id, "status": "pending_review"},
        {"$set": {"status": "rejected", "reject_reason": reason, "read": True}},
    )


def save_false_positive(keyword: str, info_hash: str, reason: str = ""):
    """记录误报关键词，用于后续优化匹配规则。"""
    db = get_db()
    db.false_positives.update_one(
        {"keyword": keyword},
        {"$inc": {"count": 1},
         "$push": {"examples": {"info_hash": info_hash, "reason": reason}},
         "$set": {"keyword": keyword}},
        upsert=True,
    )


def get_false_positives() -> list[dict]:
    """获取所有被标记为误报的关键词统计。"""
    db = get_db()
    return list(db.false_positives.find({}, {"_id": 0}).sort("count", -1))


# ── 长期记忆: 对话摘要存储 ─────────────────────────────────────────

def save_conversation_summary(user_id: str, summary: str, topics: list[str]):
    """保存对话摘要到长期记忆。"""
    from datetime import datetime
    db = get_db()
    db.memory_conversations.insert_one({
        "user_id": user_id,
        "summary": summary,
        "topics": topics,
        "created_at": datetime.now(),
    })


def get_conversation_summaries(user_id: str, limit: int = 20) -> list[dict]:
    """获取用户的历史对话摘要。"""
    db = get_db()
    return list(
        db.memory_conversations.find(
            {"user_id": user_id}, {"_id": 0}
        ).sort("created_at", -1).limit(limit)
    )


def save_user_profile(user_id: str, profile: dict):
    """保存/更新用户画像（关注领域、偏好等）。"""
    db = get_db()
    db.user_profiles.update_one(
        {"user_id": user_id},
        {"$set": profile},
        upsert=True,
    )


def get_user_profile(user_id: str) -> dict:
    """获取用户画像。"""
    db = get_db()
    doc = db.user_profiles.find_one({"user_id": user_id}, {"_id": 0})
    return doc or {}


# ── 可观测性: Trace 存储 ───────────────────────────────────────────

def save_trace(trace: dict):
    """保存一次 Agent 调用的完整 trace。"""
    db = get_db()
    db.traces.insert_one(trace)


def get_traces(limit: int = 50) -> list[dict]:
    """获取最近的 trace 记录。"""
    db = get_db()
    return list(
        db.traces.find({}, {"_id": 0}).sort("start_time", -1).limit(limit)
    )


def save_evaluation(evaluation: dict):
    """保存 LLM-as-judge 评估结果。"""
    db = get_db()
    db.evaluations.insert_one(evaluation)


def get_evaluations(limit: int = 50) -> list[dict]:
    """获取最近的评估记录。"""
    db = get_db()
    return list(
        db.evaluations.find({}, {"_id": 0}).sort("created_at", -1).limit(limit)
    )
