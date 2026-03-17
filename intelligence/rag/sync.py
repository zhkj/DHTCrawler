"""
RAG 索引自动同步：MongoDB → ChromaDB
支持两种模式：
1. 定时轮询（通用）：每隔 N 秒从 MongoDB 拉增量数据
2. Change Stream（需要 replica set）：实时监听新增
"""
import time
import threading
import logging
from db.mongo_client import get_recent_torrents, get_db
from rag.vectorstore import index_torrents, _get_collection

logger = logging.getLogger("intelligence.rag.sync")

# 默认同步间隔（秒）
_DEFAULT_INTERVAL = 120

# 单次同步最大拉取量
_SYNC_BATCH_SIZE = 500

# 全局同步线程引用，防止重复启动
_sync_thread: threading.Thread | None = None
_sync_stop = threading.Event()


def sync_once(batch_size: int = _SYNC_BATCH_SIZE) -> int:
    """
    执行一次增量同步：从 MongoDB 拉最近数据，索引到 ChromaDB。
    返回新索引的记录数。利用 index_torrents 内部的去重逻辑跳过已索引的。
    """
    torrents = get_recent_torrents(limit=batch_size)
    if not torrents:
        return 0

    collection = _get_collection()
    before = collection.count()
    index_torrents(torrents)
    after = collection.count()
    added = after - before
    if added > 0:
        logger.info(f"[RAG Sync] 增量同步完成，新增 {added} 条索引")
    return added


def start_polling(interval: int = _DEFAULT_INTERVAL):
    """
    启动后台轮询线程，定期从 MongoDB 增量同步到 ChromaDB。
    重复调用不会创建多个线程。
    """
    global _sync_thread
    if _sync_thread is not None and _sync_thread.is_alive():
        logger.info("[RAG Sync] 轮询线程已在运行")
        return

    _sync_stop.clear()

    def _poll_loop():
        logger.info(f"[RAG Sync] 轮询启动，间隔 {interval}s")
        # 启动时立即同步一次
        try:
            sync_once()
        except Exception as e:
            logger.warning(f"[RAG Sync] 首次同步失败: {e}")

        while not _sync_stop.wait(timeout=interval):
            try:
                sync_once()
            except Exception as e:
                logger.warning(f"[RAG Sync] 同步出错: {e}")

        logger.info("[RAG Sync] 轮询已停止")

    _sync_thread = threading.Thread(target=_poll_loop, daemon=True, name="rag-sync")
    _sync_thread.start()


def stop_polling():
    """停止后台轮询线程。"""
    _sync_stop.set()


def start_change_stream():
    """
    使用 MongoDB Change Stream 实时监听新增种子并索引。
    需要 MongoDB 4.0+ 且为 replica set 模式。
    如果不支持 Change Stream，自动回退到定时轮询。
    """
    def _stream_loop():
        logger.info("[RAG Sync] 尝试启动 Change Stream...")
        try:
            db = get_db()
            with db.bt_infos.watch(
                [{"$match": {"operationType": "insert"}}],
                full_document="updateLookup",
            ) as stream:
                logger.info("[RAG Sync] Change Stream 已连接")
                batch = []
                last_flush = time.time()
                for change in stream:
                    if _sync_stop.is_set():
                        break
                    doc = change.get("fullDocument")
                    if doc:
                        doc.pop("_id", None)
                        batch.append(doc)
                    # 攒够 20 条或超过 10 秒就批量索引
                    if len(batch) >= 20 or (batch and time.time() - last_flush > 10):
                        index_torrents(batch)
                        batch.clear()
                        last_flush = time.time()
        except Exception as e:
            logger.warning(f"[RAG Sync] Change Stream 不可用 ({e})，回退到定时轮询")
            start_polling()

    global _sync_thread
    if _sync_thread is not None and _sync_thread.is_alive():
        return

    _sync_stop.clear()
    _sync_thread = threading.Thread(target=_stream_loop, daemon=True, name="rag-sync")
    _sync_thread.start()


def ensure_synced():
    """
    确保同步机制已启动。供 Orchestrator 初始化时调用。
    优先尝试 Change Stream，不支持则自动回退到轮询。
    """
    global _sync_thread
    if _sync_thread is not None and _sync_thread.is_alive():
        return
    # 先做一次立即同步，再启动后台轮询
    try:
        sync_once()
    except Exception as e:
        logger.warning(f"[RAG Sync] 初始同步失败: {e}")
    start_polling()
