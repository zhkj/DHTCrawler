# DHTCrawler Agent 应用设计文档

基于现有 DHT 爬虫项目，构建一个覆盖 Agent 应用各核心技术方向的智能分析平台，目标是在求职面试中展示完整的 Agent 工程能力。

---

## 整体定位：DHT 网络情报分析平台

用自然语言与 DHT 网络数据交互——搜索种子、分析趋势、监控特定内容，同时展示完整的 Agent 技术栈。

---

## 整体架构

```
用户 (自然语言)
      │
      ▼
┌─────────────────────────────────────┐
│         Orchestrator Agent          │  ← 主控 Agent，任务分发
└─────────────┬───────────────────────┘
              │
    ┌─────────┼──────────┐
    ▼         ▼          ▼
┌───────┐ ┌───────┐ ┌─────────┐
│Search │ │Analyst│ │Crawler  │  ← 多 Agent
│Agent  │ │Agent  │ │Agent    │
└───┬───┘ └───┬───┘ └────┬────┘
    │         │           │
    ▼         ▼           ▼
┌──────────────────────────────────┐
│           Tool Layer             │
│  search_db | get_stats | crawl_  │
│  control | alert_set | summarize │
└──────────────────────────────────┘
              │
    ┌─────────┼──────────┐
    ▼         ▼          ▼
┌───────┐ ┌───────┐ ┌─────────┐
│MongoDB│ │Vector │ │  Redis  │
│(原始  │ │  DB   │ │(短期    │
│ 数据) │ │(RAG)  │ │ 记忆)   │
└───────┘ └───────┘ └─────────┘
```

---

## 推荐技术栈

| 组件 | 推荐选择 | 理由 |
|---|---|---|
| LLM | Claude API (claude-haiku-4-5) | 成本低、工具调用强 |
| Agent 框架 | LangGraph 或手写 | LangGraph 面试中认可度高 |
| Vector DB | ChromaDB（本地）/ Pinecone（云） | ChromaDB 零配置适合演示 |
| Embedding | `sentence-transformers` | 免费、离线可用 |
| 短期记忆 | Redis 或内存 dict | 简单够用 |
| 长期记忆 | MongoDB（复用现有） | 与项目已有设施统一 |
| Web UI | FastAPI + 简单前端 | 演示友好 |

---

## 核心方向一：RAG — 种子语义搜索

### 原理
将 MongoDB 中采集到的种子名称、文件列表向量化，存入向量数据库，实现语义级别的内容检索（而非关键词匹配）。

### 实现思路

```python
# 数据流：MongoDB → Embedding → Vector DB
torrent = {"name": "Python Crash Course", "files": ["chapter1.pdf", ...]}
embedding = embed(torrent["name"] + " ".join(torrent["files"]))
vector_db.add(embedding, metadata=torrent)

# 检索时
results = vector_db.query("机器学习入门教程", top_k=10)
```

### 面试亮点
- chunk 策略的选择与权衡
- embedding 模型选择（多语言支持、中文种子名称处理）
- 相似度阈值调优与结果重排序（Rerank）

---

## 核心方向二：Memory — 两级记忆架构

### 架构设计

| 类型 | 存储 | 内容 | 场景 |
|---|---|---|---|
| **短期记忆** | Redis / 内存 | 当前对话上下文 | "上一条结果的详情" |
| **长期记忆** | MongoDB | 用户偏好、历史查询 | "记住我喜欢技术类资源" |

### 上下文压缩策略

```python
# 短期：滑动窗口 + 摘要压缩
if len(messages) > 20:
    summary = llm.summarize(messages[:-5])
    messages = [summary] + messages[-5:]
```

### 面试亮点
- 上下文窗口管理的不同策略（截断 vs 摘要 vs 压缩）
- 记忆的遗忘机制设计
- 长期记忆的检索与注入时机

---

## 核心方向三：上下文管理 — 对话状态跟踪

### 状态结构

```python
context = {
    "last_query": "Python 教程",
    "last_results": [...],       # 支持追问 "第二个的详情"
    "filters": {"type": "video"},
    "session_id": "abc123"
}
```

### 面试亮点
- 多轮对话中的实体追踪（"它"指代上一个结果）
- 如何在保持上下文的同时避免信息污染
- 对话状态的序列化与恢复

