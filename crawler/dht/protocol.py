"""
KRPC 协议实现 — asyncio.DatagramProtocol 版本

功能：
1. 被动收集：响应 get_peers/announce_peer，收集 info_hash 和 peer
2. BEP-51 主动采集：向其他节点发送 sample_infohashes，直接获取 info_hash
3. 主动 get_peers：对 BEP-51 获取的 info_hash 发送 get_peers 查找 peer
4. 路由表维护：find_node 扩展路由表 + 淘汰失效节点
"""
import asyncio
import logging
import random
import struct
import time
import bencodepy as _bp
_codec = _bp.Bencode()          # 不传 encoding，key/value 保持 bytes
bencode = _codec.encode
bdecode = _codec.decode

from crawler.dht.routing_table import RoutingTable
from crawler.dht.utils import (
    generate_node_id, generate_neighbor_target, generate_token,
    generate_trans_id, decode_nodes, encode_nodes, bytes_to_hex,
)
from crawler.config import (
    BOOTSTRAP_NODES, FIND_NODE_INTERVAL, SAVE_INTERVAL,
    NODE_MAX_AGE, EVICT_INTERVAL, FIND_NODE_SAMPLE,
    SAMPLE_INTERVAL, SAMPLE_BATCH,
)

logger = logging.getLogger(__name__)

# info_hash 队列容量上限（超过时丢弃旧数据，防止内存无限增长）
QUEUE_MAXSIZE = 50_000


