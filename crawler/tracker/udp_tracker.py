"""
UDP Tracker 客户端 (BEP-15)

通过 UDP 协议向公共 Tracker 查询指定 info_hash 的 peer 列表。
流程：connect → announce → 解析 peer 列表
"""
import asyncio
import struct
import random
import logging

logger = logging.getLogger(__name__)

CONNECT_MAGIC = 0x41727101980


async def query_tracker(
    tracker_host: str,
    tracker_port: int,
    info_hash: bytes,
    peer_id: bytes,
    listen_port: int = 6881,
    timeout: float = 5.0,
) -> list[tuple[str, int]]:
    """
    向 UDP Tracker 查询 peer 列表。
    成功返回 [(ip, port), ...]，失败返回空列表。
    """
    loop = asyncio.get_running_loop()

    # DNS 解析
    try:
        infos = await asyncio.wait_for(
            loop.getaddrinfo(tracker_host, tracker_port, type=2),
            timeout=timeout,
        )
        if not infos:
            return []
        remote_addr = infos[0][4][:2]  # (ip, port)
    except Exception:
        return []

    transport = None
    try:
        result_future = loop.create_future()
        responses: dict[int, tuple[int, bytes]] = {}

        class TrackerProtocol(asyncio.DatagramProtocol):
            def datagram_received(self, data, addr):
                if len(data) >= 8:
                    action = struct.unpack(">I", data[:4])[0]
                    tid = struct.unpack(">I", data[4:8])[0]
                    responses[tid] = (action, data)
                    if not result_future.done():
                        result_future.set_result(tid)

            def error_received(self, exc):
                pass

        transport, _ = await asyncio.wait_for(
            loop.create_datagram_endpoint(TrackerProtocol, remote_addr=remote_addr),
            timeout=timeout,
        )

        # ── Step 1: Connect ──
        connect_tid = random.randint(0, 0xFFFFFFFF)
        connect_req = struct.pack(">QII", CONNECT_MAGIC, 0, connect_tid)
        transport.sendto(connect_req)

        await asyncio.wait_for(result_future, timeout=timeout)

        if connect_tid not in responses:
            return []
        action, data = responses[connect_tid]
        if action != 0 or len(data) < 16:
            return []
        connection_id = struct.unpack(">Q", data[8:16])[0]

        # ── Step 2: Announce ──
        result_future = loop.create_future()
        announce_tid = random.randint(0, 0xFFFFFFFF)
        announce_req = struct.pack(
            ">QII20s20sQQQIIIiH",
            connection_id,
            1,               # action: announce
            announce_tid,
            info_hash,
            peer_id,
            0,               # downloaded
            0,               # left
            0,               # uploaded
            0,               # event: none
            0,               # ip: default
            random.randint(0, 0xFFFFFFFF),  # key
            200,             # num_want
            listen_port,
        )
        transport.sendto(announce_req)

        await asyncio.wait_for(result_future, timeout=timeout)

        if announce_tid not in responses:
            return []
        action, data = responses[announce_tid]
        if action != 1 or len(data) < 20:
            return []

        # ── 解析 peer 列表 ──
        peers = []
        peer_data = data[20:]
        for i in range(0, len(peer_data) - 5, 6):
            ip = f"{peer_data[i]}.{peer_data[i+1]}.{peer_data[i+2]}.{peer_data[i+3]}"
            port = struct.unpack(">H", peer_data[i+4:i+6])[0]
            if port > 0:
                peers.append((ip, port))

        return peers

    except Exception as e:
        logger.debug("Tracker 查询失败 %s:%d - %s", tracker_host, tracker_port, e)
        return []
    finally:
        if transport:
            transport.close()
