"""
Tracker 反查 worker

从 tracker_queue 取出 info_hash，向多个公共 UDP Tracker 查询 peer，
将找到的 peer 送入 metadata_queue 供 BEP-9 抓取。
"""
import asyncio
import logging

from crawler.config import UDP_TRACKERS, TRACKER_TIMEOUT, TRACKER_CONCURRENCY
from crawler.dht.utils import generate_node_id
from crawler.tracker.udp_tracker import query_tracker

logger = logging.getLogger(__name__)

# 已查询过的 info_hash（避免重复查询 Tracker）
_queried: set[bytes] = set()
_QUERIED_MAX = 200_000


async def tracker_worker(
    tracker_queue: asyncio.Queue,
    metadata_queue: asyncio.Queue,
    concurrency: int = TRACKER_CONCURRENCY,
):
    """
    从 tracker_queue 取 info_hash，查询 UDP Tracker 获取 peer，
    将 peer 送入 metadata_queue。
    """
    global _queried
    semaphore = asyncio.Semaphore(concurrency)
    pending: set[asyncio.Task] = set()

    async def _query_one(info_hash: bytes):
        async with semaphore:
            peer_id = generate_node_id()
            for host, port in UDP_TRACKERS:
                try:
                    peers = await query_tracker(
                        host, port, info_hash, peer_id,
                        timeout=TRACKER_TIMEOUT,
                    )
                except Exception:
                    continue

                if not peers:
                    continue

                fed = 0
                for peer_addr in peers[:10]:
                    try:
                        metadata_queue.put_nowait({
                            "hash": info_hash,
                            "source": "tracker",
                            "peer": peer_addr,
                        })
                        fed += 1
                    except asyncio.QueueFull:
                        break

                if fed:
                    logger.info(
                        "Tracker %s:%d → %s 找到 %d peers，投递 %d",
                        host, port, info_hash.hex()[:16], len(peers), fed,
                    )
                    return  # 一个 tracker 成功即可

    while True:
        try:
            item = await asyncio.wait_for(tracker_queue.get(), timeout=2.0)
        except asyncio.TimeoutError:
            continue

        info_hash = item["hash"]

        if info_hash in _queried:
            continue
        if len(_queried) > _QUERIED_MAX:
            _queried = set()
        _queried.add(info_hash)

        task = asyncio.create_task(_query_one(info_hash))
        pending.add(task)
        task.add_done_callback(pending.discard)

        if len(pending) > concurrency * 2:
            done, pending = await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED)
