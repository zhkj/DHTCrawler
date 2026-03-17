"""
告警置信度评分模块。
根据关键词命中情况评估告警可信度，决定自动推送还是待人工审批。
"""

# 已知误报关键词缓存（由 agent 定期刷新）
_false_positive_keywords: set = set()


def refresh_false_positives():
    """从 MongoDB 刷新误报关键词缓存（count >= 2 视为高频误报）。"""
    global _false_positive_keywords
    try:
        from intelligence.db import get_false_positives
        fps = get_false_positives()
        _false_positive_keywords = {
            fp["keyword"].lower() for fp in fps if fp.get("count", 0) >= 2
        }
    except Exception:
        pass


def score(matched_keywords: list[str], categories: list[str],
          is_user_rule: bool) -> str:
    """
    计算告警置信度。

    返回: "high" / "medium" / "low"

    规则：
    - 用户自定义规则命中 -> high（用户明确关注）
    - 系统信号词命中 3+ 关键词 或 2+ 分类 -> high
    - 系统信号词命中 2 关键词 或 1 分类 -> medium
    - 仅 1 个泛化关键词命中 -> low
    - 已知误报关键词自动降级
    """
    if is_user_rule:
        return "high"

    effective_keywords = [
        kw for kw in matched_keywords
        if kw.lower() not in _false_positive_keywords
    ]
    if not effective_keywords:
        return "low"

    n_keywords = len(effective_keywords)
    n_categories = len(categories)

    if n_keywords >= 3 or n_categories >= 2:
        return "high"
    if n_keywords >= 2 or (n_categories >= 1 and n_keywords >= 1):
        return "medium"
    return "low"
