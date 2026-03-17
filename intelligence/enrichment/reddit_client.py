"""
Reddit 公开 JSON 接口 — 无需 API Key，无需注册 App。
使用 old.reddit.com 端点，兼容性更好。
"""
import logging
import httpx

logger = logging.getLogger("intelligence.enrichment.reddit")

# 模拟浏览器 User-Agent，避免被 Reddit 403 拦截
_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)


def search_reddit(query: str, subreddit: str = "all", limit: int = 5) -> list[dict]:
    """
    搜索 Reddit。
    使用 old.reddit.com 公开搜索接口，不需要 OAuth。
    """
    url = f"https://old.reddit.com/r/{subreddit}/search.json"
    headers = {
        "User-Agent": _USER_AGENT,
        "Accept": "application/json",
    }
    params = {
        "q": query,
        "sort": "relevance",
        "t": "week",
        "limit": limit,
        "restrict_sr": subreddit != "all",
    }

    try:
        resp = httpx.get(url, headers=headers, params=params, timeout=15,
                         follow_redirects=True)
        resp.raise_for_status()
        posts = resp.json().get("data", {}).get("children", [])
    except Exception as e:
        logger.warning(f"请求失败: {e}")
        return []

    results = []
    for post in posts:
        d = post["data"]
        results.append({
            "source": "reddit",
            "title": d.get("title", ""),
            "url": f"https://reddit.com{d.get('permalink', '')}",
            "subreddit": d.get("subreddit", ""),
            "score": d.get("score", 0),
            "comments": d.get("num_comments", 0),
            "created_at": str(d.get("created_utc", "")),
            "selftext": d.get("selftext", "")[:300],  # 帖子正文摘要
        })

    return results


if __name__ == "__main__":
    results = search_reddit("software leak", limit=3)
    for r in results:
        print(r["title"], r["url"])
