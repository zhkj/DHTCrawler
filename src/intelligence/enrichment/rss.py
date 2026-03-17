"""RSS 新闻聚合 — 中英文模糊匹配。"""
import re
import logging
from difflib import SequenceMatcher

import feedparser
import httpx

logger = logging.getLogger("intelligence.enrichment.rss")

RSS_FEEDS = {
    "hackernews_top":   "https://news.ycombinator.com/rss",
    "techcrunch":       "https://techcrunch.com/feed/",
    "theverge":         "https://www.theverge.com/rss/index.xml",
    "wired":            "https://www.wired.com/feed/rss",
    "bleepingcomputer": "https://www.bleepingcomputer.com/feed/",
    "solidot":          "https://www.solidot.org/index.rss",
    "ithome":           "https://www.ithome.com/rss/",
}

_FUZZY_THRESHOLD = 0.65


def _tokenize(text: str) -> list[str]:
    en_words = re.findall(r'[a-zA-Z0-9]+', text.lower())
    cn_chars = re.findall(r'[\u4e00-\u9fff]', text)
    return en_words + cn_chars


def _fuzzy_match(keyword: str, text: str) -> float:
    text_lower = text.lower()
    kw_lower = keyword.lower()
    if kw_lower in text_lower:
        return 1.0
    tokens = _tokenize(text)
    best = 0.0
    for token in tokens:
        ratio = SequenceMatcher(None, kw_lower, token).ratio()
        if ratio > best:
            best = ratio
    return best


def search_rss(query: str, sources: list[str] = None, limit: int = 5) -> list[dict]:
    feeds = {k: v for k, v in RSS_FEEDS.items() if sources is None or k in sources}
    keywords = query.split()
    candidates = []

    for source_name, feed_url in feeds.items():
        try:
            resp = httpx.get(feed_url, timeout=10, follow_redirects=True)
            resp.raise_for_status()
            feed = feedparser.parse(resp.text)
        except Exception as e:
            logger.warning(f"{source_name} 解析失败: {e}")
            continue

        for entry in feed.entries:
            text = entry.get("title", "") + " " + entry.get("summary", "")
            scores = [_fuzzy_match(kw, text) for kw in keywords]
            matched = sum(1 for s in scores if s >= _FUZZY_THRESHOLD)

            if matched > 0:
                candidates.append({
                    "source": source_name,
                    "title": entry.get("title", ""),
                    "url": entry.get("link", ""),
                    "summary": entry.get("summary", "")[:300],
                    "published": entry.get("published", ""),
                    "_matched": matched,
                    "_score": sum(scores),
                })

    candidates.sort(key=lambda x: (x["_matched"], x["_score"]), reverse=True)

    results = []
    for c in candidates[:limit]:
        c.pop("_matched")
        c.pop("_score")
        results.append(c)
    return results
