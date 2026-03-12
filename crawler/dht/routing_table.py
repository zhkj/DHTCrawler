"""
路由表（K-bucket）— 基于 Kademlia 算法
160 个桶，第 i 个桶存放与自身 XOR 距离在 [2^i, 2^(i+1)) 内的节点
"""
import random
import asyncio
import logging
from crawler.dht.utils import xor_distance, get_bucket_index
from crawler.config import K, BUCKET_K

logger = logging.getLogger(__name__)

# 每个桶存储格式：(node_id: bytes, addr: tuple[str, int])
Node = tuple[bytes, tuple[str, int]]


class RoutingTable:

    def __init__(self, self_id: bytes):
        self.self_id = self_id
        self._lock   = asyncio.Lock()
        # 160 个 bucket，每个 bucket 是一个列表
        self._buckets: list[list[Node]] = [[] for _ in range(160)]

    async def add(self, node_id: bytes, addr: tuple[str, int]):
        """
        向路由表添加节点。
        桶已满时随机替换（爬虫场景下保持新鲜度比严格 LRU 更重要）。
        """
        if node_id == self.self_id:
            return
        distance = xor_distance(self.self_id, node_id)
        idx = get_bucket_index(distance)

        async with self._lock:
            bucket = self._buckets[idx]
            # 节点已存在则更新地址（节点可能换 IP）
            for i, (nid, _) in enumerate(bucket):
                if nid == node_id:
                    bucket[i] = (node_id, addr)
                    return
            if len(bucket) < BUCKET_K:
                bucket.append((node_id, addr))
            else:
                # 桶已满：随机替换一个旧节点
                bucket[random.randint(0, BUCKET_K - 1)] = (node_id, addr)

    async def add_many(self, nodes: list[Node]):
        for node_id, addr in nodes:
            await self.add(node_id, addr)

    async def get_closest(self, target_id: bytes, k: int = K) -> list[Node]:
        """返回离 target_id 最近的 K 个节点"""
        distance = xor_distance(self.self_id, target_id)
        center   = get_bucket_index(distance)
        result: list[Node] = []

        async with self._lock:
            # 从中心桶向两侧扩展
            left, right = center, center + 1
            while len(result) < k and (left >= 0 or right < 160):
                if left >= 0:
                    result.extend(self._buckets[left])
                    left -= 1
                if right < 160:
                    result.extend(self._buckets[right])
                    right += 1

        # 按 XOR 距离排序，取最近 K 个
        result.sort(key=lambda n: xor_distance(n[0], target_id))
        return result[:k]

    async def all_nodes(self) -> list[Node]:
        """返回所有已知节点（用于周期性 find_node）"""
        async with self._lock:
            return [node for bucket in self._buckets for node in bucket]

    async def size(self) -> int:
        async with self._lock:
            return sum(len(b) for b in self._buckets)

    def to_serializable(self) -> list[list]:
        """序列化为可存入 MongoDB 的格式"""
        result = []
        for bucket in self._buckets:
            result.append([
                [node_id.hex(), list(addr)]
                for node_id, addr in bucket
            ])
        return result

    @classmethod
    def from_serializable(cls, self_id: bytes, data: list[list]) -> "RoutingTable":
        """从 MongoDB 数据恢复路由表"""
        rt = cls(self_id)
        for i, bucket in enumerate(data):
            for item in bucket:
                node_id = bytes.fromhex(item[0])
                addr    = tuple(item[1])
                rt._buckets[i].append((node_id, addr))
        return rt
