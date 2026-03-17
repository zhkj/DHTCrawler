"""
长期记忆：对话摘要向量化存储 + 用户画像。
跨会话持久，支持语义检索历史上下文。
"""
import logging
from datetime import datetime
from openai import OpenAI
from intelligence.config import LLM_API_KEY, LLM_BASE_URL, LLM_MODEL
from intelligence.db import (
    save_conversation_summary,
    save_user_profile, get_user_profile,
)

logger = logging.getLogger("intelligence.core.memory.long_term")


class LongTermMemory:

    def __init__(self, user_id: str = "default"):
        self.user_id = user_id
        self._client = OpenAI(api_key=LLM_API_KEY, base_url=LLM_BASE_URL)
        self._collection = None

    def _get_memory_collection(self):
        if self._collection is None:
            import chromadb
            from intelligence.config import CHROMA_PATH
            client = chromadb.PersistentClient(path=CHROMA_PATH)
            self._collection = client.get_or_create_collection(
                name="long_term_memory",
                metadata={"hnsw:space": "cosine"},
            )
        return self._collection

    def _get_embed_model(self):
        from intelligence.rag.vectorstore import _get_embed_model
        return _get_embed_model()

    # ── 对话摘要存储与检索 ──────────────────────────────────────

    def save_conversation(self, messages: list[dict]):
        """对话结束时：生成摘要 + 提取主题 -> MongoDB + ChromaDB。"""
        text_parts = []
        for m in messages:
            content = m.get("content", "")
            if isinstance(content, str) and content and m.get("role") in ("user", "assistant"):
                text_parts.append(f"{m['role'].upper()}: {content[:200]}")

        if len(text_parts) < 2:
            return

        conversation_text = "\n".join(text_parts[-20:])
        prompt = (
            "分析以下对话，输出：\n"
            "1. 一段3-5句的摘要\n"
            "2. 3-5个关键主题词（用逗号分隔）\n\n"
            "格式：\n摘要：<摘要内容>\n主题：<主题1>,<主题2>,...\n\n"
            f"对话内容：\n{conversation_text}"
        )

        try:
            resp = self._client.chat.completions.create(
                model=LLM_MODEL,
                max_tokens=300,
                messages=[{"role": "user", "content": prompt}],
            )
            result = resp.choices[0].message.content or ""

            summary = result
            topics = []
            for line in result.split("\n"):
                if line.startswith("摘要：") or line.startswith("摘要:"):
                    summary = line.split("：", 1)[-1].split(":", 1)[-1].strip()
                elif line.startswith("主题：") or line.startswith("主题:"):
                    topics = [
                        t.strip()
                        for t in line.split("：", 1)[-1].split(":", 1)[-1].split(",")
                        if t.strip()
                    ]
        except Exception as e:
            logger.warning(f"摘要生成失败: {e}")
            summary = conversation_text[:500]
            topics = []

        save_conversation_summary(self.user_id, summary, topics)

        try:
            collection = self._get_memory_collection()
            model = self._get_embed_model()
            embedding = model.encode([summary]).tolist()
            doc_id = f"{self.user_id}_{datetime.now().strftime('%Y%m%d%H%M%S')}"

            collection.add(
                embeddings=embedding,
                ids=[doc_id],
                metadatas=[{
                    "user_id": self.user_id,
                    "topics": ",".join(topics),
                    "created_at": datetime.now().isoformat(),
                }],
                documents=[summary],
            )
            logger.info(f"对话摘要已存储: topics={topics}")
        except Exception as e:
            logger.warning(f"向量存储失败: {e}")

    def recall(self, query: str, top_k: int = 3) -> list[dict]:
        """语义检索相关历史对话摘要。"""
        try:
            collection = self._get_memory_collection()
            model = self._get_embed_model()
            embedding = model.encode([query]).tolist()

            results = collection.query(
                query_embeddings=embedding,
                n_results=top_k,
                where={"user_id": self.user_id},
                include=["documents", "metadatas", "distances"],
            )

            memories = []
            for i in range(len(results["ids"][0])):
                relevance = round(1 - results["distances"][0][i], 3)
                if relevance < 0.3:
                    continue
                memories.append({
                    "summary": results["documents"][0][i],
                    "topics": results["metadatas"][0][i].get("topics", ""),
                    "created_at": results["metadatas"][0][i].get("created_at", ""),
                    "relevance": relevance,
                })
            return memories
        except Exception as e:
            logger.warning(f"记忆检索失败: {e}")
            return []

    # ── 用户画像 ────────────────────────────────────────────────

    def update_profile(self, **kwargs):
        profile = get_user_profile(self.user_id)
        profile.update(kwargs)
        profile["user_id"] = self.user_id
        profile["updated_at"] = datetime.now().isoformat()
        save_user_profile(self.user_id, profile)

    def get_profile(self) -> dict:
        return get_user_profile(self.user_id)

    def get_context_prompt(self, query: str) -> str:
        """生成长期记忆上下文，注入到 system prompt。"""
        parts = []

        profile = self.get_profile()
        if profile:
            focus = profile.get("focus_areas", [])
            style = profile.get("analysis_style", "")
            if focus:
                parts.append(f"用户关注领域: {', '.join(focus)}")
            if style:
                parts.append(f"用户偏好风格: {style}")

        memories = self.recall(query, top_k=3)
        if memories:
            parts.append("相关历史对话：")
            for m in memories:
                parts.append(f"- [{m['created_at'][:10]}] {m['summary']}")

        if not parts:
            return ""
        return "\n[长期记忆上下文]\n" + "\n".join(parts)
