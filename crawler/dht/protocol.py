"""
KRPC 协议实现 — asyncio.DatagramProtocol 版本

优化点（相比 Python 2 threading 版本）：
1. 单线程事件循环处理所有 UDP 收发，无线程切换开销
2. asyncio.Queue 解耦网络层和存储层，不阻塞消息处理
3. 批量写入 MongoDB，减少数据库连接次数
4. 结构化日志替代 print
"""
import asyncio
import logging
from bencode import bencode, bdecode  # pip install bencode.py

from crawler.dht.routing_table import RoutingTable
from crawler.dht.utils import (
    generate_node_id, generate_token, generate_trans_id,
    decode_nodes, encode_nodes, bytes_to_hex,
)
from crawler.config import BOOTSTRAP_NODES, FIND_NODE_INTERVAL, SAVE_INTERVAL

logger = logging.getLogger(__name__)

# info_hash 队列容量上限（超过时丢弃旧数据，防止内存无限增长）
QUEUE_MAXSIZE = 10_000


class DHTProtocol(asyncio.DatagramProtocol):
    """
    DHT 节点协议：
    - datagram_received：处理所有入站 UDP 消息（ping/find_node/get_peers/announce_peer）
    - 两个后台任务：主动 find_node 扩展路由表、周期性持久化
    """

    def __init__(
        self,
        node_id: bytes,
        routing_table: RoutingTable,
        info_hash_queue: asyncio.Queue,  # 与 Storage 共享的队列
    ):
        self.node_id       = node_id
        self.routing_table = routing_table
        self.queue         = info_hash_queue
        self.transport: asyncio.DatagramTransport | None = None
        self._tasks: list[asyncio.Task] = []

    # ── asyncio.DatagramProtocol 回调 ────────────────────────────

    def connection_made(self, transport: asyncio.DatagramTransport):
        self.transport = transport
        host, port = transport.get_extra_info("sockname")
        logger.info(f"节点 {self.node_id.hex()[:8]}... 启动，监听 {host}:{port}")
        # 启动后台任务
        self._tasks = [
            asyncio.create_task(self._bootstrap()),
            asyncio.create_task(self._periodic_find_nodes()),
        ]

    def datagram_received(self, data: bytes, addr: tuple[str, int]):
        try:
            msg = bdecode(data)
            self._dispatch(msg, addr)
        except Exception:
            pass  # 忽略无法解析的数据包

    def error_received(self, exc: Exception):
        logger.debug(f"UDP 错误: {exc}")

    def connection_lost(self, exc: Exception | None):
        for task in self._tasks:
            task.cancel()

    # ── 消息分发 ─────────────────────────────────────────────────

    def _dispatch(self, msg: dict, addr: tuple[str, int]):
        msg_type = msg.get(b"y")
        if msg_type == b"q":
            query = msg.get(b"q")
            handlers = {
                b"ping":          self._handle_ping,
                b"find_node":     self._handle_find_node,
                b"get_peers":     self._handle_get_peers,
                b"announce_peer": self._handle_announce_peer,
            }
            handler = handlers.get(query)
            if handler:
                handler(msg, addr)
        elif msg_type == b"r":
            r = msg.get(b"r", {})
            if b"nodes" in r:
                self._handle_find_node_response(r)

    # ── Query 处理 ────────────────────────────────────────────────

    def _handle_ping(self, msg: dict, addr: tuple[str, int]):
        self._send({
            b"t": msg[b"t"],
            b"y": b"r",
            b"r": {b"id": self.node_id},
        }, addr)

    def _handle_find_node(self, msg: dict, addr: tuple[str, int]):
        target = msg[b"a"][b"target"]
        loop = asyncio.get_event_loop()
        closest = loop.run_until_complete(self.routing_table.get_closest(target))
        self._send({
            b"t": msg[b"t"],
            b"y": b"r",
            b"r": {
                b"id":    self.node_id,
                b"nodes": encode_nodes(closest),
            },
        }, addr)

    def _handle_get_peers(self, msg: dict, addr: tuple[str, int]):
        """
        get_peers：其他节点在询问谁有某个种子的 peers。
        我们不存 peers，返回最近节点列表即可。
        同时记录 info_hash（这是被查询的种子，说明有人在下载）。
        """
        info_hash = msg[b"a"][b"info_hash"]
        self._enqueue(info_hash, source="get_peers")

        loop = asyncio.get_event_loop()
        closest = loop.run_until_complete(self.routing_table.get_closest(info_hash))
        self._send({
            b"t": msg[b"t"],
            b"y": b"r",
            b"r": {
                b"id":    self.node_id,
                b"token": generate_token(),
                b"nodes": encode_nodes(closest),
            },
        }, addr)

    def _handle_announce_peer(self, msg: dict, addr: tuple[str, int]):
        """
        announce_peer：其他节点宣告自己正在下载某个种子。
        这是最直接的 info_hash 来源。
        """
        info_hash = msg[b"a"][b"info_hash"]
        self._enqueue(info_hash, source="announce_peer")
        logger.debug(f"(>_<) 收到 announce_peer: {info_hash.hex()}")

        self._send({
            b"t": msg[b"t"],
            b"y": b"r",
            b"r": {b"id": self.node_id},
        }, addr)

    # ── Response 处理 ─────────────────────────────────────────────

    def _handle_find_node_response(self, r: dict):
        nodes = decode_nodes(r.get(b"nodes", b""))
        asyncio.create_task(self.routing_table.add_many(nodes))

    # ── 主动探测 ──────────────────────────────────────────────────

    async def _bootstrap(self):
        """启动时向 bootstrap 节点发送 find_node，加入 DHT 网络"""
        for addr in BOOTSTRAP_NODES:
            self._find_node_to(generate_node_id(), addr)
        await asyncio.sleep(2)

    async def _periodic_find_nodes(self):
        """
        周期性向路由表中所有已知节点发送 find_node。
        这是爬虫扩大路由表、被更多节点"发现"的核心机制。
        """
        while True:
            nodes = await self.routing_table.all_nodes()
            for _, addr in nodes:
                self._find_node_to(generate_node_id(), addr)
            size = await self.routing_table.size()
            logger.info(f"节点 {self.node_id.hex()[:8]}... 路由表大小: {size}")
            await asyncio.sleep(FIND_NODE_INTERVAL)

    def _find_node_to(self, target_id: bytes, addr: tuple[str, int]):
        self._send({
            b"t": generate_trans_id(),
            b"y": b"q",
            b"q": b"find_node",
            b"a": {
                b"id":     self.node_id,
                b"target": target_id,
            },
        }, addr)

    # ── 工具方法 ──────────────────────────────────────────────────

    def _send(self, msg: dict, addr: tuple[str, int]):
        try:
            self.transport.sendto(bencode(msg), addr)
        except Exception:
            pass

    def _enqueue(self, info_hash: bytes, source: str):
        """将 info_hash 放入队列（非阻塞，满了就丢弃）"""
        try:
            self.queue.put_nowait({"hash": info_hash, "source": source})
        except asyncio.QueueFull:
            pass
