"""RAG 模块：向量化存储 + 混合检索（Vector + BM25）+ Cross-Encoder 重排序。"""
import logging

import chromadb
from sentence_transformers import SentenceTransformer

from intelligence.config import CHROMA_COLLECTION, CHROMA_PATH, EMBED_MODEL

logger = logging.getLogger("intelligence.rag")

_embed_model = None
_chroma_client = None
_collection = None


def _get_embed_model():
    global _embed_model
    if _embed_model is None:
        logger.info(f"加载 Embedding 模型: {EMBED_MODEL}")
        _embed_model = SentenceTransformer(EMBED_MODEL)
    return _embed_model


def _get_collection():
    global _chroma_client, _collection
    if _collection is None:
        _chroma_client = chromadb.PersistentClient(path=CHROMA_PATH)
        _collection = _chroma_client.get_or_create_collection(
            name=CHROMA_COLLECTION,
            metadata={"hnsw:space": "cosine"},
        )
    return _collection


def _torrent_to_text(torrent: dict) -> str:
    name = torrent.get("name", "")
    files = torrent.get("files", [])
    file_names = " ".join([f[0] if isinstance(f, list) else str(f) for f in files[:10]])
    summary = torrent.get("external_summary", "")
    return f"种子名称: {name} 文件: {file_names} 外部信息: {summary}"


def index_torrents(torrents: list[dict]):
    """批量向量化种子数据存入 ChromaDB，同时更新 BM25 索引。"""
    collection = _get_collection()
    model = _get_embed_model()

    texts, ids, metadatas = [], [], []
    new_docs_for_bm25 = []
    for t in torrents:
        info_hash = t.get("info_hash", "")
        if not info_hash:
            continue
        existing = collection.get(ids=[info_hash])
        if existing["ids"]:
            continue

        texts.append(_torrent_to_text(t))
        ids.append(info_hash)
        metadatas.append({
            "name": t.get("name", ""),
            "magnet": t.get("magnet", ""),
            "date": str(t.get("date", "")),
        })
        new_docs_for_bm25.append(t)

    if not texts:
        return

    embeddings = model.encode(texts).tolist()
    collection.add(embeddings=embeddings, ids=ids, metadatas=metadatas, documents=texts)
    logger.info(f"已索引 {len(texts)} 条记录")

    # 增量更新 BM25 索引
    if new_docs_for_bm25:
        try:
            from intelligence.rag.bm25 import update_index
            update_index(new_docs_for_bm25)
        except Exception as e:
            logger.warning(f"BM25 索引更新失败: {e}")


def _vector_search(query: str, top_k: int = 20) -> list[dict]:
    """纯向量语义检索。"""
    collection = _get_collection()
    model = _get_embed_model()

    embedding = model.encode([query]).tolist()
    results = collection.query(
        query_embeddings=embedding,
        n_results=top_k,
        include=["documents", "metadatas", "distances"],
    )

    output = []
    for i in range(len(results["ids"][0])):
        output.append({
            "info_hash": results["ids"][0][i],
            "name": results["metadatas"][0][i].get("name", ""),
            "magnet": results["metadatas"][0][i].get("magnet", ""),
            "date": results["metadatas"][0][i].get("date", ""),
            "relevance": round(1 - results["distances"][0][i], 3),
        })
    return output


def search(query: str, top_k: int = 5, use_rerank: bool = True) -> list[dict]:
    """混合检索：Vector + BM25 → RRF 融合 → Cross-Encoder 重排序。

    流程：
        query → 并行:
            ├─ Vector Search (ChromaDB, top_k=20)
            └─ BM25 Search (内存索引, top_k=20)
                ↓
            RRF 融合（Reciprocal Rank Fusion）去重合并
                ↓
            Cross-Encoder Rerank (top_k=final)
                ↓
            返回精排结果

    Args:
        query: 搜索查询文本。
        top_k: 最终返回结果数量。
        use_rerank: 是否启用 Cross-Encoder 重排序，默认开启。

    Returns:
        排序后的种子文档列表。
    """
    recall_k = max(top_k * 4, 20)

    # 1. 向量检索
    vector_results = _vector_search(query, top_k=recall_k)

    # 2. BM25 关键词检索
    bm25_results = []
    try:
        from intelligence.rag.bm25 import search as bm25_search
        bm25_results = bm25_search(query, top_k=recall_k)
    except Exception as e:
        logger.warning(f"BM25 检索失败，仅使用向量检索: {e}")

    # 3. RRF 融合
    if bm25_results:
        from intelligence.rag.reranker import reciprocal_rank_fusion
        fused_results = reciprocal_rank_fusion(
            vector_results, bm25_results, k=60, id_key="info_hash",
        )
    else:
        fused_results = vector_results

    # 4. Cross-Encoder 重排序
    if use_rerank and len(fused_results) > top_k:
        try:
            from intelligence.rag.reranker import rerank
            final_results = rerank(query, fused_results, top_k=top_k, text_key="name")
        except Exception as e:
            logger.warning(f"Rerank 失败，使用 RRF 排序: {e}")
            final_results = fused_results[:top_k]
    else:
        final_results = fused_results[:top_k]

    return final_results
