"""RAG 索引自动同步：MongoDB -> ChromaDB。"""
import time
import threading
import logging
from intelligence.db import get_db, get_recent_torrents
from intelligence.rag.vectorstore import index_torrents, _get_collection

logger = logging.getLogger("intelligence.rag.sync")

_DEFAULT_INTERVAL = 120
_SYNC_BATCH_SIZE = 500
_sync_thread: threading.Thread | None = None
_sync_stop = threading.Event()


def sync_once(batch_size: int = _SYNC_BATCH_SIZE) -> int:
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
    global _sync_thread
    if _sync_thread is not None and _sync_thread.is_alive():
        return

    _sync_stop.clear()

    def _poll_loop():
        logger.info(f"[RAG Sync] 轮询启动，间隔 {interval}s")
        try:
            sync_once()
        except Exception as e:
            logger.warning(f"[RAG Sync] 首次同步失败: {e}")

        while not _sync_stop.wait(timeout=interval):
            try:
                sync_once()
            except Exception as e:
                logger.warning(f"[RAG Sync] 同步出错: {e}")

    _sync_thread = threading.Thread(target=_poll_loop, daemon=True, name="rag-sync")
    _sync_thread.start()


def stop_polling():
    _sync_stop.set()


def start_change_stream():
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
                    if len(batch) >= 20 or (batch and time.time() - last_flush > 10):
                        index_torrents(batch)
                        batch.clear()
                        last_flush = time.time()
        except Exception as e:
            logger.warning(f"[RAG Sync] Change Stream 不可用 ({e})，回退到轮询")
            start_polling()

    global _sync_thread
    if _sync_thread is not None and _sync_thread.is_alive():
        return
    _sync_stop.clear()
    _sync_thread = threading.Thread(target=_stream_loop, daemon=True, name="rag-sync")
    _sync_thread.start()


def ensure_synced():
    global _sync_thread
    if _sync_thread is not None and _sync_thread.is_alive():
        return
    try:
        sync_once()
    except Exception as e:
        logger.warning(f"[RAG Sync] 初始同步失败: {e}")
    start_polling()
