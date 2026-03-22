"""Reddit 公开 JSON 接口 — 无需 API Key。"""
import logging

import httpx

logger = logging.getLogger("intelligence.enrichment.reddit")

_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)


def search_reddit(query: str, subreddit: str = "all", limit: int = 5) -> list[dict]:
    url = f"https://old.reddit.com/r/{subreddit}/search.json"
    headers = {"User-Agent": _USER_AGENT, "Accept": "application/json"}
    params = {
        "q": query, "sort": "relevance", "t": "week",
        "limit": limit, "restrict_sr": subreddit != "all",
    }

    try:
        resp = httpx.get(url, headers=headers, params=params, timeout=10,
                         follow_redirects=True)
        resp.raise_for_status()
        posts = resp.json().get("data", {}).get("children", [])
    except Exception as e:
        logger.warning(f"请求失败: {e}")
        return []

    return [
        {
            "source": "reddit",
            "title": d.get("title", ""),
            "url": f"https://reddit.com{d.get('permalink', '')}",
            "subreddit": d.get("subreddit", ""),
            "score": d.get("score", 0),
            "comments": d.get("num_comments", 0),
            "created_at": str(d.get("created_utc", "")),
            "selftext": d.get("selftext", "")[:300],
        }
        for post in posts
        for d in [post["data"]]
    ]
