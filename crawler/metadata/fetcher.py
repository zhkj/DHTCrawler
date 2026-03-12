"""
种子元数据抓取
根据 info_hash 从第三方缓存服务下载 .torrent 文件，解析出文件名、大小等信息。

注：更优雅的方案是直接实现 BEP-9（Magnet URI extension），
    从 DHT peers 直接获取 metadata，不依赖第三方服务。
    这里先用 HTTP 方式实现，作为 v1 版本。
"""
import asyncio
import logging
import datetime
import httpx
from bencode import bdecode

from crawler.config import TORRENT_SOURCES, FETCH_TIMEOUT
from crawler.dht.utils import bytes_to_hex
from crawler.storage.mongodb import save_torrent_metadata

logger = logging.getLogger(__name__)


def _btih(info_hash: bytes) -> str:
    """bytes → 大写十六进制字符串（标准 BTIH 格式）"""
    return info_hash.hex().upper()


def _parse_torrent(content: bytes, info_hash: bytes) -> dict | None:
    """解析 .torrent 文件内容，返回结构化元数据"""
    try:
        torrent = bdecode(content)
    except Exception:
        return None

    info = torrent.get(b"info")
    if not info:
        return None

    # 文件名（bytes → str）
    name_raw = info.get(b"name", b"unknown")
    name = name_raw.decode("utf-8", errors="replace")

    btih   = _btih(info_hash)
    result = {
        "info_hash": bytes_to_hex(info_hash),
        "name":      name,
        "magnet":    f"magnet:?xt=urn:btih:{btih}",
        "date":      datetime.datetime.utcnow(),
    }

    if b"files" in info:
        # 多文件种子
        files = []
        for f in info[b"files"]:
            path   = "/".join(p.decode("utf-8", errors="replace") for p in f.get(b"path", []))
            length = f.get(b"length", 0)
            files.append({"path": path, "length": length})
        result["files"]       = files
        result["total_size"]  = sum(f["length"] for f in files)
    else:
        # 单文件种子
        result["total_size"]  = info.get(b"length", 0)

    return result


async def fetch_and_save(info_hash: bytes):
    """
    尝试从各缓存源下载 .torrent，解析后存入 MongoDB。
    任意一个源成功即停止。
    """
    btih = _btih(info_hash)

    async with httpx.AsyncClient(
        timeout=FETCH_TIMEOUT,
        headers={"User-Agent": "Mozilla/5.0"},
        follow_redirects=True,
    ) as client:
        for url_template in TORRENT_SOURCES:
            url = url_template.format(btih=btih)
            try:
                resp = await client.get(url)
                if resp.status_code == 200 and len(resp.content) > 100:
                    metadata = _parse_torrent(resp.content, info_hash)
                    if metadata:
                        await save_torrent_metadata(metadata)
                        logger.info(f"获取成功: {metadata['name'][:60]}")
                        return
            except Exception as e:
                logger.debug(f"[{url}] 失败: {e}")

    logger.debug(f"所有源均失败: {btih}")


async def metadata_worker(info_hash_queue: asyncio.Queue, concurrency: int = 10):
    """
    元数据抓取工作协程。
    从队列取出 announce_peer 的 info_hash，并发抓取元数据。
    只处理 announce_peer（已宣告下载的），get_peers 的暂不处理（量太大）。
    """
    semaphore = asyncio.Semaphore(concurrency)

    async def _fetch_with_sem(info_hash: bytes):
        async with semaphore:
            await fetch_and_save(info_hash)

    pending: set[asyncio.Task] = set()

    while True:
        try:
            item = await asyncio.wait_for(info_hash_queue.get(), timeout=1.0)
        except asyncio.TimeoutError:
            continue

        if item.get("source") != "announce_peer":
            continue

        task = asyncio.create_task(_fetch_with_sem(item["hash"]))
        pending.add(task)
        task.add_done_callback(pending.discard)

        # 防止 pending 无限增长
        if len(pending) > concurrency * 3:
            done, pending = await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED)
