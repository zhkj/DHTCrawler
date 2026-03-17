"""
BEP-9: Extension for Peers to Send Metadata Files

通过 BitTorrent 扩展协议 (BEP-10) 直接从 DHT peers 获取种子元数据，
无需依赖第三方 HTTP 缓存服务。

流程：
  1. TCP 连接 peer，完成 BT 握手（声明支持扩展协议）
  2. 交换扩展握手，协商 ut_metadata 消息 ID，获取 metadata_size
  3. 按 16KB 分片请求元数据
  4. 拼装所有分片，SHA1 校验 == info_hash
  5. bdecode 得到 info 字典
"""
import asyncio
import hashlib
import struct
import logging

import bencodepy as _bp

_codec = _bp.Bencode()
bencode = _codec.encode
bdecode = _codec.decode

logger = logging.getLogger(__name__)

BT_HEADER = b"\x13BitTorrent protocol"
EXT_MSG_ID = 20
PIECE_SIZE = 16384  # 16 KB per metadata piece
METADATA_MAX_SIZE = 10 * 1024 * 1024  # 10 MB safety limit
UT_METADATA_LOCAL_ID = 1  # 本端声明的 ut_metadata 消息 ID


def _make_handshake(info_hash: bytes, peer_id: bytes) -> bytes:
    """构造 BT 握手包，声明支持 BEP-10 扩展协议"""
    reserved = bytearray(8)
    reserved[5] |= 0x10  # BEP-10 extension bit
    return BT_HEADER + bytes(reserved) + info_hash + peer_id


def _make_ext_handshake() -> bytes:
    """构造扩展握手消息，声明支持 ut_metadata"""
    payload = bencode({b"m": {b"ut_metadata": UT_METADATA_LOCAL_ID}})
    length = 2 + len(payload)  # 1(msg_id) + 1(ext_id) + payload
    return struct.pack(">I", length) + bytes([EXT_MSG_ID, 0]) + payload


def _make_request(ut_metadata_id: int, piece: int) -> bytes:
    """构造元数据分片请求 (msg_type=0)"""
    payload = bencode({b"msg_type": 0, b"piece": piece})
    length = 2 + len(payload)
    return struct.pack(">I", length) + bytes([EXT_MSG_ID, ut_metadata_id]) + payload


async def _read_msg(reader: asyncio.StreamReader) -> tuple[int, bytes]:
    """读取一条 BT 协议消息，返回 (msg_id, payload)"""
    raw_len = await reader.readexactly(4)
    msg_len = struct.unpack(">I", raw_len)[0]
    if msg_len == 0:
        return -1, b""  # keep-alive
    data = await reader.readexactly(msg_len)
    return data[0], data[1:]


def _find_bencode_end(data: bytes, pos: int = 0) -> int:
    """定位 bencode 编码值的结束位置（用于分离 header dict 和 piece data）"""
    ch = data[pos:pos + 1]
    if ch in (b"d", b"l"):
        i = pos + 1
        while data[i:i + 1] != b"e":
            i = _find_bencode_end(data, i)
        return i + 1
    elif ch == b"i":
        return data.index(b"e", pos) + 1
    else:
        # string: <length>:<data>
        colon = data.index(b":", pos)
        str_len = int(data[pos:colon])
        return colon + 1 + str_len


async def fetch_metadata(
    info_hash: bytes,
    peer_addr: tuple[str, int],
    peer_id: bytes,
    timeout: float = 8.0,
) -> bytes | None:
    """
    通过 BEP-9 从指定 peer 下载种子元数据。
    成功返回 raw info dict bytes，失败返回 None。
    """
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(peer_addr[0], peer_addr[1]),
            timeout=timeout,
        )
    except Exception:
        return None

    try:
        return await asyncio.wait_for(
            _do_fetch(reader, writer, info_hash, peer_id),
            timeout=timeout,
        )
    except Exception as e:
        logger.debug("BEP-9 获取失败 %s:%d - %s", peer_addr[0], peer_addr[1], e)
        return None
    finally:
        writer.close()


async def _do_fetch(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
    info_hash: bytes,
    peer_id: bytes,
) -> bytes | None:
    # ── 1. BT 握手 ──
    writer.write(_make_handshake(info_hash, peer_id))
    await writer.drain()

    hs = await reader.readexactly(68)
    if hs[:20] != BT_HEADER:
        return None
    if not (hs[25] & 0x10):
        return None  # 不支持扩展协议

    # ── 2. 扩展握手 ──
    writer.write(_make_ext_handshake())
    await writer.drain()

    ut_metadata_id = None
    metadata_size = None

    # 读消息直到收到扩展握手回复（跳过 bitfield/have 等）
    for _ in range(50):
        msg_id, payload = await _read_msg(reader)
        if msg_id == EXT_MSG_ID and len(payload) > 1 and payload[0] == 0:
            ext_hs = bdecode(payload[1:])
            m = ext_hs.get(b"m", {})
            ut_metadata_id = m.get(b"ut_metadata")
            metadata_size = ext_hs.get(b"metadata_size")
            break

    if not ut_metadata_id or not metadata_size:
        return None
    if metadata_size > METADATA_MAX_SIZE:
        return None

    # ── 3. 请求所有分片 ──
    num_pieces = (metadata_size + PIECE_SIZE - 1) // PIECE_SIZE
    for i in range(num_pieces):
        writer.write(_make_request(ut_metadata_id, i))
    await writer.drain()

    # ── 4. 收集分片 ──
    pieces: dict[int, bytes] = {}
    for _ in range(200):
        if len(pieces) >= num_pieces:
            break
        msg_id, payload = await _read_msg(reader)
        if msg_id != EXT_MSG_ID or len(payload) < 2:
            continue
        # payload[0] 是对端发给我们的 ext_msg_id，应该等于我们声明的 UT_METADATA_LOCAL_ID
        if payload[0] != UT_METADATA_LOCAL_ID:
            continue

        msg_data = payload[1:]
        try:
            header_end = _find_bencode_end(msg_data)
            header = bdecode(msg_data[:header_end])
        except Exception:
            continue

        msg_type = header.get(b"msg_type")
        if msg_type == 2:
            return None  # reject
        if msg_type != 1:
            continue  # 不是 data 类型

        piece_idx = header[b"piece"]
        piece_data = msg_data[header_end:]
        pieces[piece_idx] = piece_data

    if len(pieces) != num_pieces:
        return None

    # ── 5. 拼装 & SHA1 校验 ──
    metadata = b"".join(pieces[i] for i in range(num_pieces))
    if hashlib.sha1(metadata).digest() != info_hash:
        logger.debug("SHA1 校验失败: %s", info_hash.hex())
        return None

    return metadata
