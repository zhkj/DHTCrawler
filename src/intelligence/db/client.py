"""MongoDB 连接管理。"""
import pymongo
from intelligence.config import MONGO_HOST, MONGO_PORT, MONGO_DB

_client = None


def get_db():
    global _client
    if _client is None:
        _client = pymongo.MongoClient(MONGO_HOST, MONGO_PORT)
    return _client[MONGO_DB]
