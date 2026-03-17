"""语义缓存模块 — 基于 ChromaDB 的 query embedding 缓存。

相似度 > 阈值时直接返回缓存结果，避免重复 LLM 调用。
"""
import logging
from datetime import datetime

import chromadb

from intelligence.config import CHROMA_PATH

logger = logging.getLogger("intelligence.core.cache")

_CACHE_COLLECTION_NAME = "semantic_cache"
_SIMILARITY_THRESHOLD = 0.95  # cosine similarity >= 0.95 命中缓存
_CACHE_TTL_HOURS = 24

_cache_collection = None


def _get_cache_collection():
    global _cache_collection
    if _cache_collection is None:
        client = chromadb.PersistentClient(path=CHROMA_PATH)
        _cache_collection = client.get_or_create_collection(
            name=_CACHE_COLLECTION_NAME,
            metadata={"hnsw:space": "cosine"},
        )
    return _cache_collection


def _get_embed_model():
    from intelligence.rag.vectorstore import _get_embed_model
    return _get_embed_model()


def cache_lookup(query: str) -> str | None:
    """查询语义缓存。

    Args:
        query: 用户查询文本。

    Returns:
        缓存的回复文本，未命中返回 None。
    """
    try:
        collection = _get_cache_collection()
        if collection.count() == 0:
            return None

        model = _get_embed_model()
        embedding = model.encode([query]).tolist()

        results = collection.query(
            query_embeddings=embedding,
            n_results=1,
            include=["documents", "metadatas", "distances"],
        )

        if not results["ids"][0]:
            return None

        distance = results["distances"][0][0]
        similarity = 1 - distance

        if similarity >= _SIMILARITY_THRESHOLD:
            cached_response = results["documents"][0][0]
            created_at = results["metadatas"][0][0].get("created_at", "")

            # TTL 检查
            if created_at:
                try:
                    cache_time = datetime.fromisoformat(created_at)
                    age_hours = (datetime.now() - cache_time).total_seconds() / 3600
                    if age_hours > _CACHE_TTL_HOURS:
                        logger.info(f"缓存已过期 (age={age_hours:.1f}h)")
                        return None
                except (ValueError, TypeError):
                    pass

            logger.info(f"缓存命中 | similarity={similarity:.4f}")
            return cached_response

        return None

    except Exception as e:
        logger.warning(f"缓存查询失败: {e}")
        return None


def cache_store(query: str, response: str):
    """存储查询-回复对到语义缓存。

    Args:
        query: 用户查询文本。
        response: Agent 回复文本。
    """
    if not query or not response or len(response) < 20:
        return

    try:
        collection = _get_cache_collection()
        model = _get_embed_model()
        embedding = model.encode([query]).tolist()

        doc_id = f"cache_{datetime.now().strftime('%Y%m%d%H%M%S%f')}"

        collection.add(
            embeddings=embedding,
            ids=[doc_id],
            documents=[response],
            metadatas=[{
                "query": query[:500],
                "created_at": datetime.now().isoformat(),
                "response_len": len(response),
            }],
        )
        logger.info(f"缓存已存储 | query={query[:50]}")

    except Exception as e:
        logger.warning(f"缓存存储失败: {e}")


class TokenTracker:
    """Token 使用量追踪器。"""

    def __init__(self):
        self.total_prompt_tokens = 0
        self.total_completion_tokens = 0
        self.total_tokens = 0
        self.call_count = 0

    def track(self, usage):
        """从 OpenAI response.usage 中提取 token 统计。"""
        if usage is None:
            return

        prompt = getattr(usage, "prompt_tokens", 0) or 0
        completion = getattr(usage, "completion_tokens", 0) or 0
        total = getattr(usage, "total_tokens", 0) or 0

        self.total_prompt_tokens += prompt
        self.total_completion_tokens += completion
        self.total_tokens += total
        self.call_count += 1

    def summary(self) -> dict:
        return {
            "total_prompt_tokens": self.total_prompt_tokens,
            "total_completion_tokens": self.total_completion_tokens,
            "total_tokens": self.total_tokens,
            "call_count": self.call_count,
            "avg_tokens_per_call": (
                round(self.total_tokens / self.call_count)
                if self.call_count > 0 else 0
            ),
        }

    def reset(self):
        self.total_prompt_tokens = 0
        self.total_completion_tokens = 0
        self.total_tokens = 0
        self.call_count = 0
