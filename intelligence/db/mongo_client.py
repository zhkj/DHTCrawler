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