---

## 核心方向四：Multi-Agent — 三个专职 Agent

### 分工设计

**Crawler Agent**：控制爬虫运行状态
```
用户："暂停爬虫 / 查看今日采集量"
→ Crawler Agent 调用 crawl_control() 工具
```

**Search Agent**：RAG 检索 + 结果排序
```
用户："找一些机器学习相关的资源"
→ Search Agent 调用 semantic_search() + rerank()
```

**Analyst Agent**：数据分析 + 趋势洞察
```
用户："最近一周热门的内容类型是什么"
→ Analyst Agent 聚合 MongoDB 数据，生成报告
```

### Tool 工具集

```python
tools = [
    search_torrents(query, top_k),      # RAG 语义搜索
    get_network_stats(time_range),       # 网络统计
    get_trending(category, limit),       # 热门趋势
    set_alert(keyword, callback),        # 关键词监控告警
    control_crawler(action),            # 启停爬虫
    explain_infohash(hash),             # 查询某个 hash 的详情
]
```

### 面试亮点
- Agent 间通信与任务路由机制
- Orchestrator 如何拆解用户意图并分发任务
- 多 Agent 结果聚合策略

---

## 拓展方向一：可观测性与评估（Observability & Evaluation）

### 是什么
建立完整的 Agent 执行链路可视化系统，监控各 Agent 的性能指标、决策质量和数据质量，并将评估结果反馈给 Agent 做自适应调整。

### 如何结合本项目
- **DHT 查询链路追踪**：为每个 `find_node`、`get_peers`、`announce_peer` 请求添加 TraceID，追踪从节点查询到数据入库的完整路径
- **实时性能评估 Agent**：
  - 路由表填充效率（`add_nodes_to_rtable` 成功率）
  - info_hash 采集速率与去重率
  - BT 元数据解析成功率（torcache vs btbox 对比）
- **LLM-as-Judge**：用 LLM 对 Search Agent 的返回结果打分，评估相关性

```
Agent执行 → 链路日志 → 评估Agent打分 → 反馈调整策略
```

### 面试亮点
- OpenTelemetry + Prometheus 标准实现
- Evaluation-driven Adaptation：评估结果驱动 Agent 行为调整
- LLM 作为评估器的设计与局限性分析

---

## 拓展方向二：Human-in-the-Loop

### 是什么
在 Agent 决策的关键节点引入人工审查或确认，而非完全自动化，适用于高风险或低置信度的决策。

### 如何结合本项目
- **异常数据人工审查**：当爬虫发现异常（如高频重复 info_hash、疑似恶意节点）时，Agent 标记并推送人工确认
- **规则学习闭环**：
  ```
  Agent 采集 → 质量评分 → 低于阈值?
    ├─ 是 → 推送人工验证 → 反馈规则 → Agent 学习
    └─ 否 → 直接入库
  ```
- **交互式爬虫配置**：用户通过 Web UI 动态修改 `NODE_NUM`、采样频率等参数，Agent 实时应用并汇报效果

### 面试亮点
- 体现对"Agent 不应完全自主"的系统性理解
- 反馈学习循环（Feedback Loop）设计
- WebSocket 实时推送爬虫状态的前后端实现

---

## 拓展方向三：流式 / 实时处理

### 是什么
将当前的批量处理模式（积累 100 条再写库）改造为实时事件流，Agent 基于持续流入的数据做增量决策。

### 架构改造

```
DHT Node --(announce_peer)--> Kafka / Redis Stream
    ├→ Parser Agent     （立即异步获取 BT 元数据）
    ├→ Aggregator Agent （实时更新热点 info_hash 排行）
    └→ Anomaly Agent    （实时识别僵尸网络、恶意节点）

所有结果 → WebSocket → 实时 Dashboard
```

### 时间窗口决策示例

```python
# Agent 基于滑动窗口做决策
window_5min = get_events(last=300)
trending = counter(window_5min).most_common(10)
if trending[0].count > threshold:
    alert_agent.notify("发现异常热点内容")
```

### 面试亮点
- 从离线爬虫升级为实时系统的架构演进
- Kafka + Flink/Spark Streaming 大数据工程能力
- 多 Agent 并发消费与背压（Backpressure）处理

---

## 拓展方向四：知识图谱

