# DHT 融合情报系统设计文档

## 系统定位

**DHT 网络作为线索触发器，外部数据源（社交媒体、新闻、论坛）作为内容补充，通过 Agent 将两者融合，为用户提供"某类内容正在发生什么"的完整情报视图。**

DHT 擅长发现"某件事正在发生"（内容出现、传播），外部数据源擅长解释"这件事是什么、人们怎么看"。二者结合才能形成完整情报。

---

## 用户用例（User Stories）

### 用例 1：发现今日值得关注的 DHT 事件
```
用户："今天 DHT 上有什么值得关注的内容？"

系统做了什么：
  1. 扫描过去 24 小时新增的 info_hash
  2. 按文件名关键词识别"有信号"的种子（含 leak/internal/crack/confidential 等）
  3. 对每条信号去 Reddit/HackerNews/新闻源 搜索相关讨论
  4. 汇总成摘要返回

用户看到：
  - "发现 3 条疑似软件泄露信号，其中 AutoCAD 2026 Internal Build 在 Reddit 上已有讨论"
  - "发现 1 条纪录片在多个地区节点快速传播，目前暂无主流媒体报道"
```

### 用例 2：跟踪特定实体的全网动态
```
用户："帮我追踪一下 OpenAI 相关的内容，DHT 上有没有什么动静，外面怎么说"

系统做了什么：
  1. 在 DHT 历史数据中搜索含 "OpenAI" 的种子名称
  2. 实时监听后续出现的相关 info_hash
  3. 并发抓取 Twitter/Reddit/HN/新闻 关于 OpenAI 近期讨论
  4. 将 DHT 信号与外部讨论做时间轴对齐，发现关联

用户看到：
  - DHT 侧："3 天前出现一个 'OpenAI_Internal_Evals_2024.zip'，节点数快速增长"
  - 社媒侧："Reddit 上同期有帖子讨论该文件内容，HN 有相关评论"
  - 关联分析："DHT 信号比 HN 讨论早出现约 6 小时"
```

### 用例 3：调查某个 info_hash 的完整背景
```
用户："这个 hash：a3f2b1... 是什么来的？背景是什么？"

系统做了什么：
  1. 在 MongoDB 查询该 hash 的元数据（文件名、文件列表、首次出现时间）
  2. 提取文件名中的实体（软件名、公司名、版本号）
  3. 去新闻/社媒搜索相关实体的近期事件
  4. 综合生成背景报告

用户看到：
  完整报告："该种子包含 xxx 公司内部工具，文件列表显示...
             首次出现于 2024-11-03，同期 The Verge 有报道称该公司...
             Reddit 上有用户讨论该文件的真实性..."
```

### 用例 4：设置关键词监控告警
```
用户："帮我盯着 Apple 相关的泄露，有了告诉我"

系统做了什么：
  1. 将告警规则存入长期记忆（关键词 + 用户偏好）
  2. Monitor Agent 持续监听 DHT 新增 info_hash
  3. 命中时触发 Enrichment Agent 抓取外部数据
  4. 推送告警（带完整上下文）

用户收到：
  "发现新信号：'Apple_iPhone17_CAD_Files_Leak.torrent'
   外部情况：Twitter 上已有 3 个账号转发讨论，MacRumors 尚未报道
   初步判断：真实性待验证，传播速度较快"
```

### 用例 5：趋势分析与周报
```
用户："给我生成上周的 DHT 情报周报"

系统做了什么：
  1. 汇总上周所有采集的 info_hash，按类别分类（软件/影视/文档/可疑内容）
  2. 识别传播最广、增长最快的内容
  3. 对热点内容逐一补充外部来源的背景
  4. 生成结构化报告

用户看到：
  - 本周热点事件 TOP 5
  - 新兴趋势（某类内容正在快速增长）
  - 值得深入调查的异常信号
```

