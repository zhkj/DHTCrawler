# DHTCrawler

一个基于 BitTorrent DHT 协议的 Python 爬虫，通过伪装成 DHT 节点被动监听网络中的 `info_hash`，再获取对应的种子元数据。

---

## 功能

- **DHT 网络嗅探**：伪装成合法 DHT 节点，加入 BitTorrent DHT 网络，被动收集其他节点广播的 `info_hash`
- **双渠道采集**：同时捕获 `announce_peer`（节点宣布下载某 torrent）和 `get_peers`（节点查询某 torrent 的 peers）两类消息中的 `info_hash`
- **路由表持久化**：将 DHT 路由表存储到 MongoDB，重启后可恢复节点状态，无需重新 bootstrap
- **种子元数据解析**：根据收集到的 `info_hash`，从外部 torrent 缓存服务下载 `.torrent` 文件，解析出种子名称、文件列表、文件大小、磁力链接等信息
- **多节点并发**：支持同时运行多个 DHT 节点，提高 `info_hash` 采集速度

---

## 工作原理

### 1. DHT 网络与 Kademlia 算法

BitTorrent DHT 网络基于 **Kademlia** 分布式哈希表算法。网络中每个节点拥有一个 160 位的唯一 Node ID，节点之间的"距离"通过 **XOR 运算**计算：

```
distance(A, B) = A XOR B
```

每个节点维护一张**路由表（Routing Table）**，由 160 个 k-bucket 组成，第 `i` 个 bucket 存储与自身 XOR 距离在 `[2^i, 2^(i+1))` 范围内的节点信息（IP + 端口 + Node ID）。

### 2. KRPC 协议

DHT 节点间通过 **KRPC（Kademlia Remote Procedure Call）** 通信，使用 UDP 传输，消息以 **Bencode** 编码。共有四种消息类型：

| 消息类型 | 方向 | 说明 |
|---|---|---|
| `ping` | 查询/响应 | 探测节点是否在线 |
| `find_node` | 查询/响应 | 查找离目标 ID 最近的 K 个节点 |
| `get_peers` | 查询/响应 | 查询拥有某 `info_hash` 的 peers |
| `announce_peer` | 查询/响应 | 宣告自己正在下载某 `info_hash` 的 torrent |

### 3. 爬虫工作流程

```
Bootstrap 节点 (router.bittorrent.com 等)
        │
        ▼
  发送 find_node 查询
        │
        ▼
  获取邻近节点列表 ──────► 加入路由表
        │                      │
        │                      ▼
        │              持续向路由表中的节点
        │              发送 find_node，扩大路由表
        │
        ▼
  被动接收其他节点的查询
        │
        ├── 收到 announce_peer ──► 提取 info_hash ──► 存入 MongoDB
        │
        └── 收到 get_peers    ──► 提取 info_hash ──► 存入 MongoDB
```

**关键设计**：爬虫不主动发起 `get_peers`，而是"混入"DHT 网络后，等待其他真实节点将查询/宣告消息发给自己，从而被动、低噪地采集 `info_hash`。

### 4. 种子元数据获取（bt.py）

拿到 `info_hash` 后，`bt.py` 依次尝试以下缓存服务获取 `.torrent` 文件：

1. `http://torcache.net/torrent/<BTIH>.torrent`
2. `http://bt.box.n0808.com/<prefix>/<suffix>/<BTIH>.torrent`

下载到 `.torrent` 文件后，通过 Bencode 解码提取：

- 种子名称（`name`）
- 文件列表（`files`）及各文件大小
- 对应的磁力链接（`magnet:?xt=urn:btih:<BTIH>`）

最终将元数据写入 MongoDB 的 `bt_infos` 集合。

---

## 项目结构

```
DHTCrawler/
├── dhtcrawler.py   # 入口：启动多个 DHT 节点
├── node.py         # Node 类：封装节点 ID 和协议实例
├── krpc.py         # 核心：KRPC 协议实现（路由表、消息处理、find_node 主动探测）
├── bt.py           # 种子元数据解析：根据 info_hash 获取 .torrent 并解析
├── dbconnect.py    # MongoDB 数据访问层
├── utility.py      # 工具函数：节点 ID 生成、XOR 距离、节点编解码
└── config.py       # 配置：节点数量、Bootstrap 节点、MongoDB 地址
```

---

## 数据库结构（MongoDB）

数据库名：`dhtcrawler`

| Collection | 说明 |
|---|---|
| `info_hashs` | 从 `announce_peer` 收集的 info_hash（含时间戳）|
| `get_peer_info_hashs` | 从 `get_peers` 收集的 info_hash（含时间戳）|
| `rtables` | 各节点路由表快照，用于重启恢复 |
| `bt_infos` | 解析后的种子元数据（名称、文件列表、磁力链接）|

---

## 依赖

- Python 2.x
- [bencode](https://pypi.org/project/bencode/) — Bencode 编解码
- [pymongo](https://pypi.org/project/pymongo/) — MongoDB 驱动
- MongoDB（本地默认端口 `27017`）

安装依赖：

```bash
pip install bencode pymongo
```

---

## 使用方法

**第一步：启动 DHT 爬虫节点，收集 info_hash**

```bash
python dhtcrawler.py
```

节点启动后会自动 bootstrap 并持续运行，采集到的 `info_hash` 写入 MongoDB。

**第二步：解析种子元数据**

```bash
python bt.py
```

读取 MongoDB 中的 `info_hash`，从外部服务获取 `.torrent` 文件并解析，结果存入 `bt_infos` 集合。

---

## 配置说明（config.py）

| 参数 | 默认值 | 说明 |
|---|---|---|
| `NODE_NUM` | `1` | 同时运行的 DHT 节点数量 |
| `INITIAL_NODES` | BitTorrent 官方 Bootstrap 节点 | DHT 网络入口节点 |
| `HOST` | `127.0.0.1` | MongoDB 地址 |
| `PORT` | `27017` | MongoDB 端口 |