### 是什么
将离散的爬虫数据（Node ID、info_hash、种子元数据）组织为结构化知识图谱，用 Agent 做关联分析、溯源和异常检测。

### 图谱结构

```
Node(ID, IP, Port)
  ├─ knows_node   → Node         （路由表关系）
  ├─ announces    → InfoHash     （宣告下载关系）
  └─ last_seen    → Timestamp

InfoHash
  ├─ has_file     → File         （BT 元数据）
  ├─ announced_by → Node[]       （来自哪些节点）
  └─ category     → Category     （通过文件名推断分类）
```

### Agent 推理任务
- **内容溯源 Agent**：给定 info_hash，查找发布节点、传播路径、首次出现时间
- **异常检测 Agent**：识别短时间内宣布相同哈希的节点集群（疑似僵尸网络）
- **热点发现 Agent**：通过图关系识别新兴热点内容及其来源

### 面试亮点
- 图数据库（Neo4j）+ Cypher 查询语言
- 图神经网络用于异常节点检测（进阶）
- 内容安全与网络分析的实际应用场景

---

## 拓展方向五：自适应资源调度 Agent

### 是什么
Agent 根据系统资源（CPU、内存、网络带宽）和任务优先级，动态调整爬虫策略与参数配置，实现成本最优的数据采集。

### 如何结合本项目
当前系统硬编码了关键参数（`NODE_NUM=1`、批量大小 `100`、查询间隔 `4s`），自适应 Agent 将这些变为动态决策：

```python
# Agent 持续监控并动态调整
resources = monitor.get()  # CPU, 内存, 网络延迟
if resources.cpu < 30% and resources.memory_free > 2GB:
    crawler.set_node_num(node_num + 1)   # 增加节点
if mongo.write_latency > 500ms:
    crawler.set_batch_size(batch_size * 2)  # 减少写频率
```

**数据源优先级动态评分**：
```
score(source) = 新增Node数 / 网络请求数
每小时重新评估 torcache vs btbox 的权重
```

### 面试亮点
- 强化学习（Q-Learning）优化调度策略（进阶方向）
- 成本-收益动态决策模型
- 自适应系统设计模式

---

## 各方向优先级与建议

| 优先级 | 方向 | 实现难度 | 面试价值 | 建议周期 |
|---|---|---|---|---|
| ★★★ | RAG 语义搜索 | 低 | 高 | Week 1 |
| ★★★ | Multi-Agent + Tool Use | 中 | 高 | Week 2 |
| ★★★ | Memory 两级架构 | 低 | 高 | Week 2 |
| ★★★ | 流式 / 实时处理 | 中 | 高 | Week 3 |
| ★★★ | 知识图谱 | 中 | 很高 | Week 4 |
| ★★ | 可观测性与评估 | 中 | 高 | Week 3 |
| ★★ | Human-in-the-Loop | 高 | 中 | Week 5 |
| ★ | 自适应资源调度 | 中 | 中 | Week 5 |

---

## 推荐开发路线

```
Week 1：RAG 基础
  MongoDB 数据 → Embedding → ChromaDB → 语义搜索接口

Week 2：单 Agent + Memory + Tool Use
  LLM + 工具调用 + 上下文管理 + 两级记忆

Week 3：Multi-Agent + 实时流
  拆分 Search / Analyst / Crawler Agent + Orchestrator
  引入 Kafka/Redis Stream 替换批量写入

Week 4：知识图谱
  Neo4j 建图 + 溯源/异常检测 Agent

Week 5：可观测性 + Human-in-the-Loop + 完善演示
  链路追踪 + Web UI + 典型 Demo 场景脚本
```

---

## 面试叙述逻辑

1. **项目背景**：从真实 DHT 网络采集数据，不是玩具数据集，有真实的数据管道
2. **为什么用 RAG**：种子数量百万级，无法塞进 context，需要语义检索
3. **Memory 的取舍**：短期用滑动窗口+摘要，长期存用户偏好，对比各策略优缺点
4. **Multi-Agent 的必要性**：爬虫控制、搜索、分析职责分离，各自独立扩展
5. **知识图谱的价值**：将离散数据关联成图，实现传统数据库无法做到的溯源和网络分析
6. **遇到的挑战**：中文种子名称的 embedding 质量、多轮对话的实体解析、实时流的背压处理