### 用例 6：多轮追问（上下文对话）
```
用户："上周软件泄露里有没有安全相关的？"
系统：返回 3 条结果

用户："第二条详细说说，外面怎么反应的？"
系统：记住上下文，深入分析第二条，无需用户重复提供 hash

用户："类似的事件历史上发生过几次？"
系统：跨越本次对话，查询历史数据库中同类事件
```

---

## 系统架构

```
┌─────────────────────────────────────────────────────────────────┐
│                          用户交互层                              │
│              Web UI / CLI  (FastAPI + WebSocket)                 │
└───────────────────────────┬─────────────────────────────────────┘
                            │ 自然语言输入
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│                      Orchestrator Agent                          │
│   意图识别 → 任务拆解 → 路由到子 Agent → 聚合结果 → 生成回复     │
└──────┬──────────┬───────────────┬──────────────┬────────────────┘
       │          │               │              │
       ▼          ▼               ▼              ▼
  ┌─────────┐ ┌─────────┐ ┌──────────┐ ┌──────────────┐
  │ Search  │ │ Monitor │ │Enrichment│ │  Analyst     │
  │  Agent  │ │  Agent  │ │  Agent   │ │  Agent       │
  │(检索)   │ │(监控)   │ │(信息补全)│ │(分析/报告)   │
  └────┬────┘ └────┬────┘ └────┬─────┘ └──────┬───────┘
       │           │           │              │
       └───────────┴───────────┴──────────────┘
                            │
                    ┌───────▼────────┐
                    │   Tool Layer   │
                    └───────┬────────┘
                            │
          ┌─────────────────┼──────────────────┐
          ▼                 ▼                  ▼
  ┌──────────────┐  ┌──────────────┐  ┌───────────────┐
  │  DHT 数据层  │  │  外部数据层  │  │   记忆层      │
  │  MongoDB     │  │  社媒/新闻   │  │Redis + MongoDB│
  │  Vector DB   │  │  API 聚合    │  │  + Vector DB  │
  └──────────────┘  └──────────────┘  └───────────────┘
          ▲
  ┌───────┴──────┐
  │ DHT Crawler  │  ← 持续运行的底层数据采集（现有项目）
  └──────────────┘
```

---

## 数据流全图

```
[DHT 网络]
    │  announce_peer / get_peers
    ▼
[DHT Crawler]  ──→  MongoDB
    │               info_hashs
    │               get_peer_info_hashs
    │               bt_infos
    │
    │   新增 info_hash 事件
    ▼
[Trigger Detection]  ──→  命中关键词规则? ──→ 是 ──→ [Enrichment Agent]
    │                                                       │
    │ 否（普通记录）                           抓取外部数据 ↓
    │                                     Reddit / HN / Twitter
    ▼                                     NewsAPI / RSS
[Vector Embedding]  ←──────────────────── 结构化摘要
    │  种子元数据 + 外部摘要 → Embedding
    ▼
[Vector DB]  ─────────────────────────── 支持 RAG 检索
    │
    ▼
[Agent 层]  ←── 用户查询
    │
    ▼
[响应生成]  ──→  用户
```

---

## 各模块详解

### 模块 1：DHT 采集层（现有）

**职责**：持续采集 info_hash 和种子元数据，存入 MongoDB

**不需要改动，直接复用**

**输出数据结构**：
```json
{
  "info_hash": "a3f2b1c4...",
  "name": "AutoCAD_2026_Internal_Build_Leak.zip",
  "files": ["setup.exe", "crack/keygen.exe", "readme.txt"],
  "size": 2048000000,
  "discovered_at": "2024-11-03T14:22:00Z",
  "node_ips": ["1.2.3.4", "5.6.7.8"]
}
```

---

### 模块 2：Trigger Detection（触发检测）

**职责**：对新增 info_hash 的文件名做规则匹配，识别"有情报价值"的信号

**Agent 能力**：Tool Use — 调用分类工具

