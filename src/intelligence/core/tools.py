"""Agent 工具集定义 + 执行器。"""
import json
import re

from intelligence.db import get_recent_torrents, get_torrent_by_hash
from intelligence.enrichment import search_hackernews, search_reddit, search_rss
from intelligence.rag.vectorstore import search as rag_search

# ── 内容清洗 ──────────────────────────────────────────────────────
# NSFW:Not Safe For Work
_NSFW_PATTERNS = re.compile(
    r'xxx|porn|hentai|sex|nude|erotic|adult|fetish|orgasm'
    r'|milf|anal|blowjob|creampie|gangbang|threesome|lesbian'
    r'|brazzers|bangbros|realitykings|naughtyamerica|hotandmean'
    r'|onlyfans|playboy|penthouse|hustler',
    re.IGNORECASE,
)

_MAX_TOOL_RESULT_CHARS = 3000


def _sanitize_results(results: list[dict]) -> list[dict]:
    cleaned = []
    for r in results:
        name = r.get("name", "") or r.get("title", "")
        if _NSFW_PATTERNS.search(name):
            continue
        if name.count('\ufffd') > 2:
            continue
        cleaned.append(r)
    return cleaned


def _slim_torrent(torrent: dict) -> dict:
    files = torrent.get("files", [])
    file_names = []
    for f in files[:5]:
        if isinstance(f, dict):
            file_names.append(f.get("path", str(f))[:80])
        elif isinstance(f, list):
            file_names.append(str(f[0])[:80] if f else "")
        else:
            file_names.append(str(f)[:80])
    slim = {
        "info_hash": torrent.get("info_hash", ""),
        "name": torrent.get("name", ""),
        "date": str(torrent.get("date", "")),
        "file_count": len(files),
        "sample_files": file_names,
    }
    if "magnet" in torrent:
        slim["magnet"] = torrent["magnet"]
    if "relevance" in torrent:
        slim["relevance"] = torrent["relevance"]
    return slim


def _truncate(text: str) -> str:
    if len(text) <= _MAX_TOOL_RESULT_CHARS:
        return text
    return text[:_MAX_TOOL_RESULT_CHARS] + '... [结果已截断]'


# ── Tool 定义（OpenAI function calling 格式） ────────────────────

TOOLS_SCHEMA = [
    {
        "type": "function",
        "function": {
            "name": "search_dht",
            "description": "在 DHT 数据库中语义搜索种子，适合回答'有没有关于 xxx 的内容'类问题",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "搜索关键词或描述"},
                    "top_k": {"type": "integer", "description": "返回结果数量，默认 5"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_torrent_detail",
            "description": "根据 info_hash 查询某个种子的详细信息",
            "parameters": {
                "type": "object",
                "properties": {
                    "info_hash": {
                        "type": "string",
                        "description": "种子的 info_hash（40位十六进制）",
                    },
                },
                "required": ["info_hash"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_hackernews",
            "description": "在 HackerNews 上搜索相关讨论，获取技术社区对某事件的看法",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "搜索关键词"},
                    "days": {"type": "integer", "description": "搜索最近几天，默认 7"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_reddit",
            "description": "在 Reddit 上搜索相关帖子，获取社区讨论和用户反应",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "搜索关键词"},
                    "subreddit": {"type": "string", "description": "指定子版块，默认 all"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_news",
            "description": "从科技新闻 RSS 源搜索相关报道",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "搜索关键词"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_trending",
            "description": "获取最近 DHT 网络中新出现的种子列表",
            "parameters": {
                "type": "object",
                "properties": {
                    "limit": {"type": "integer", "description": "返回数量，默认 10"},
                },
            },
        },
    },
]


# ── Tool 执行器 ────────────────────────────────────────────────

def execute_tool(tool_name: str, tool_input: dict) -> str:
    try:
        if tool_name == "search_dht":
            results = rag_search(tool_input["query"], tool_input.get("top_k", 5))
            results = _sanitize_results(results)
            return _truncate(json.dumps(results, ensure_ascii=False))

        elif tool_name == "get_torrent_detail":
            result = get_torrent_by_hash(tool_input["info_hash"])
            if result is None:
                return json.dumps({"error": "未找到该 info_hash"})
            if _NSFW_PATTERNS.search(result.get("name", "")):
                return json.dumps({"error": "该记录内容不适合展示"})
            result = _slim_torrent(result)
            return _truncate(json.dumps(result, ensure_ascii=False, default=str))

        elif tool_name == "search_hackernews":
            results = search_hackernews(tool_input["query"], tool_input.get("days", 7))
            return _truncate(json.dumps(results, ensure_ascii=False))

        elif tool_name == "search_reddit":
            results = search_reddit(tool_input["query"], tool_input.get("subreddit", "all"))
            return _truncate(json.dumps(results, ensure_ascii=False))

        elif tool_name == "search_news":
            results = search_rss(tool_input["query"])
            return _truncate(json.dumps(results, ensure_ascii=False))

        elif tool_name == "get_trending":
            results = get_recent_torrents(limit=tool_input.get("limit", 10))
            results = _sanitize_results(results)
            results = [_slim_torrent(r) for r in results]
            return _truncate(json.dumps(results, ensure_ascii=False, default=str))

        else:
            return json.dumps({"error": f"未知工具: {tool_name}"})

    except Exception as e:
        return json.dumps({"error": str(e)})
