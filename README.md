# DHTCrawler

基于 BitTorrent DHT 协议的 Python 3 爬虫。通过被动监听 + BEP-51 主动采集 + UDP Tracker 反查，三管齐下获取 `info_hash` 并通过 BEP-9 抓取种子元数据。

---

## 功能

- **被动采集**：伪装成 DHT 节点，捕获 `announce_peer`（节点宣布下载）和 `get_peers`（节点查询 peers）中的 `info_hash`
- **BEP-51 主动采集**：向 DHT 节点发送 `sample_infohashes` 请求，批量获取 `info_hash`，再通过主动 `get_peers` 查找在线 peer
- **UDP Tracker 反查**：对无 peer 的 `info_hash`，向公共 UDP Tracker 查询 peer 列表，补充 BEP-9 抓取来源
- **BEP-9 元数据抓取**：直接从 peer 的 TCP 连接获取种子元数据（文件名、大小、文件列表），无需依赖第三方 HTTP 缓存
- **路由表持久化**：路由表存储到 MongoDB，重启后恢复节点状态，跳过 bootstrap 冷启动
- **多节点并发**：支持同时运行多个 DHT 节点（默认 8 个），提高采集覆盖面
- **Intelligence Agent**：基于 Claude API 的智能查询层，支持自然语言搜索种子、统计分析等

---

## 架构

```
                      DHT 网络
                         │
      ┌──────────────────┼──────────────────┐
      │                  │                  │
   被动接收           被动接收        BEP-51 主动采集
   get_peers       announce_peer    sample_infohashes
   (hash, 无peer)  (hash + peer)    (批量 hash)
      │                  │                  │
      │                  │          ┌───────┴───────┐
      │                  │          │               │
      │                  │   active get_peers    tracker_queue
      │                  │   (DHT 查 peer)          │
      │                  │          │               │
      ▼                  ▼          ▼               ▼
    ┌────────── info_hash_queue ─────────┐    UDP Tracker
    │           drain_queue              │    反查 peer
    │        (批量写入 MongoDB)          │        │
    └──────┬─────────────┬───────────────┘        │
           │             │                        │
       有 peer        无 peer                     │
           │             │                        │
           │       tracker_queue ◄────────────────┘
           │             │
           ▼             ▼
      metadata_queue ◄───┘
           │
     BEP-9 元数据抓取 (200 并发)
           │
           ▼
     MongoDB bt_infos
```

---

## 工作原理

### 1. DHT 网络与 Kademlia 算法

BitTorrent DHT 基于 **Kademlia** 分布式哈希表。每个节点拥有 160 位 Node ID，节点间距离通过 XOR 计算。路由表由 160 个 k-bucket 组成，爬虫模式下每个 bucket 容量放大到 1500（标准值为 8），以容纳更多节点。

### 2. 被动采集（KRPC 协议）

| 消息类型 | 说明 | 对爬虫的价值 |
|---|---|---|
| `get_peers` | 其他节点查询某 info_hash 的 peer | 获取 info_hash（无可靠 peer 地址） |
| `announce_peer` | 其他节点宣告正在下载 | 获取 info_hash + peer TCP 地址（高质量） |

**关键优化**：回复 `get_peers` 时伪装 Node ID（前 15 字节用 info_hash），让对方认为我们是"最近节点"，后续触发 `announce_peer` 回传。

### 3. BEP-51 主动采集

周期性向路由表中的节点发送 `sample_infohashes` 请求，对方直接返回其存储的 info_hash 列表。拿到 hash 后：
- 向 DHT 网络发送主动 `get_peers`，查找在线 peer
- 同时投递到 Tracker 反查队列

### 4. UDP Tracker 反查（BEP-15）

对无 peer 的 info_hash，向公共 UDP Tracker（opentrackr.org、openbittorrent.com 等）发送 announce 请求，获取 peer 列表，补充 BEP-9 抓取来源。

### 5. BEP-9 元数据抓取

