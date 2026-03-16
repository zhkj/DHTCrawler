import os
from dotenv import load_dotenv

# 加载项目根目录的 .env（crawler 和 intelligence 共享同一份配置）
_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(_root, ".env"))

# ── DHT 爬虫配置 ──────────────────────────────────────────────────
NODE_NUM    = int(os.getenv("DHT_NODE_NUM", 8))       # 并发节点数，越多采集越快
DHT_PORT    = int(os.getenv("DHT_PORT", 6881))        # 监听端口（多节点自动递增）
FIND_NODE_INTERVAL = float(os.getenv("FIND_NODE_INTERVAL", 1.0))  # 主动探测间隔(秒)
SAVE_INTERVAL      = float(os.getenv("SAVE_INTERVAL", 10.0))      # 路由表持久化间隔
NODE_MAX_AGE       = float(os.getenv("NODE_MAX_AGE", 900.0))       # 节点最大存活时间(秒)，超时视为失效
EVICT_INTERVAL     = float(os.getenv("EVICT_INTERVAL", 120.0))     # 淘汰检查间隔(秒)
STATS_INTERVAL     = float(os.getenv("STATS_INTERVAL", 30.0))      # 性能统计日志间隔(秒)

# 路由表每个 bucket 最大节点数（K 值）
K         = 8
BUCKET_K  = 1500   # 爬虫模式下放大 K，容纳更多节点

# Bootstrap 节点（DHT 网络入口）
BOOTSTRAP_NODES = [
    ("router.bittorrent.com", 6881),
    ("dht.transmissionbt.com", 6881),
    ("router.utorrent.com",    6881),
]

# ── MongoDB ────────────────────────────────────────────────────────
MONGO_HOST = os.getenv("MONGO_HOST", "127.0.0.1")
MONGO_PORT = int(os.getenv("MONGO_PORT", 27017))
MONGO_DB   = "dht"

# ── 元数据抓取 ────────────────────────────────────────────────────
# 抓取种子元数据的第三方缓存服务（按优先级排列）
TORRENT_SOURCES = [
    "https://itorrents.org/torrent/{btih}.torrent",
    "https://torrage.info/torrent.php?h={btih}",
]
FETCH_TIMEOUT = 8    # 单次请求超时（秒），缩短以加快轮转
METADATA_CONCURRENCY = int(os.getenv("METADATA_CONCURRENCY", 200))  # BEP-9 并发抓取数
FIND_NODE_SAMPLE = int(os.getenv("FIND_NODE_SAMPLE", 200))  # 每轮 find_node 采样节点数

# ── BEP-51 主动采集 ─────────────────────────────────────────────
SAMPLE_INTERVAL    = float(os.getenv("SAMPLE_INTERVAL", 5.0))   # sample_infohashes 发送间隔(秒)
SAMPLE_BATCH       = int(os.getenv("SAMPLE_BATCH", 50))         # 每轮采样的节点数

# ── UDP Tracker 反查 ────────────────────────────────────────────
TRACKER_TIMEOUT     = float(os.getenv("TRACKER_TIMEOUT", 5.0))
TRACKER_CONCURRENCY = int(os.getenv("TRACKER_CONCURRENCY", 50))
UDP_TRACKERS = [
    ("tracker.opentrackr.org", 1337),
    ("tracker.openbittorrent.com", 6969),
    ("open.stealth.si", 80),
    ("exodus.desync.com", 6969),
    ("tracker.torrent.eu.org", 451),
    ("open.demonii.com", 1337),
    ("tracker.moeking.me", 6969),
]
