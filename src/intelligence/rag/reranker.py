"""Cross-Encoder 重排序模块。

使用 cross-encoder/ms-marco-MiniLM-L-6-v2 对 query-document pair 打分，
实现精排。支持 RRF（Reciprocal Rank Fusion）融合多路召回结果。
"""
import logging

from sentence_transformers import CrossEncoder

logger = logging.getLogger("intelligence.rag.reranker")

RERANK_MODEL = "cross-encoder/ms-marco-MiniLM-L-6-v2"

_cross_encoder: CrossEncoder | None = None


def _get_cross_encoder() -> CrossEncoder:
    global _cross_encoder
    if _cross_encoder is None:
        logger.info(f"加载 Cross-Encoder 模型: {RERANK_MODEL}")
        _cross_encoder = CrossEncoder(RERANK_MODEL)
    return _cross_encoder


def reciprocal_rank_fusion(
    *result_lists: list[dict],
    k: int = 60,
    id_key: str = "info_hash",
) -> list[dict]:
    """RRF 融合多路召回结果。

    公式: score = Σ 1/(k + rank_i)

    Args:
        *result_lists: 多个排序后的文档列表。
        k: RRF 常数，默认 60。
        id_key: 文档唯一标识字段。

    Returns:
        按 RRF 分数降序排列的去重文档列表。
    """
    rrf_scores: dict[str, float] = {}
    doc_map: dict[str, dict] = {}

    for results in result_lists:
        for rank, doc in enumerate(results):
            doc_id = doc.get(id_key, "")
            if not doc_id:
                continue
            rrf_scores[doc_id] = rrf_scores.get(doc_id, 0) + 1.0 / (k + rank + 1)
            if doc_id not in doc_map:
                doc_map[doc_id] = doc

    # 按 RRF 分数降序排列
    sorted_ids = sorted(rrf_scores.keys(), key=lambda x: rrf_scores[x], reverse=True)

    results = []
    for doc_id in sorted_ids:
        doc = doc_map[doc_id].copy()
        doc["rrf_score"] = round(rrf_scores[doc_id], 6)
        results.append(doc)

    return results


def rerank(query: str, documents: list[dict], top_k: int = 5,
           text_key: str = "name") -> list[dict]:
    """Cross-Encoder 精排。

    对每个 query-document pair 用 Cross-Encoder 打分，返回 top_k。

    Args:
        query: 用户查询。
        documents: 待排序文档列表。
        top_k: 返回数量。
        text_key: 文档中用于排序的文本字段。

    Returns:
        按 Cross-Encoder 分数降序排列的文档列表。
    """
    if not documents:
        return []

    if len(documents) <= top_k:
        return documents

    model = _get_cross_encoder()

    # 构建 query-document pairs
    pairs = []
    for doc in documents:
        text = doc.get(text_key, "") or doc.get("name", "")
        pairs.append([query, text])

    # 打分
    scores = model.predict(pairs)

    # 按分数排序
    scored_docs = list(zip(documents, scores))
    scored_docs.sort(key=lambda x: x[1], reverse=True)

    results = []
    for doc, score in scored_docs[:top_k]:
        doc = doc.copy()
        doc["rerank_score"] = round(float(score), 4)
        results.append(doc)

    return results
