import os
from dotenv import load_dotenv

# 加载项目根目录的 .env（crawler 和 intelligence 共享同一份配置）
_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(_root, ".env"))

# ── DHT 爬虫配置 ──────────────────────────────────────────────────
NODE_NUM    = int(os.getenv("DHT_NODE_NUM", 3))      # 并发节点数，越多采集越快
DHT_PORT    = int(os.getenv("DHT_PORT", 6881))        # 监听端口（多节点自动递增）
FIND_NODE_INTERVAL = float(os.getenv("FIND_NODE_INTERVAL", 2.0))  # 主动探测间隔(秒)
SAVE_INTERVAL      = float(os.getenv("SAVE_INTERVAL", 10.0))      # 路由表持久化间隔

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
MONGO_DB   = "dhtcrawler"

# ── 元数据抓取 ────────────────────────────────────────────────────
# 抓取种子元数据的第三方缓存服务（按优先级排列）
TORRENT_SOURCES = [
    "https://itorrents.org/torrent/{btih}.torrent",
    "https://torrage.info/torrent.php?h={btih}",
]
FETCH_TIMEOUT = 15   # 单次 HTTP 请求超时（秒）
