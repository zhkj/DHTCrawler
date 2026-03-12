"""
DHT 爬虫启动入口

架构：
  N 个 DHTProtocol 节点（asyncio.DatagramProtocol）
    └─→ 共享 asyncio.Queue（info_hash 缓冲区）
           ├─→ drain_queue 协程 → 批量写入 MongoDB
           └─→ metadata_worker 协程 → 抓取种子元数据

全程单线程事件循环，无锁竞争（除路由表的 asyncio.Lock）。
"""
import asyncio
import logging
import signal

from crawler.config import NODE_NUM, DHT_PORT, SAVE_INTERVAL, BOOTSTRAP_NODES
from crawler.dht.protocol import DHTProtocol, QUEUE_MAXSIZE
from crawler.dht.routing_table import RoutingTable
from crawler.dht.utils import generate_node_id, hex_to_bytes
from crawler.storage.mongodb import (
    drain_queue, save_routing_table, load_routing_tables,
)
from crawler.metadata.fetcher import metadata_worker

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("dhtcrawler")


async def _periodic_save(node_id: bytes, routing_table: RoutingTable, port: int):
    """周期性持久化路由表"""
    while True:
        await asyncio.sleep(SAVE_INTERVAL)
        await save_routing_table(node_id, routing_table, ("0.0.0.0", port))
        size = await routing_table.size()
        logger.info(f"节点 {node_id.hex()[:8]}... 路由表已保存，节点数: {size}")


async def create_node(
    node_id: bytes,
    routing_table: RoutingTable,
    port: int,
    queue: asyncio.Queue,
) -> asyncio.DatagramTransport:
    loop = asyncio.get_running_loop()
    transport, _ = await loop.create_datagram_endpoint(
        lambda: DHTProtocol(node_id, routing_table, queue),
        local_addr=("0.0.0.0", port),
    )
    return transport


async def main():
    # 加载历史路由表（重启后恢复，跳过 bootstrap 冷启动期）
    saved_tables = await load_routing_tables()
    logger.info(f"从数据库加载 {len(saved_tables)} 个历史节点路由表")

    # 共享队列：所有节点的 info_hash 都进入同一个队列
    queue: asyncio.Queue = asyncio.Queue(maxsize=QUEUE_MAXSIZE)

    transports: list[asyncio.DatagramTransport] = []
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

        transport = await create_node(node_id, routing_table, port, queue)
        transports.append(transport)

        save_tasks.append(asyncio.create_task(
            _periodic_save(node_id, routing_table, port)
        ))

    # 后台任务：消费队列 → 写入 MongoDB
    drain_task = asyncio.create_task(drain_queue(queue))

    # 后台任务：抓取种子元数据
    fetch_task = asyncio.create_task(metadata_worker(queue))

    logger.info(f"DHT 爬虫启动，{NODE_NUM} 个节点，端口 {DHT_PORT}-{DHT_PORT + NODE_NUM - 1}")
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
    for task in save_tasks:
        task.cancel()
    for transport in transports:
        transport.close()
    logger.info("已退出")


if __name__ == "__main__":
    asyncio.run(main())
