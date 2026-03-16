"""
RSS 新闻聚合 — 完全免费，无需 API Key
支持中英文模糊匹配（OR 逻辑 + 按相关度排序）
"""
import re
from difflib import SequenceMatcher

import feedparser
import httpx


# 科技新闻源（可自由增减）
RSS_FEEDS = {
    # 英文源
    "hackernews_top":   "https://news.ycombinator.com/rss",
    "techcrunch":       "https://techcrunch.com/feed/",
    "theverge":         "https://www.theverge.com/rss/index.xml",
    "wired":            "https://www.wired.com/feed/rss",
    "bleepingcomputer": "https://www.bleepingcomputer.com/feed/",
    # 中文源
    "solidot":          "https://www.solidot.org/index.rss",
    "ithome":           "https://www.ithome.com/rss/",
}

# 模糊匹配阈值：两个词的相似度 >= 此值视为匹配
_FUZZY_THRESHOLD = 0.65


def _tokenize(text: str) -> list[str]:
    """分词：英文按空格/标点拆分，中文按单字拆分"""
    # 提取英文单词
    en_words = re.findall(r'[a-zA-Z0-9]+', text.lower())
    # 提取中文字符（单字作为 token）
    cn_chars = re.findall(r'[\u4e00-\u9fff]', text)
    return en_words + cn_chars


def _fuzzy_match(keyword: str, text: str) -> float:
    """
    计算关键词与文本的模糊匹配得分。
    - 精确子串包含：得分 1.0
    - 否则用 SequenceMatcher 找最佳局部匹配
    """
    text_lower = text.lower()
    kw_lower = keyword.lower()

    # 精确子串匹配（对中文尤其重要）
    if kw_lower in text_lower:
        return 1.0

    # 英文模糊匹配：与文本中每个词比较
    tokens = _tokenize(text)
    best = 0.0
    for token in tokens:
        ratio = SequenceMatcher(None, kw_lower, token).ratio()
        if ratio > best:
            best = ratio
    return best


def search_rss(query: str, sources: list[str] = None, limit: int = 5) -> list[dict]:
    """
    从 RSS 源中模糊搜索文章。
    - OR 逻辑：任一关键词匹配即可入选
    - 按匹配关键词数 + 相似度总分排序
    - 支持中英文混合查询
    """
    feeds = {k: v for k, v in RSS_FEEDS.items() if sources is None or k in sources}
    keywords = query.split()
    candidates = []

    for source_name, feed_url in feeds.items():
        try:
            resp = httpx.get(feed_url, timeout=10, follow_redirects=True)
            resp.raise_for_status()
            feed = feedparser.parse(resp.text)
        except Exception as e:
            print(f"[RSS] {source_name} 解析失败: {e}")
            continue

        for entry in feed.entries:
            text = entry.get("title", "") + " " + entry.get("summary", "")
            # 计算每个关键词的匹配得分
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

    # 按匹配词数降序，再按总分降序
    candidates.sort(key=lambda x: (x["_matched"], x["_score"]), reverse=True)

    # 去掉内部排序字段
    results = []
    for c in candidates[:limit]:
        c.pop("_matched")
        c.pop("_score")
        results.append(c)

    return results


if __name__ == "__main__":
    results = search_rss("security")
    if results:
        for r in results:
            print(r["source"], r["title"])
    else:
        print("无匹配结果")
