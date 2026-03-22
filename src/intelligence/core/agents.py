"""子 Agent 定义 — 按意图分类路由到不同执行策略。

Agent 路由：Orchestrator 根据意图分类选择执行策略
- 检索类 → SearchAgent: RAG + Enrichment 工具链
- 分析类 → AnalystAgent: 统计 + 趋势工具链
- 监控类 → MonitorAgent: Monitor 配置工具链
"""
import logging

from intelligence.core.tools import TOOLS_SCHEMA

logger = logging.getLogger("intelligence.core.agents")


class AgentProfile:
    """子 Agent 配置。"""

    def __init__(self, name: str, description: str, tools: list[str],
                 system_prompt_extra: str = ""):
        self.name = name
        self.description = description
        self.tools = tools
        self.system_prompt_extra = system_prompt_extra

    def filter_tools_schema(self) -> list[dict]:
        """根据 Agent 的工具列表过滤 TOOLS_SCHEMA。

        只保留该 Agent 被授权使用的工具，实际限制 LLM 的工具选择。
        """
        return [
            tool for tool in TOOLS_SCHEMA
            if tool["function"]["name"] in self.tools
        ]


# ── 预定义子 Agent ────────────────────────────────────────────────

SEARCH_AGENT = AgentProfile(
    name="SearchAgent",
    description="检索类任务：搜索 DHT 数据并从外部源补充信息",
    tools=[
        "search_dht", "get_torrent_detail",
        "search_hackernews", "search_reddit", "search_news",
    ],
    system_prompt_extra=(
        "你是一个专注于信息检索的 Agent。优先从 DHT 数据库搜索，"
        "然后用 HackerNews/Reddit/新闻补充背景信息。"
        "确保综合多个来源的信息给出完整答案。"
    ),
)

ANALYST_AGENT = AgentProfile(
    name="AnalystAgent",
    description="分析类任务：趋势分析、统计汇总、情报报告",
    tools=[
        "get_trending", "search_dht",
        "search_hackernews", "search_reddit", "search_news",
    ],
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
    """基于关键词的意图分类，低置信度时回退 LLM。

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
    best_score = scores[best_intent]

    # 置信度判断：最高分为0或多个意图并列时，回退LLM
    sorted_scores = sorted(scores.values(), reverse=True)
    second_best = sorted_scores[1] if len(sorted_scores) > 1 else 0

    if best_score == 0 or (best_score > 0 and best_score == second_best):
        # 低置信度，尝试 LLM 分类
        llm_intent = _llm_classify_intent(query)
        if llm_intent:
            logger.info(
                f"意图分类 (LLM fallback) | query={query[:50]} "
                f"intent={llm_intent} keyword_scores={scores}"
            )
            return llm_intent

    if best_score == 0:
        best_intent = "search"

    logger.info(
        f"意图分类 | query={query[:50]} "
        f"intent={best_intent} scores={scores}"
    )
    return best_intent


def _llm_classify_intent(query: str) -> str | None:
    """LLM 意图分类兜底。"""
    try:
        from intelligence.config import LLM_MODEL
        from intelligence.core.llm_client import get_client

        client = get_client()
        resp = client.chat.completions.create(
            model=LLM_MODEL,
            max_tokens=20,
            temperature=0,
            messages=[{
                "role": "user",
                "content": (
                    f"将以下用户查询分类为一个类别（只输出类别名）：\n"
                    f"- search: 搜索、查找具体内容\n"
                    f"- analyst: 分析、趋势、报告、汇总\n"
                    f"- monitor: 监控、告警、通知配置\n\n"
                    f"查询：{query}\n类别："
                ),
            }],
        )
        result = resp.choices[0].message.content.strip().lower()
        if result in ("search", "analyst", "monitor"):
            return result
        return None
    except Exception:
        return None


def get_agent(intent: str) -> AgentProfile:
    """根据意图获取对应的 Agent 配置。"""
    return AGENT_REGISTRY.get(intent, SEARCH_AGENT)
