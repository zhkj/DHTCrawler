"""种子数据 Repository。"""
from intelligence.db.client import get_db


def get_recent_torrents(limit: int = 100) -> list[dict]:
    db = get_db()
    return list(db.bt_infos.find({}, {"_id": 0}).sort("date", -1).limit(limit))


def get_torrent_by_hash(info_hash: str) -> dict | None:
    db = get_db()
    return db.bt_infos.find_one({"info_hash": info_hash}, {"_id": 0})


def get_recent_info_hashs(limit: int = 500) -> list[dict]:
    db = get_db()
    return list(db.info_hashs.find({}, {"_id": 0}).sort("date", -1).limit(limit))
