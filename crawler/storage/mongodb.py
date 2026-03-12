"""
MongoDB 存储层
- 使用连接池（MongoClient 本身是线程/协程安全的）
- 批量写入减少 RTT
- 路由表持久化，重启后恢复节点状态
"""
import asyncio
import logging
import datetime
import pymongo
from pymongo import UpdateOne

from crawler.config import MONGO_HOST, MONGO_PORT, MONGO_DB
from crawler.dht.utils import bytes_to_hex

logger = logging.getLogger(__name__)

# MongoDB 连接池（全局单例）
_client: pymongo.MongoClient | None = None


def _db():
    global _client
    if _client is None:
        _client = pymongo.MongoClient(
            MONGO_HOST, MONGO_PORT,
            maxPoolSize=10,
            serverSelectionTimeoutMS=5000,
        )
    return _client[MONGO_DB]


# ── info_hash 批量写入 ────────────────────────────────────────────

async def drain_queue(queue: asyncio.Queue, batch_size: int = 200, interval: float = 5.0):
    """
    持续消费 info_hash 队列，批量写入 MongoDB。
    作为独立协程运行，与网络层解耦。
    """
    while True:
        batch = []
        try:
            # 等待第一条数据
            item = await asyncio.wait_for(queue.get(), timeout=interval)
            batch.append(item)
            # 尽量多取，凑成批次（非阻塞）
            while len(batch) < batch_size:
                try:
                    batch.append(queue.get_nowait())
                except asyncio.QueueEmpty:
                    break
        except asyncio.TimeoutError:
            continue

        if batch:
            await asyncio.to_thread(_write_info_hashs, batch)


def _write_info_hashs(batch: list[dict]):
    """同步写入（在线程池中执行，不阻塞事件循环）"""
    db = _db()
    now = datetime.datetime.utcnow()

    announce_docs, get_peer_docs = [], []
    for item in batch:
        doc = {"value": bytes_to_hex(item["hash"]), "date": now}
        if item["source"] == "announce_peer":
            announce_docs.append(doc)
        else:
            get_peer_docs.append(doc)

    try:
        if announce_docs:
            db.info_hashs.insert_many(announce_docs, ordered=False)
            logger.debug(f"写入 {len(announce_docs)} 条 announce_peer info_hash")
        if get_peer_docs:
            db.get_peer_info_hashs.insert_many(get_peer_docs, ordered=False)
            logger.debug(f"写入 {len(get_peer_docs)} 条 get_peers info_hash")
    except Exception as e:
        logger.error(f"MongoDB 写入失败: {e}")


# ── 路由表持久化 ──────────────────────────────────────────────────

async def save_routing_table(node_id: bytes, routing_table, addr: tuple[str, int]):
    """异步持久化路由表（在线程池中执行）"""
    node_id_hex = bytes_to_hex(node_id)
    rt_data     = routing_table.to_serializable()
    await asyncio.to_thread(_upsert_routing_table, node_id_hex, rt_data, addr)


def _upsert_routing_table(node_id_hex: str, rt_data: list, addr: tuple):
    db = _db()
    db.rtables.update_one(
        {"node_id": node_id_hex},
        {"$set": {"rtable": rt_data, "addr": list(addr)}},
        upsert=True,
    )


async def load_routing_tables() -> list[dict]:
    """启动时从 MongoDB 恢复所有节点的路由表"""
    return await asyncio.to_thread(_load_routing_tables)


def _load_routing_tables() -> list[dict]:
    db = _db()
    return list(db.rtables.find({}, {"_id": 0}))


# ── 种子元数据 ────────────────────────────────────────────────────

async def save_torrent_metadata(metadata: dict):
    await asyncio.to_thread(_save_torrent_metadata, metadata)


def _save_torrent_metadata(metadata: dict):
    db = _db()
    try:
        db.bt_infos.update_one(
            {"info_hash": metadata["info_hash"]},
            {"$set": metadata},
            upsert=True,
        )
    except Exception as e:
        logger.error(f"保存种子元数据失败: {e}")
