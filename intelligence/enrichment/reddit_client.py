"""
Reddit 公开 JSON 接口 — 无需 API Key，无需注册 App。
Reddit 允许直接访问 /search.json，只需设置合理的 User-Agent。
"""
import httpx

# Reddit 要求 User-Agent 格式：<platform>:<app_id>:<version> (by /u/<username>)
# 填任意合理字符串即可，不能用 "python-requests" 这类默认值
_USER_AGENT = "dht-intelligence-bot/0.1 (research project)"


def search_reddit(query: str, subreddit: str = "all", limit: int = 5) -> list[dict]:
    """
    搜索 Reddit。
    不需要 OAuth，直接用公开搜索接口（有速率限制但够用）。
    """
    url = f"https://www.reddit.com/r/{subreddit}/search.json"
    headers = {"User-Agent": _USER_AGENT}
    params = {
        "q": query,
        "sort": "relevance",
        "t": "week",
        "limit": limit,
        "restrict_sr": subreddit != "all",
    }

    try:
        resp = httpx.get(url, headers=headers, params=params, timeout=10)
        resp.raise_for_status()
        posts = resp.json().get("data", {}).get("children", [])
    except Exception as e:
        print(f"[Reddit] 请求失败: {e}")
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
