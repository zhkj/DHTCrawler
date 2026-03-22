"""HackerNews Algolia API — 免费，无需 API Key。"""
import logging
from datetime import datetime, timedelta

import httpx

logger = logging.getLogger("intelligence.enrichment.hn")

HN_API = "https://hn.algolia.com/api/v1"


def search_hackernews(query: str, days: int = 7, limit: int = 5) -> list[dict]:
    since_ts = int((datetime.now() - timedelta(days=days)).timestamp())
    params = {
        "query": query,
        "tags": "(story,comment)",
        "numericFilters": f"created_at_i>{since_ts}",
        "hitsPerPage": limit,
    }

    try:
        resp = httpx.get(f"{HN_API}/search", params=params, timeout=10)
        resp.raise_for_status()
        hits = resp.json().get("hits", [])
    except Exception as e:
        logger.warning(f"请求失败: {e}")
        return []

    return [
        {
            "source": "hackernews",
            "title": hit.get("title") or hit.get("comment_text", "")[:100],
            "url": hit.get("url")
                   or f"https://news.ycombinator.com/item?id={hit.get('objectID')}",
            "score": hit.get("points", 0),
            "comments": hit.get("num_comments", 0),
            "created_at": hit.get("created_at", ""),
            "author": hit.get("author", ""),
        }
        for hit in hits
    ]
