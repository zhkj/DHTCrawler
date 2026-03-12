"""
Agent 工具集定义
每个函数对应 Claude function calling 的一个 tool。
"""
import json
from db.mongo_client import get_torrent_by_hash, get_recent_torrents
from rag.vectorstore import search as rag_search
from enrichment.hn_client import search_hackernews
from enrichment.reddit_client import search_reddit
from enrichment.rss_client import search_rss


# ── Tool 定义（传给 Claude API 的 schema） ──────────────────────────

TOOLS = [
    {
        "name": "search_dht",
        "description": "在 DHT 数据库中语义搜索种子，适合回答'有没有关于 xxx 的内容'类问题",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "搜索关键词或描述"},
                "top_k": {"type": "integer", "description": "返回结果数量，默认 5", "default": 5},
            },
            "required": ["query"],
        },
    },
    {
        "name": "get_torrent_detail",
        "description": "根据 info_hash 查询某个种子的详细信息",
        "input_schema": {
            "type": "object",
            "properties": {
                "info_hash": {"type": "string", "description": "种子的 info_hash（40位十六进制）"},
            },
            "required": ["info_hash"],
        },
    },
    {
        "name": "search_hackernews",
        "description": "在 HackerNews 上搜索相关讨论，获取技术社区对某事件的看法",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "搜索关键词"},
                "days": {"type": "integer", "description": "搜索最近几天，默认 7", "default": 7},
            },
            "required": ["query"],
        },
    },
    {
        "name": "search_reddit",
        "description": "在 Reddit 上搜索相关帖子，获取社区讨论和用户反应",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "搜索关键词"},
                "subreddit": {"type": "string", "description": "指定子版块，默认 all", "default": "all"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "search_news",
        "description": "从科技新闻 RSS 源搜索相关报道",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "搜索关键词"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "get_trending",
        "description": "获取最近 DHT 网络中新出现的种子列表，用于回答'最近有什么动态'类问题",
        "input_schema": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "description": "返回数量，默认 10", "default": 10},
            },
        },
    },
]


# ── Tool 执行器 ────────────────────────────────────────────────────

def execute_tool(tool_name: str, tool_input: dict) -> str:
    """
    根据工具名称调用对应函数，返回 JSON 字符串结果。
    Orchestrator 在 ReAct 循环中调用此函数。
    """
    try:
        if tool_name == "search_dht":
            results = rag_search(tool_input["query"], tool_input.get("top_k", 5))
            return json.dumps(results, ensure_ascii=False)

        elif tool_name == "get_torrent_detail":
            result = get_torrent_by_hash(tool_input["info_hash"])
            if result is None:
                return json.dumps({"error": "未找到该 info_hash"})
            return json.dumps(result, ensure_ascii=False, default=str)

        elif tool_name == "search_hackernews":
            results = search_hackernews(tool_input["query"], tool_input.get("days", 7))
            return json.dumps(results, ensure_ascii=False)

        elif tool_name == "search_reddit":
            results = search_reddit(tool_input["query"], tool_input.get("subreddit", "all"))
            return json.dumps(results, ensure_ascii=False)

        elif tool_name == "search_news":
            results = search_rss(tool_input["query"])
            return json.dumps(results, ensure_ascii=False)

        elif tool_name == "get_trending":
            results = get_recent_torrents(limit=tool_input.get("limit", 10))
            return json.dumps(results, ensure_ascii=False, default=str)

        else:
            return json.dumps({"error": f"未知工具: {tool_name}"})

    except Exception as e:
        return json.dumps({"error": str(e)})