通过 TCP 连接 peer，完成 BT 握手 → 扩展握手（BEP-10）→ 请求 metadata 分片 → SHA1 校验 → bencode 解析，提取种子名称、文件列表、总大小等信息。

---

## 项目结构

```
DHTCrawler/
├── crawler/
│   ├── main.py                 # 启动入口：事件循环、队列编排、信号处理
│   ├── config.py               # 配置：节点数、端口、超时、Tracker 列表等
│   ├── dht/
│   │   ├── protocol.py         # KRPC 协议：被动响应 + BEP-51 主动采集 + 主动 get_peers
│   │   ├── routing_table.py    # Kademlia 路由表（asyncio.Lock 保护）
│   │   └── utils.py            # 工具函数：ID 生成、XOR 距离、节点编解码
│   ├── metadata/
│   │   ├── fetcher.py          # 元数据抓取 worker：去重、多 peer 重试、并发控制
│   │   └── bep9.py             # BEP-9 协议实现：TCP 握手、分片请求、SHA1 校验
│   ├── tracker/
│   │   ├── udp_tracker.py      # UDP Tracker 客户端（BEP-15）：connect + announce
│   │   └── worker.py           # Tracker 反查 worker：查询 peer → 投递 metadata_queue
│   └── storage/
│       └── mongodb.py          # MongoDB 存储层：批量写入、路由表持久化
├── intelligence/               # 智能查询层（Claude API Agent）
│   ├── app.py                  # FastAPI 入口
│   ├── agents/                 # Agent 编排、工具定义
│   ├── db/                     # 数据库查询封装
│   └── rag/                    # 向量检索
├── logs/                       # 运行日志
└── .env                        # 环境变量配置
```

---

## 数据库结构（MongoDB）

数据库名：`dht`

| Collection | 说明 |
|---|---|
| `info_hashs` | 采集到的 info_hash 记录（来源、时间戳） |
| `rtables` | 各节点路由表快照，用于重启恢复 |
| `bt_infos` | 解析后的种子元数据（名称、文件列表、大小、磁力链接） |

---

## 依赖

- Python 3.11+
- [bencodepy](https://pypi.org/project/bencodepy/) — Bencode 编解码
- [pymongo](https://pypi.org/project/pymongo/) — MongoDB 驱动
- [python-dotenv](https://pypi.org/project/python-dotenv/) — 环境变量加载
- MongoDB 服务

安装依赖：

```bash
pip install bencodepy pymongo python-dotenv
```

---

## 使用方法

```bash
# 启动 MongoDB
mongod --dbpath /usr/local/var/mongodb --fork --logpath /usr/local/var/log/mongodb/mongo.log

# 启动爬虫（采集 info_hash + 抓取元数据，一步完成）
python3 -m crawler.main
```

---

## 配置说明（config.py / .env）

| 参数 | 默认值 | 说明 |
|---|---|---|
| `DHT_NODE_NUM` | `8` | 并发 DHT 节点数 |
| `DHT_PORT` | `6881` | 起始监听端口（多节点自动递增） |
| `FIND_NODE_INTERVAL` | `1.0` | find_node 探测间隔（秒） |
| `FIND_NODE_SAMPLE` | `200` | 每轮 find_node 采样节点数 |
| `SAMPLE_INTERVAL` | `5.0` | BEP-51 sample_infohashes 间隔（秒） |
| `SAMPLE_BATCH` | `50` | 每轮 BEP-51 采样节点数 |
| `METADATA_CONCURRENCY` | `200` | BEP-9 元数据抓取并发数 |
| `FETCH_TIMEOUT` | `8` | BEP-9 / Tracker 请求超时（秒） |
| `TRACKER_CONCURRENCY` | `50` | UDP Tracker 并发查询数 |
| `NODE_MAX_AGE` | `900` | 节点最大存活时间（秒） |
| `MONGO_HOST` | `127.0.0.1` | MongoDB 地址 |
| `MONGO_PORT` | `27017` | MongoDB 端口 |

所有参数均可通过 `.env` 文件或环境变量覆盖。