**触发规则示例**：
```python
SIGNAL_KEYWORDS = {
    "leak":      ["leak", "internal", "confidential", "unreleased", "private"],
    "crack":     ["crack", "keygen", "patch", "activator", "bypass"],
    "document":  [".pdf", ".docx", ".xlsx", "report", "whitepaper"],
    "malware":   ["trojan", "ransomware", "payload", "backdoor", "c2"],
}
```

**可选技术栈**：
- 简单规则：Python 正则 / 关键词匹配（够用）
- 进阶：用小型分类模型（`fasttext` 或 fine-tuned BERT）对文件名分类
- 实时触发：Redis Stream / Kafka 消费 MongoDB Change Stream

---

### 模块 3：Enrichment Agent（信息补全 Agent）

**职责**：拿到"有信号"的种子信息，去外部数据源抓取相关讨论和背景

**Agent 能力**：
- **Tool Use**：调用多个外部 API 工具
- **并发执行**：多个外部源同时抓取（LangGraph 的 parallel node）
- **结果合并**：将多源结果去重、整合成结构化摘要

**工具集**：
```python
tools = [
    search_reddit(query, subreddit=None, limit=10),
    search_hackernews(query, limit=5),
    search_news(query, sources=["techcrunch", "theverge"], days=7),
    search_twitter(query, limit=20),          # 可选，需 API
    fetch_webpage(url),                        # 抓取具体页面
]
```

**执行流程**：
```
输入：{"name": "AutoCAD_2026_Internal_Build_Leak.zip", "files": [...]}
  ↓
实体提取：["AutoCAD", "2026", "Internal Build", "Autodesk"]
  ↓
并发调用：
  ├─ search_reddit("AutoCAD 2026 leak")
  ├─ search_hackernews("Autodesk leak")
  └─ search_news("AutoCAD internal build 2026")
  ↓
结果整合 → 结构化摘要 → 存入 Vector DB
```

**可选技术栈**：
| 工具 | 方案 A（免费/简单） | 方案 B（完整） |
|---|---|---|
| Reddit | `praw` 库 | Reddit API (免费) |
| HackerNews | HN Algolia API（免费无需 key） | 同左 |
| 新闻 | RSS 解析（`feedparser`） | NewsAPI（免费 tier） |
| Twitter/X | 搜索结果爬取 | Twitter API v2（收费） |
| 网页抓取 | `httpx` + `BeautifulSoup` | Firecrawl / Jina Reader |

---

### 模块 4：RAG 模块（知识库检索）

**职责**：将所有采集到的 DHT 元数据 + 外部摘要向量化存储，支持语义检索

**Agent 能力**：RAG — 检索增强生成

**数据向量化内容**：
```python
# 每条记录的向量化文本
text = f"""
种子名称: {torrent['name']}
文件列表: {', '.join(torrent['files'][:10])}
外部摘要: {torrent['external_summary']}
发现时间: {torrent['discovered_at']}
"""
embedding = embed_model.encode(text)
vector_db.add(embedding, metadata=torrent)
```

**可选技术栈**：
| 组件 | 方案 A | 方案 B |
|---|---|---|
| Vector DB | ChromaDB（本地，零配置） | Pinecone / Weaviate（云端） |
| Embedding 模型 | `sentence-transformers/all-MiniLM-L6-v2`（免费） | OpenAI `text-embedding-3-small` |
| 中文支持 | `paraphrase-multilingual-MiniLM-L12-v2` | — |
| 重排序（Rerank） | `cross-encoder/ms-marco-MiniLM-L-6-v2` | Cohere Rerank API |

---

### 模块 5：Memory 层（记忆）

**职责**：维护用户的对话上下文、历史偏好、告警配置

**Agent 能力**：Memory — 短期 + 长期两级记忆

**短期记忆**（对话上下文）：
```python
# 滑动窗口 + 摘要压缩
class ShortTermMemory:
    def add(self, message): ...
    def get_context(self) -> list:
        if len(self.messages) > 20:
            summary = llm.summarize(self.messages[:-5])
            return [{"role": "system", "content": f"对话摘要: {summary}"}] \
                   + self.messages[-5:]
        return self.messages
```

