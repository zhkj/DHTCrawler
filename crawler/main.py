"""
DHT 爬虫启动入口

架构：
  N 个 DHTProtocol 节点（asyncio.DatagramProtocol）
    └─→ 共享 asyncio.Queue（info_hash 缓冲区）
           ├─→ drain_queue 协程 → 批量写入 MongoDB
           │     ├─→ 有 peer 的 item → metadata_queue → BEP-9 抓取元数据
           │     └─→ 无 peer 的 item → tracker_queue  → Tracker 反查 peer → metadata_queue
           └─→ BEP-51 sample_infohashes → 主动发现 info_hash
                 ├─→ active get_peers → peer → info_hash_queue → metadata_queue
                 └─→ tracker_queue → Tracker 反查 peer → metadata_queue

全程单线程事件循环，无锁竞争（除路由表的 asyncio.Lock）。
"""
import asyncio
import logging
import signal

from crawler.config import (
    NODE_NUM, DHT_PORT, SAVE_INTERVAL, STATS_INTERVAL,
    BOOTSTRAP_NODES, METADATA_CONCURRENCY, TRACKER_CONCURRENCY,
)
from crawler.dht.protocol import DHTProtocol, QUEUE_MAXSIZE
from crawler.dht.routing_table import RoutingTable
from crawler.dht.utils import generate_node_id, hex_to_bytes
from crawler.storage.mongodb import (
    drain_queue, save_routing_table, load_routing_tables,
)
from crawler.metadata.fetcher import metadata_worker
from crawler.tracker.worker import tracker_worker

import os

_log_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "logs")
os.makedirs(_log_dir, exist_ok=True)
_log_file = os.path.join(_log_dir, "crawler.log")

_file_handler = logging.FileHandler(_log_file, encoding="utf-8")
_file_handler.setFormatter(logging.Formatter(
    "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
))
_console_handler = logging.StreamHandler()
_console_handler.setFormatter(logging.Formatter(
    "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
))

logging.basicConfig(level=logging.INFO, handlers=[_file_handler, _console_handler])
logger = logging.getLogger("dhtcrawler")


async def _periodic_save(node_id: bytes, routing_table: RoutingTable, port: int):
    """周期性持久化路由表"""
    while True:
        await asyncio.sleep(SAVE_INTERVAL)
        await save_routing_table(node_id, routing_table, ("0.0.0.0", port))
        size = await routing_table.size()
        logger.info(f"节点 {node_id.hex()[:8]}... 路由表已保存，节点数: {size}")


async def _periodic_stats(
    protocols: list["DHTProtocol"],
    queue: asyncio.Queue,
    metadata_queue: asyncio.Queue,
    tracker_queue: asyncio.Queue,
):
    """周期性打印性能统计：吞吐量、队列水位、路由表大小"""
    while True:
        await asyncio.sleep(STATS_INTERVAL)
        total_recv = total_sent = total_hashes = total_evicted = total_samples = 0
        for proto in protocols:
            s = proto.get_stats()
            total_recv    += s["msgs_recv"]
            total_sent    += s["msgs_sent"]
            total_hashes  += s["hashes_enqueued"]
            total_evicted += s["nodes_evicted"]
            total_samples += s["samples_found"]
            rt_size = await proto.routing_table.size()
            logger.info(
                "[节点 %s] recv=%d sent=%d hashes=%d(%.2f/s) samples=%d evicted=%d rt=%d",
                s["node_id"], s["msgs_recv"], s["msgs_sent"],
                s["hashes_enqueued"], s["hash_per_s"],
                s["samples_found"], s["nodes_evicted"], rt_size,
            )
        logger.info(
            "[汇总] recv=%d sent=%d hashes=%d samples=%d evicted=%d "
            "queue=%d/%d meta_q=%d/%d tracker_q=%d/%d",
            total_recv, total_sent, total_hashes, total_samples, total_evicted,
            queue.qsize(), queue.maxsize,
            metadata_queue.qsize(), metadata_queue.maxsize,
            tracker_queue.qsize(), tracker_queue.maxsize,
        )


