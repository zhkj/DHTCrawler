"""BM25 关键词检索模块。

基于 rank_bm25 实现，对种子名称 + 文件列表做分词索引。
中文按字符切分，英文按空格/标点切分，避免引入 jieba 等重依赖。
"""
import logging
import re

from rank_bm25 import BM25Okapi

logger = logging.getLogger("intelligence.rag.bm25")

# 全局 BM25 索引（内存中维护，随 sync 更新）
_bm25_index: BM25Okapi | None = None
_corpus_docs: list[dict] = []  # 保留原始文档用于返回


def _tokenize(text: str) -> list[str]:
    """简单分词：英文按空格/标点切分，中文按字符切分。"""
    return re.findall(r'[\u4e00-\u9fff]|[a-zA-Z0-9]+', text.lower())


def _doc_to_text(doc: dict) -> str:
    """将种子文档转为可检索文本。"""
    name = doc.get("name", "")
    files = doc.get("files", [])
    file_parts = []
    for f in files[:10]:
        if isinstance(f, list):
            file_parts.append(str(f[0]) if f else "")
        elif isinstance(f, dict):
            file_parts.append(f.get("path", str(f)))
        else:
            file_parts.append(str(f))
    return f"{name} {' '.join(file_parts)}"


def build_index(documents: list[dict]):
    """构建/重建 BM25 索引。

    Args:
        documents: 种子文档列表，每个需包含 info_hash, name 等字段。
    """
    global _bm25_index, _corpus_docs

    if not documents:
        return

    _corpus_docs = documents
    tokenized_corpus = [_tokenize(_doc_to_text(doc)) for doc in documents]
    _bm25_index = BM25Okapi(tokenized_corpus)
    logger.info(f"BM25 索引已构建，共 {len(documents)} 条文档")


def search(query: str, top_k: int = 20) -> list[dict]:
    """BM25 关键词检索。

    Args:
        query: 搜索查询文本。
        top_k: 返回结果数量。

    Returns:
        按 BM25 分数排序的文档列表，每个包含 bm25_score 字段。
    """
    if _bm25_index is None or not _corpus_docs:
        logger.warning("BM25 索引未构建，返回空结果")
        return []

    tokenized_query = _tokenize(query)
    if not tokenized_query:
        return []

    scores = _bm25_index.get_scores(tokenized_query)

    # 取 top_k 个非零分数的文档
    scored_docs = [
        (idx, score) for idx, score in enumerate(scores) if score > 0
    ]
    scored_docs.sort(key=lambda x: x[1], reverse=True)
    scored_docs = scored_docs[:top_k]

    results = []
    for idx, score in scored_docs:
        doc = _corpus_docs[idx].copy()
        doc["bm25_score"] = round(float(score), 4)
        results.append(doc)

    return results


def update_index(new_documents: list[dict]):
    """增量更新：将新文档加入索引并重建。"""
    existing_hashes = {doc.get("info_hash") for doc in _corpus_docs}
    added = [doc for doc in new_documents if doc.get("info_hash") not in existing_hashes]
    if added:
        all_docs = _corpus_docs + added
        build_index(all_docs)


def ensure_initialized():
    """确保 BM25 索引已初始化。

    从 MongoDB 读取种子数据构建索引，解决进程启动时 BM25 为空的问题。
    """
    if _bm25_index is not None:
        return

    try:
        from intelligence.config import BM25_INIT_LIMIT
        from intelligence.db.repo_torrent import get_recent_torrents
        docs = get_recent_torrents(limit=BM25_INIT_LIMIT)
        if docs:
            build_index(docs)
            logger.info(
                f"BM25 索引从 MongoDB 初始化完成，共 {len(docs)} 条"
            )
    except Exception as e:
        logger.warning(f"BM25 索引初始化失败: {e}")
