"""可观测性 Repository — Trace & 评估结果。"""
from intelligence.db.client import get_db


def save_trace(trace: dict):
    db = get_db()
    db.traces.insert_one(trace)


def get_traces(limit: int = 50) -> list[dict]:
    db = get_db()
    return list(
        db.traces.find({}, {"_id": 0}).sort("start_time", -1).limit(limit)
    )


def save_evaluation(evaluation: dict):
    db = get_db()
    db.evaluations.insert_one(evaluation)


def get_evaluations(limit: int = 50) -> list[dict]:
    db = get_db()
    return list(
        db.evaluations.find({}, {"_id": 0}).sort("created_at", -1).limit(limit)
    )