**长期记忆**（用户偏好 + 告警规则，存 MongoDB）：
```json
{
  "user_id": "u001",
  "alert_keywords": ["Apple leak", "OpenAI internal"],
  "preferred_topics": ["cybersecurity", "AI"],
  "past_queries": [...],
  "last_active": "2024-11-10"
}
```

**可选技术栈**：
- 短期记忆：Python 内存 dict（简单）/ Redis（多会话）
- 长期记忆：MongoDB（复用现有）
- 记忆检索：ChromaDB（用向量相似度从历史查询中找相关记忆）

---

### 模块 6：Orchestrator Agent（主控 Agent）

**职责**：理解用户意图，拆解任务，调度子 Agent，聚合结果

**Agent 能力**：
- **意图分类**：判断是查询、监控配置还是分析请求
- **任务规划**：ReAct 模式 —— 思考 → 行动 → 观察 → 继续
- **子 Agent 路由**：根据意图调用对应 Agent
- **结果聚合**：将多个 Agent 结果合并成连贯回复

**意图路由逻辑**：
```python
intent_routing = {
    "查询/搜索"    → Search Agent + Enrichment Agent,
    "监控/告警"    → Monitor Agent（写入长期记忆）,
    "分析/报告"    → Analyst Agent,
    "调查某 hash"  → Search Agent + Enrichment Agent,
    "多轮追问"     → 结合 Memory 路由到对应 Agent,
}
```

**可选技术栈**：
| 方案 | 说明 | 适合场景 |
|---|---|---|
| LangGraph | 有向图定义 Agent 流程，可视化强 | 面试展示首选 |
| LangChain AgentExecutor | 成熟，文档丰富 | 快速原型 |
| 手写 ReAct 循环 | 最灵活，面试能讲清楚每一步 | 展示深度理解 |
| AutoGen | 微软出品，Multi-Agent 框架 | Multi-Agent 场景 |

---

### 模块 7：Monitor Agent（监控 Agent）

**职责**：后台持续运行，监听 DHT 新增数据，命中告警规则时触发 Enrichment 并推送通知

**Agent 能力**：
- **长期记忆读取**：加载用户配置的告警关键词
- **Tool Use**：调用 Enrichment Agent 工具
- **Human-in-the-Loop**（可选）：低置信度时请求用户确认

**执行流程**：
```
MongoDB Change Stream 监听新增 info_hash
    ↓
与用户告警关键词匹配
    ↓ 命中
Enrichment Agent 抓取外部数据
    ↓
置信度评分（LLM 判断相关性）
    ↓
高置信度 → 直接推送告警
低置信度 → Human-in-the-Loop：发给用户确认
```

---

### 模块 8：Analyst Agent（分析 Agent）

**职责**：执行趋势分析、周报生成、跨时间对比等需要聚合推理的任务

**Agent 能力**：
- **Tool Use**：统计查询工具（MongoDB aggregation）
- **Long Context 处理**：处理大量数据时的摘要策略
- **结构化输出**：生成 Markdown 报告 / JSON 结构

**工具集**：
```python
tools = [
    get_trending_hashes(time_range, top_k),       # 热门 hash 排行
    get_category_stats(category, time_range),      # 分类统计
    compare_periods(period_a, period_b),           # 时段对比
    get_geo_distribution(info_hash),               # IP 地理分布
    search_similar_events(event_description),      # 历史相似事件
]
```

---

## 技术栈总览

