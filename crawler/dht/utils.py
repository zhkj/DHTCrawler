"""
DHT 工具函数 — Python 3 版本
bytes 是一等公民，不再做 hex 字符串的中间转换
"""
import os
import struct
import socket


def generate_node_id() -> bytes:
    """生成随机 20 字节节点 ID"""
    return os.urandom(20)


def generate_token(length: int = 5) -> bytes:
    return os.urandom(length)


def generate_trans_id(length: int = 2) -> bytes:
    return os.urandom(length)


def xor_distance(a: bytes, b: bytes) -> int:
    """计算两个节点 ID 的 XOR 距离"""
    return int.from_bytes(a, "big") ^ int.from_bytes(b, "big")


def get_bucket_index(distance: int) -> int:
    """XOR 距离 → 路由表桶索引 (0-159)"""
    if distance == 0:
        return 0
    return min(distance.bit_length() - 1, 159)


def decode_nodes(data: bytes) -> list[tuple[bytes, tuple[str, int]]]:
    """
    解析 compact node info。
    格式：每 26 字节 = 20 字节 NodeID + 4 字节 IP + 2 字节 Port
    """
    nodes = []
    for i in range(0, len(data) - 25, 26):
        node_id = data[i : i + 20]
        try:
            ip   = socket.inet_ntoa(data[i + 20 : i + 24])
            port = struct.unpack("!H", data[i + 24 : i + 26])[0]
            if 1 <= port <= 65535:
                nodes.append((node_id, (ip, port)))
        except Exception:
            continue
    return nodes


def encode_nodes(nodes: list[tuple[bytes, tuple[str, int]]]) -> bytes:
    """序列化节点列表为 compact node info"""
    buf = bytearray()
    for node_id, (ip, port) in nodes:
        try:
            buf += node_id
            buf += socket.inet_aton(ip)
            buf += struct.pack("!H", port)
        except Exception:
            continue
    return bytes(buf)


def bytes_to_hex(b: bytes) -> str:
    return b.hex()


def hex_to_bytes(h: str) -> bytes:
    return bytes.fromhex(h)
