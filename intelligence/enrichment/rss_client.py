"""
RSS 新闻聚合 — 完全免费，无需 API Key
"""
import feedparser
import httpx
from datetime import datetime


# 科技新闻源（可自由增减）
RSS_FEEDS = {
    "hackernews_top": "https://news.ycombinator.com/rss",
    "techcrunch":     "https://techcrunch.com/feed/",
    "theverge":       "https://www.theverge.com/rss/index.xml",
    "wired":          "https://www.wired.com/feed/rss",
    "bleepingcomputer": "https://www.bleepingcomputer.com/feed/",  # 安全新闻
}


def search_rss(query: str, sources: list[str] = None, limit: int = 5) -> list[dict]:
    """
    从 RSS 源中搜索包含关键词的文章。
    query 支持多词（空格分隔），取 AND 逻辑。
    """
    feeds = {k: v for k, v in RSS_FEEDS.items() if sources is None or k in sources}
    keywords = query.lower().split()
    results = []

    for source_name, feed_url in feeds.items():
        try:
            feed = feedparser.parse(feed_url)
        except Exception as e:
            print(f"[RSS] {source_name} 解析失败: {e}")
            continue

        for entry in feed.entries:
            text = (entry.get("title", "") + " " + entry.get("summary", "")).lower()
            if all(kw in text for kw in keywords):
                results.append({
                    "source": source_name,
                    "title": entry.get("title", ""),
                    "url": entry.get("link", ""),
                    "summary": entry.get("summary", "")[:300],
                    "published": entry.get("published", ""),
                })
                if len(results) >= limit:
                    return results

    return results


if __name__ == "__main__":
    results = search_rss("data breach leak")
    for r in results:
        print(r["source"], r["title"])