```
┌──────────────────────────────────────────────────────┐
│                    用户层                             │
│  FastAPI + Jinja2 模板  /  Streamlit（快速原型）      │
│  WebSocket（实时推送告警）                            │
└──────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────┐
│                    Agent 层                           │
│  LLM:       Claude API (claude-haiku-4-5 / sonnet)   │
│  框架:      LangGraph（推荐）/ 手写 ReAct             │
│  工具调用:  Function Calling                          │
└──────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────┐
│                    数据处理层                         │
│  Embedding: sentence-transformers（本地免费）         │
│  Vector DB: ChromaDB（本地）/ Pinecone（云）          │
│  实时触发:  MongoDB Change Stream / Redis Stream      │
└──────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────┐
│                    外部数据源                         │
│  Reddit:      praw（免费 API）                        │
│  HackerNews:  Algolia HN API（完全免费）              │
│  新闻:        feedparser RSS / NewsAPI               │
│  网页内容:    httpx + BeautifulSoup / Jina Reader     │
└──────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────┐
│                    存储层                             │
│  主数据库:   MongoDB（复用现有）                       │
│  短期记忆:   Redis / Python dict                      │
│  向量存储:   ChromaDB                                 │
└──────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────┐
│                    采集层（现有）                      │
│  DHT Crawler:  dhtcrawler.py（Python 2 → 建议升 3）  │
│  元数据解析:   bt.py                                  │
└──────────────────────────────────────────────────────┘
```

---

## Agent 能力分布总览

| 模块 | 用到的 Agent 能力 |
|---|---|
| Trigger Detection | Tool Use（规则匹配工具）|
| Enrichment Agent | Tool Use（多源 API）、并发执行、结果合并 |
| RAG 模块 | RAG（向量检索 + 重排序）|
| Memory 层 | Short-term Memory（滑动窗口/摘要）、Long-term Memory |
| Orchestrator | 意图理解、ReAct 规划、Multi-Agent 路由 |
| Monitor Agent | 长期记忆读取、Human-in-the-Loop、异步监控 |
| Analyst Agent | Tool Use、Long Context 处理、结构化输出 |
| 上下文管理 | 跨越全系统，实体追踪、多轮状态维护 |

---

## 推荐开发顺序

```
阶段 1（1-2 周）：数据管道打通
  ├─ DHT 数据 → MongoDB（已有）
  ├─ Enrichment 工具：HN API + Reddit API + RSS（免费，优先实现）
  └─ 手动测试：给定 hash → 能返回外部相关信息

阶段 2（1-2 周）：RAG + 基础 Agent
  ├─ 数据向量化存入 ChromaDB
  ├─ 单 Agent 实现：接受自然语言 → RAG 检索 → 生成回复
  └─ 上下文管理：多轮对话状态跟踪

阶段 3（1-2 周）：Multi-Agent 拆分
  ├─ Orchestrator + Search Agent + Analyst Agent
  ├─ LangGraph 定义 Agent 流程图
  └─ Tool Use：完整工具集接入

阶段 4（1 周）：Memory + Monitor
  ├─ 两级记忆（Redis 短期 + MongoDB 长期）
  ├─ Monitor Agent：MongoDB Change Stream + 告警推送
  └─ Human-in-the-Loop：低置信度事件请求确认

阶段 5（1 周）：演示打磨
  ├─ Web UI（Streamlit 最快）
  ├─ 准备 3-5 个典型 Demo 场景
  └─ 可观测性：打印 Agent 思考链路（方便面试讲解）
```

---

## 面试时的叙述框架

1. **项目独特性**：DHT 是真实网络行为数据，不是爬公开 API，有底层协议实现（Kademlia、KRPC）
2. **为什么要融合**：DHT 只有信号，没有解释；外部数据有解释，但错过早期信号——两者互补
3. **RAG 的必要性**：数据持续增长无上限，不能全塞 context，向量检索是唯一选择
4. **Multi-Agent 的设计权衡**：为什么不用单 Agent？各 Agent 职责边界如何划定？
5. **Memory 的取舍**：短期用摘要压缩，长期用向量检索，为什么不直接存全量历史？
6. **Human-in-the-Loop 的价值**：情报系统不能全自动，低置信度场景下人工介入的设计
7. **可以继续深挖的方向**：知识图谱、实时流处理、自适应调度——展示你知道边界在哪
