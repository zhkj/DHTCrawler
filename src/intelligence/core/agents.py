"""子 Agent 定义 — 按意图分类路由到不同执行策略。

Agent 路由：Orchestrator 根据意图分类选择执行策略
- 检索类 → SearchAgent: RAG + Enrichment 工具链
- 分析类 → AnalystAgent: 统计 + 趋势工具链
- 监控类 → MonitorAgent: Monitor 配置工具链
"""
import logging

logger = logging.getLogger("intelligence.core.agents")


class AgentProfile:
    """子 Agent 配置。"""

    def __init__(self, name: str, description: str, tools: list[str],
                 system_prompt_extra: str = ""):
        self.name = name
        self.description = description
        self.tools = tools
        self.system_prompt_extra = system_prompt_extra


# ── 预定义子 Agent ────────────────────────────────────────────────

SEARCH_AGENT = AgentProfile(
    name="SearchAgent",
    description="检索类任务：搜索 DHT 数据并从外部源补充信息",
    tools=["search_dht", "get_torrent_detail", "search_hackernews", "search_reddit", "search_news"],
    system_prompt_extra=(
        "你是一个专注于信息检索的 Agent。优先从 DHT 数据库搜索，"
        "然后用 HackerNews/Reddit/新闻补充背景信息。"
        "确保综合多个来源的信息给出完整答案。"
    ),
)

ANALYST_AGENT = AgentProfile(
    name="AnalystAgent",
    description="分析类任务：趋势分析、统计汇总、情报报告",
    tools=["get_trending", "search_dht", "search_hackernews", "search_reddit", "search_news"],
    system_prompt_extra=(
        "你是一个专注于数据分析的 Agent。先获取趋势数据，"
        "然后结合外部讨论进行综合分析。"
        "输出应包含数据支撑、趋势判断和行动建议。"
    ),
)

MONITOR_AGENT = AgentProfile(
    name="MonitorAgent",
    description="监控类任务：告警配置、监控查询",
    tools=["search_dht", "get_torrent_detail", "get_trending"],
    system_prompt_extra=(
        "你是一个专注于监控配置的 Agent。帮助用户设置关键词告警、"
        "查看监控状态、调整监控参数。"
    ),
)

# 所有可用 Agent
AGENT_REGISTRY: dict[str, AgentProfile] = {
    "search": SEARCH_AGENT,
    "analyst": ANALYST_AGENT,
    "monitor": MONITOR_AGENT,
}

# ── 意图分类关键词映射 ────────────────────────────────────────────

_INTENT_KEYWORDS = {
    "search": [
        "搜索", "查找", "有没有", "是否存在", "查询", "找",
        "search", "find", "look for", "泄露", "leak",
    ],
    "analyst": [
        "分析", "趋势", "报告", "摘要", "汇总", "统计", "情报",
        "analysis", "trend", "report", "summary", "动态", "概况",
    ],
    "monitor": [
        "监控", "告警", "通知", "设置", "配置", "关注",
        "monitor", "alert", "watch", "notify",
    ],
}


def classify_intent(query: str) -> str:
    """基于关键词的意图分类。

    Args:
        query: 用户输入查询。

    Returns:
        意图类别: "search" | "analyst" | "monitor"
    """
    query_lower = query.lower()
    scores = {intent: 0 for intent in _INTENT_KEYWORDS}

    for intent, keywords in _INTENT_KEYWORDS.items():
        for kw in keywords:
            if kw in query_lower:
                scores[intent] += 1

    best_intent = max(scores, key=scores.get)

    # 如果没有匹配到任何关键词，默认走 search
    if scores[best_intent] == 0:
        best_intent = "search"

    logger.info(f"意图分类 | query={query[:50]} intent={best_intent} scores={scores}")
    return best_intent


def get_agent(intent: str) -> AgentProfile:
    """根据意图获取对应的 Agent 配置。"""
    return AGENT_REGISTRY.get(intent, SEARCH_AGENT)
