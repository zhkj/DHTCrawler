"""长期记忆 Repository — 对话摘要 & 用户画像。"""
from datetime import datetime
from intelligence.db.client import get_db


def save_conversation_summary(user_id: str, summary: str, topics: list[str]):
    db = get_db()
    db.memory_conversations.insert_one({
        "user_id": user_id,
        "summary": summary,
        "topics": topics,
        "created_at": datetime.now(),
    })


def get_conversation_summaries(user_id: str, limit: int = 20) -> list[dict]:
    db = get_db()
    return list(
        db.memory_conversations.find({"user_id": user_id}, {"_id": 0})
        .sort("created_at", -1)
        .limit(limit)
    )


def save_user_profile(user_id: str, profile: dict):
    db = get_db()
    db.user_profiles.update_one(
        {"user_id": user_id},
        {"$set": profile},
        upsert=True,
    )


def get_user_profile(user_id: str) -> dict:
    db = get_db()
    doc = db.user_profiles.find_one({"user_id": user_id}, {"_id": 0})
    return doc or {}
