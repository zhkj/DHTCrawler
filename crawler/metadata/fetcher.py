"""
种子元数据抓取（BEP-9）

通过 BEP-9 扩展协议直接从 announce_peer 的 peer 获取种子元数据，
解析出文件名、大小等信息后存入 MongoDB。

优化：
- 基于 info_hash 去重，避免重复抓取
- 同一 info_hash 多 peer 支持，首个失败尝试下一个
- 高并发 semaphore 控制
"""
import asyncio
import collections
import logging
import datetime

import bencodepy as _bp

_codec = _bp.Bencode()
bdecode = _codec.decode

from crawler.config import METADATA_CONCURRENCY, FETCH_TIMEOUT
from crawler.dht.utils import generate_node_id, bytes_to_hex
from crawler.storage.mongodb import save_torrent_metadata
from crawler.metadata.bep9 import fetch_metadata

logger = logging.getLogger(__name__)

# 已抓取/正在抓取的 info_hash 集合（内存去重）
_seen_hashes: set[bytes] = set()
_SEEN_MAX = 500_000  # 超过此数量时清空旧记录

# 同一 info_hash 的多个 peer 排队
_peer_map: dict[bytes, list[tuple[str, int]]] = collections.defaultdict(list)
_MAX_PEERS_PER_HASH = 3  # 每个 info_hash 最多保留几个 peer


def _parse_raw_metadata(raw: bytes, info_hash: bytes) -> dict | None:
    """解析 BEP-9 返回的 raw info dict bytes，返回结构化元数据"""
    try:
        info = bdecode(raw)
    except Exception:
        return None

    name_raw = info.get(b"name", b"unknown")
    name = name_raw.decode("utf-8", errors="replace")
    btih = info_hash.hex().upper()

    result = {
        "info_hash": bytes_to_hex(info_hash),
        "name":      name,
        "magnet":    f"magnet:?xt=urn:btih:{btih}",
        "date":      datetime.datetime.utcnow(),
    }

    if b"files" in info:
        files = []
        for f in info[b"files"]:
            path   = "/".join(p.decode("utf-8", errors="replace") for p in f.get(b"path", []))
            length = f.get(b"length", 0)
            files.append({"path": path, "length": length})
        result["files"]      = files
        result["total_size"] = sum(f["length"] for f in files)
    else:
        result["total_size"] = info.get(b"length", 0)

    return result


async def fetch_and_save(info_hash: bytes, peers: list[tuple[str, int]]):
    """尝试从多个 peer 获取元数据，第一个成功即返回"""
    peer_id = generate_node_id()
    for peer_addr in peers:
        raw = await fetch_metadata(info_hash, peer_addr, peer_id, timeout=FETCH_TIMEOUT)
        if raw is None:
            continue

        metadata = _parse_raw_metadata(raw, info_hash)
        if metadata:
            await save_torrent_metadata(metadata)
            logger.info("获取成功: %s", metadata["name"][:60])
            return

    logger.debug("BEP-9 所有 peer 均失败: %s (尝试 %d 个)", info_hash.hex()[:16], len(peers))


async def metadata_worker(metadata_queue: asyncio.Queue, concurrency: int = METADATA_CONCURRENCY):
    """
    元数据抓取工作协程。
    从 metadata_queue 取出 announce_peer 的 info_hash + peer 地址，
    去重后并发通过 BEP-9 抓取元数据。
    """
    global _seen_hashes
    semaphore = asyncio.Semaphore(concurrency)

    async def _fetch_with_sem(info_hash: bytes, peers: list[tuple[str, int]]):
        async with semaphore:
            await fetch_and_save(info_hash, peers)

    pending: set[asyncio.Task] = set()

    while True:
        try:
            item = await asyncio.wait_for(metadata_queue.get(), timeout=1.0)
        except asyncio.TimeoutError:
            continue

        peer = item.get("peer")
        if not peer:
            continue

        info_hash = item["hash"]

        # 已成功抓取过的跳过
        if info_hash in _seen_hashes:
            continue

        # 防止 _seen_hashes 无限增长
        if len(_seen_hashes) > _SEEN_MAX:
            _seen_hashes = set()

        _seen_hashes.add(info_hash)

        # 收集该 info_hash 的 peers（可能从队列里连续取到同一 hash 的不同 peer）
        peers = [peer]

        # 非阻塞地尝试再取几个同 hash 或不同 hash 的 item
        extra_items = []
        for _ in range(10):
            try:
                extra = metadata_queue.get_nowait()
            except asyncio.QueueEmpty:
                break
            ep = extra.get("peer")
            if not ep:
                continue
            eh = extra["hash"]
            if eh == info_hash and len(peers) < _MAX_PEERS_PER_HASH:
                peers.append(ep)
            elif eh not in _seen_hashes:
                extra_items.append(extra)

        # 把多余的 item 放回队列
        for ei in extra_items:
            try:
                metadata_queue.put_nowait(ei)
            except asyncio.QueueFull:
                pass

        task = asyncio.create_task(_fetch_with_sem(info_hash, peers))
        pending.add(task)
        task.add_done_callback(pending.discard)

        if len(pending) > concurrency * 3:
            done, pending = await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED)