class DHTProtocol(asyncio.DatagramProtocol):
    """
    DHT 节点协议：
    - datagram_received：处理所有入站 UDP 消息
    - 被动模式：响应 ping/find_node/get_peers/announce_peer
    - 主动模式：BEP-51 sample_infohashes + 主动 get_peers
    """

    def __init__(
        self,
        node_id: bytes,
        routing_table: RoutingTable,
        info_hash_queue: asyncio.Queue,  # 与 Storage 共享的队列
        tracker_queue: asyncio.Queue | None = None,  # BEP-51 发现的 hash → Tracker 反查
    ):
        self.node_id       = node_id
        self.routing_table = routing_table
        self.queue         = info_hash_queue
        self.tracker_queue = tracker_queue
        self.transport: asyncio.DatagramTransport | None = None
        self._tasks: list[asyncio.Task] = []

        # 主动 get_peers 的 transaction_id → info_hash 映射
        self._pending_get_peers: dict[bytes, bytes] = {}
        self._pending_max = 10_000

        # 性能计数器（自上次 reset 以来）
        self._msgs_recv:       int = 0
        self._msgs_sent:       int = 0
        self._hashes_enqueued: int = 0
        self._nodes_evicted:   int = 0
        self._samples_found:   int = 0
        self._stats_reset_at:  float = time.time()

        # 按来源分类计数
        self._source_counts: dict[str, int] = {
            "get_peers": 0,
            "announce_peer": 0,
            "active_get_peers": 0,
        }

    # ── asyncio.DatagramProtocol 回调 ────────────────────────────

    def connection_made(self, transport: asyncio.DatagramTransport):
        self.transport = transport
        host, port = transport.get_extra_info("sockname")
        logger.info(f"节点 {self.node_id.hex()[:8]}... 启动，监听 {host}:{port}")
        # 启动后台任务
        self._tasks = [
            asyncio.create_task(self._bootstrap()),
            asyncio.create_task(self._periodic_find_nodes()),
            asyncio.create_task(self._periodic_evict()),
            asyncio.create_task(self._periodic_sample_infohashes()),
        ]

    def datagram_received(self, data: bytes, addr: tuple[str, int]):
        try:
            msg = bdecode(data)
            self._msgs_recv += 1
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
        # 是请求消息
        if msg_type == b"q":
            sender_id = msg.get(b"a", {}).get(b"id")
            if sender_id:
                asyncio.create_task(self.routing_table.mark_seen(sender_id))
            query = msg.get(b"q")
            handlers = {
                b"ping":          self._handle_ping,
                b"find_node":     self._handle_find_node,
                b"get_peers":     self._handle_get_peers,
                b"announce_peer": self._handle_announce_peer,
            }
            handler = handlers.get(query)
            if handler:
                result = handler(msg, addr)
                if asyncio.iscoroutine(result):
                    asyncio.create_task(result)
        elif msg_type == b"r":
            # 是响应消息
            r = msg.get(b"r", {})
            tid = msg.get(b"t")
            sender_id = r.get(b"id")
            if sender_id:
                asyncio.create_task(self.routing_table.mark_seen(sender_id))
            # find_node / get_peers 响应中的 nodes（更近的节点列表）
            if b"nodes" in r:
                self._handle_find_node_response(r)
            # get_peers 响应中的 values（实际 peer 列表）
            if b"values" in r and tid and tid in self._pending_get_peers:
                info_hash = self._pending_get_peers.pop(tid)
                self._handle_get_peers_values(info_hash, r)
            # BEP-51 sample_infohashes 响应
            if b"samples" in r:
                self._handle_sample_response(r)

    # ── Query 处理（被动） ──────────────────────────────────────

    def _handle_ping(self, msg: dict, addr: tuple[str, int]):
        self._send({
            b"t": msg[b"t"],
            b"y": b"r",
            b"r": {b"id": self.node_id},
        }, addr)

    async def _handle_find_node(self, msg: dict, addr: tuple[str, int]):
        target = msg[b"a"][b"target"]
        fake_id = target[:15] + self.node_id[15:]
        closest = await self.routing_table.get_closest(target)
        self._send({
            b"t": msg[b"t"],
            b"y": b"r",
            b"r": {
                b"id":    fake_id,
                b"nodes": encode_nodes(closest),
            },
        }, addr)

    async def _handle_get_peers(self, msg: dict, addr: tuple[str, int]):
        """
        get_peers：其他节点在询问谁有某个种子的 peers。
        我们不存 peers，返回最近节点列表即可。
        同时记录 info_hash（这是被查询的种子，说明有人在下载）。

        关键优化：回复时伪装 node_id 为接近 info_hash 的值，
        让对方认为我们是"最近节点"，从而在下载后向我们发送 announce_peer。
        """
        info_hash = msg[b"a"][b"info_hash"]
        self._enqueue(info_hash, source="get_peers", peer=addr)

        # 伪装成接近 info_hash 的节点（前 15 字节用 info_hash，后 5 字节用真实 ID）
        fake_id = info_hash[:15] + self.node_id[15:]
        closest = await self.routing_table.get_closest(info_hash)
        self._send({
            b"t": msg[b"t"],
            b"y": b"r",
            b"r": {
                b"id":    fake_id,
                b"token": generate_token(),
                b"nodes": encode_nodes(closest),
            },
        }, addr)

    def _handle_announce_peer(self, msg: dict, addr: tuple[str, int]):
        """
        announce_peer：其他节点宣告自己正在下载某个种子。
        这是最直接的 info_hash 来源。
        提取 peer 的 TCP 端口（BEP-5: implied_port），供 BEP-9 元数据抓取使用。
        """
        args = msg[b"a"]
        info_hash = args[b"info_hash"]
        # implied_port=1 时使用 UDP 来源端口，否则使用声明的 port
        if args.get(b"implied_port", 0) != 0:
            peer_addr = addr
        else:
            peer_addr = (addr[0], args.get(b"port", addr[1]))
        self._enqueue(info_hash, source="announce_peer", peer=peer_addr)
        logger.debug(f"(>_<) 收到 announce_peer: {info_hash.hex()} peer={peer_addr}")

        self._send({
            b"t": msg[b"t"],
            b"y": b"r",
            b"r": {b"id": self.node_id},
        }, addr)

    # ── Response 处理 ─────────────────────────────────────────────

    def _handle_find_node_response(self, r: dict):
        nodes = decode_nodes(r.get(b"nodes", b""))
        asyncio.create_task(self.routing_table.add_many(nodes))

    def _handle_get_peers_values(self, info_hash: bytes, r: dict):
        """处理主动 get_peers 返回的 peer 列表（values 字段）"""
        values = r.get(b"values", [])
        for v in values:
            if len(v) == 6:
                ip = f"{v[0]}.{v[1]}.{v[2]}.{v[3]}"
                port = struct.unpack(">H", v[4:6])[0]
                if port > 0:
                    self._enqueue(info_hash, source="active_get_peers", peer=(ip, port))

    def _handle_sample_response(self, r: dict):
        """
        BEP-51: 解析 sample_infohashes 响应。
        samples 字段是 N 个 20 字节 info_hash 的拼接。
        对每个发现的 info_hash：
        1. 主动向 DHT 发 get_peers 查找在线 peer
        2. 投递到 tracker_queue 让 Tracker 反查 peer
        """
        samples = r.get(b"samples", b"")
        if len(samples) % 20 != 0 or not samples:
            return

        # 响应中也可能带 nodes，加入路由表
        if b"nodes" in r:
            nodes = decode_nodes(r.get(b"nodes", b""))
            asyncio.create_task(self.routing_table.add_many(nodes))

        count = len(samples) // 20
        self._samples_found += count

        for i in range(0, len(samples), 20):
            info_hash = samples[i:i + 20]
            # 主动 get_peers：向 DHT 网络查找这个 hash 的 peer
            asyncio.create_task(self._active_get_peers(info_hash))
            # 同时投递到 Tracker 反查队列
            if self.tracker_queue:
                try:
                    self.tracker_queue.put_nowait({"hash": info_hash})
                except asyncio.QueueFull:
                    pass

    # ── 主动探测 ──────────────────────────────────────────────────

    async def _bootstrap(self):
        """启动时向 bootstrap 节点发送 find_node，加入 DHT 网络"""
        for addr in BOOTSTRAP_NODES:
            self._find_node_to(generate_node_id(), addr)
        await asyncio.sleep(2)

    async def _periodic_find_nodes(self):
        """
        周期性向路由表中随机采样的节点发送 find_node。
        采样而非全量广播，降低发包量的同时保持路由表刷新和被发现率。
        路由表为空时自动重新 bootstrap。
        """
        while True:
            nodes = await self.routing_table.all_nodes()
            if not nodes:
                logger.warning(f"节点 {self.node_id.hex()[:8]}... 路由表为空，重新 bootstrap")
                for addr in BOOTSTRAP_NODES:
                    self._find_node_to(generate_node_id(), addr)
            else:
                # 采样发送，避免对大路由表进行广播风暴
                sample = random.sample(nodes, min(FIND_NODE_SAMPLE, len(nodes)))
                for _, addr in sample:
                    # 70% 发邻近 target（让更多节点记住我们），30% 随机 target（扩展路由表）
                    if random.random() < 0.7:
                        target = generate_neighbor_target(self.node_id)
                    else:
                        target = generate_node_id()
                    self._find_node_to(target, addr)
                size = await self.routing_table.size()
                logger.info(f"节点 {self.node_id.hex()[:8]}... 路由表大小: {size}, find_node 发送: {len(sample)}")
            await asyncio.sleep(FIND_NODE_INTERVAL)

    async def _periodic_sample_infohashes(self):
        """
        BEP-51: 周期性向路由表节点发送 sample_infohashes 请求，
        主动采集 info_hash，不依赖被动等待 get_peers/announce_peer。
        """
        # 等待路由表先填充
        await asyncio.sleep(15)
        while True:
            nodes = await self.routing_table.all_nodes()
            if nodes:
                sample = random.sample(nodes, min(SAMPLE_BATCH, len(nodes)))
                for _, addr in sample:
                    self._send_sample_infohashes(addr)
                logger.info(
                    "节点 %s... BEP-51 采样 %d 个节点，累计发现 %d 个 info_hash",
                    self.node_id.hex()[:8], len(sample), self._samples_found,
                )
            await asyncio.sleep(SAMPLE_INTERVAL)

    async def _active_get_peers(self, info_hash: bytes):
        """主动向路由表中最近的节点发送 get_peers，查找指定 info_hash 的 peer"""
        closest = await self.routing_table.get_closest(info_hash)
        for _, addr in closest[:8]:
            self._send_get_peers(info_hash, addr)

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

    def _send_get_peers(self, info_hash: bytes, addr: tuple[str, int]):
        """主动发送 get_peers 请求，记录 transaction_id 以关联响应"""
        tid = generate_trans_id()
        # 防止内存泄漏
        if len(self._pending_get_peers) > self._pending_max:
            self._pending_get_peers.clear()
        self._pending_get_peers[tid] = info_hash
        self._send({
            b"t": tid,
            b"y": b"q",
            b"q": b"get_peers",
            b"a": {
                b"id":        self.node_id,
                b"info_hash": info_hash,
            },
        }, addr)

    def _send_sample_infohashes(self, addr: tuple[str, int]):
        """BEP-51: 发送 sample_infohashes 请求"""
        self._send({
            b"t": generate_trans_id(),
            b"y": b"q",
            b"q": b"sample_infohashes",
            b"a": {
                b"id":     self.node_id,
                b"target": generate_node_id(),
            },
        }, addr)

    # ── 工具方法 ──────────────────────────────────────────────────

    def _send(self, msg: dict, addr: tuple[str, int]):
        try:
            self.transport.sendto(bencode(msg), addr)
            self._msgs_sent += 1
        except Exception:
            pass

    def _enqueue(self, info_hash: bytes, source: str, peer: tuple[str, int] | None = None):
        """将 info_hash 放入队列（非阻塞，满了就丢弃）"""
        try:
            item = {"hash": info_hash, "source": source}
            if peer:
                item["peer"] = peer
            self.queue.put_nowait(item)
            self._hashes_enqueued += 1
            if source in self._source_counts:
                self._source_counts[source] += 1
            logger.info("[%s] info_hash=%s peer=%s", source, info_hash.hex(), peer)
        except asyncio.QueueFull:
            logger.warning("info_hash 队列已满，丢弃数据（queue_size=%d）", self.queue.maxsize)

    def get_stats(self) -> dict:
        """返回当前周期的统计数据并重置计数器"""
        elapsed = time.time() - self._stats_reset_at
        stats = {
            "node_id":         self.node_id.hex()[:8],
            "elapsed_s":       round(elapsed, 1),
            "msgs_recv":       self._msgs_recv,
            "msgs_sent":       self._msgs_sent,
            "hashes_enqueued": self._hashes_enqueued,
            "nodes_evicted":   self._nodes_evicted,
            "samples_found":   self._samples_found,
            "recv_per_s":      round(self._msgs_recv / max(elapsed, 1), 1),
            "hash_per_s":      round(self._hashes_enqueued / max(elapsed, 1), 2),
            "source_counts":   dict(self._source_counts),
        }
        self._msgs_recv = self._msgs_sent = self._hashes_enqueued = 0
        self._nodes_evicted = 0
        self._samples_found = 0
        for k in self._source_counts:
            self._source_counts[k] = 0
        self._stats_reset_at = time.time()
        return stats

    async def _periodic_evict(self):
        """周期性淘汰长期未活跃节点"""
        while True:
            await asyncio.sleep(EVICT_INTERVAL)
            evicted = await self.routing_table.evict_stale(NODE_MAX_AGE)
            self._nodes_evicted += evicted
            if evicted:
                size = await self.routing_table.size()
                logger.info(
                    "节点 %s... 淘汰 %d 个失效节点，路由表剩余: %d",
                    self.node_id.hex()[:8], evicted, size,
                )