async def create_node(
    node_id: bytes,
    routing_table: RoutingTable,
    port: int,
    queue: asyncio.Queue,
    tracker_queue: asyncio.Queue,
) -> tuple[asyncio.DatagramTransport, DHTProtocol]:
    loop = asyncio.get_running_loop()
    protocol = DHTProtocol(node_id, routing_table, queue, tracker_queue)
    transport, _ = await loop.create_datagram_endpoint(
        lambda: protocol,
        local_addr=("0.0.0.0", port),
    )
    return transport, protocol


async def main():
    # 加载历史路由表（重启后恢复，跳过 bootstrap 冷启动期）
    saved_tables = await load_routing_tables()
    logger.info(f"从数据库加载 {len(saved_tables)} 个历史节点路由表")

    # 共享队列：所有节点的 info_hash 都进入同一个队列
    queue: asyncio.Queue = asyncio.Queue(maxsize=QUEUE_MAXSIZE)

    # 元数据抓取队列（带 peer 地址的 item）
    metadata_queue: asyncio.Queue = asyncio.Queue(maxsize=QUEUE_MAXSIZE * 2)

    # Tracker 反查队列（无 peer 的 info_hash → Tracker 查 peer → metadata_queue）
    tracker_queue: asyncio.Queue = asyncio.Queue(maxsize=QUEUE_MAXSIZE)

    transports: list[asyncio.DatagramTransport] = []
    protocols:  list[DHTProtocol] = []
    save_tasks: list[asyncio.Task] = []

    for i in range(NODE_NUM):
        port = DHT_PORT + i

        # 优先使用历史节点信息（含路由表），否则新建节点
        if i < len(saved_tables):
            saved = saved_tables[i]
            node_id = hex_to_bytes(saved["node_id"])
            routing_table = RoutingTable.from_serializable(node_id, saved["rtable"])
            logger.info(f"节点 {i} 从历史恢复: {node_id.hex()[:8]}...")
        else:
            node_id = generate_node_id()
            routing_table = RoutingTable(node_id)
            logger.info(f"节点 {i} 新建: {node_id.hex()[:8]}...")

        transport, protocol = await create_node(node_id, routing_table, port, queue, tracker_queue)
        transports.append(transport)
        protocols.append(protocol)

        save_tasks.append(asyncio.create_task(
            _periodic_save(node_id, routing_table, port)
        ))

    # 后台任务：消费队列 → 写入 MongoDB → 分发到 metadata_queue / tracker_queue
    drain_task = asyncio.create_task(drain_queue(queue, metadata_queue, tracker_queue))

    # 后台任务：从 metadata_queue 抓取种子元数据（BEP-9）
    fetch_task = asyncio.create_task(metadata_worker(metadata_queue))

    # 后台任务：Tracker 反查 → 找到 peer → 送入 metadata_queue
    tracker_task = asyncio.create_task(tracker_worker(tracker_queue, metadata_queue))

    # 后台任务：性能统计日志
    stats_task = asyncio.create_task(_periodic_stats(protocols, queue, metadata_queue, tracker_queue))

    logger.info(
        "DHT 爬虫启动，%d 个节点，端口 %d-%d，元数据并发: %d，Tracker 并发: %d",
        NODE_NUM, DHT_PORT, DHT_PORT + NODE_NUM - 1,
        METADATA_CONCURRENCY, TRACKER_CONCURRENCY,
    )
    logger.info("按 Ctrl+C 优雅退出")

    # 等待退出信号
    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop_event.set)

    await stop_event.wait()

    # 优雅退出
    logger.info("正在关闭...")
    drain_task.cancel()
    fetch_task.cancel()
    tracker_task.cancel()
    stats_task.cancel()
    for task in save_tasks:
        task.cancel()
    for transport in transports:
        transport.close()
    logger.info("已退出")


if __name__ == "__main__":
    asyncio.run(main())
