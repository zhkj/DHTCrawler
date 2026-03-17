"""
两级记忆系统
- 短期记忆：滑动窗口 + 摘要压缩（单次对话内）
- 长期记忆：对话摘要向量化存储 + 用户画像（跨对话，MongoDB + ChromaDB）
"""
import logging
from datetime import datetime
from openai import OpenAI
from config import LLM_API_KEY, LLM_BASE_URL, LLM_MODEL
from db.mongo_client import (
    save_alert, get_alerts,
    save_conversation_summary, get_conversation_summaries,
    save_user_profile, get_user_profile,
)

logger = logging.getLogger("intelligence.memory")

MAX_MESSAGES = 20       # 超过此数量触发压缩
KEEP_RECENT  = 6        # 压缩时保留最近几条原始消息


class ConversationMemory:
    """
    短期记忆：维护当前对话的消息历史，自动在超长时压缩。
    """

    def __init__(self):
        self.messages: list[dict] = []
        self._client = OpenAI(api_key=LLM_API_KEY, base_url=LLM_BASE_URL)

    def add(self, role: str, content: str):
        self.messages.append({"role": role, "content": content})
        if len(self.messages) > MAX_MESSAGES:
            self._compress()

    def get(self) -> list[dict]:
        return self.messages

    def _compress(self):
        """将旧消息摘要化，保留最近几条原文。"""
        old_messages = self.messages[:-KEEP_RECENT]
        recent_messages = self.messages[-KEEP_RECENT:]

        history_parts = []
        for m in old_messages:
            content = m.get("content", "")
            if isinstance(content, str) and content:
                history_parts.append(f"{m['role'].upper()}: {content}")
        history_text = "\n".join(history_parts)

        summary_prompt = f"请用3-5句话概括以下对话的要点：\n\n{history_text}"

        try:
            resp = self._client.chat.completions.create(
                model=LLM_MODEL,
                max_tokens=300,
                messages=[{"role": "user", "content": summary_prompt}],
            )
            summary = resp.choices[0].message.content
        except Exception:
            summary = "（早期对话已压缩）"

        self.messages = [
            {"role": "user", "content": f"[对话摘要] {summary}"},
            {"role": "assistant", "content": "好的，我记住了之前的讨论内容。"},
            *recent_messages,
        ]

    def get_text_messages(self) -> list[dict]:
        """获取所有纯文本消息（过滤掉工具调用消息），用于生成摘要。"""
        return [
            m for m in self.messages
            if isinstance(m.get("content"), str) and m.get("role") in ("user", "assistant")
        ]

    def clear(self):
        self.messages = []


class UserPreferences:
    """
    长期记忆（基础层）：用户偏好和告警规则，持久化到 MongoDB。
    """

    def __init__(self, user_id: str = "default"):
        self.user_id = user_id

    def set_alerts(self, keywords: list[str]):
        save_alert(self.user_id, keywords)

    def get_alerts(self) -> list[str]:
        return get_alerts(self.user_id)


class LongTermMemory:
    """
    长期记忆（增强层）：
    1. 对话摘要 → 向量化存入 ChromaDB，支持语义检索历史
    2. 用户画像 → 关注领域、分析偏好、交互习惯
    3. 误报反馈 → 从 HITL 流程学习的错误模式
    """

    def __init__(self, user_id: str = "default"):
        self.user_id = user_id
        self._client = OpenAI(api_key=LLM_API_KEY, base_url=LLM_BASE_URL)
        self._collection = None

    def _get_memory_collection(self):
        """获取长期记忆专用的 ChromaDB collection（懒加载）。"""
        if self._collection is None:
            import chromadb
            from config import CHROMA_PATH
            client = chromadb.PersistentClient(path=CHROMA_PATH)
            self._collection = client.get_or_create_collection(
                name="long_term_memory",
                metadata={"hnsw:space": "cosine"},
            )
        return self._collection

    def _get_embed_model(self):
        """复用全局 embedding 模型。"""
        from rag.vectorstore import _get_embed_model
        return _get_embed_model()

    # ── 对话摘要存储与检索 ──────────────────────────────────────

    def save_conversation(self, messages: list[dict]):
        """
        对话结束时调用：生成摘要 + 提取主题 → 存入 MongoDB + ChromaDB。
        """
        text_parts = []
        for m in messages:
            content = m.get("content", "")
            if isinstance(content, str) and content and m.get("role") in ("user", "assistant"):
                text_parts.append(f"{m['role'].upper()}: {content[:200]}")

        if len(text_parts) < 2:
            return  # 对话太短，不值得存储

        conversation_text = "\n".join(text_parts[-20:])  # 最多取最近20条

        # LLM 生成摘要和主题
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

            # 解析摘要和主题
            summary = result
            topics = []
            for line in result.split("\n"):
                if line.startswith("摘要：") or line.startswith("摘要:"):
                    summary = line.split("：", 1)[-1].split(":", 1)[-1].strip()
                elif line.startswith("主题：") or line.startswith("主题:"):
                    topics = [t.strip() for t in line.split("：", 1)[-1].split(":", 1)[-1].split(",") if t.strip()]

        except Exception as e:
            logger.warning(f"[LongTermMemory] 摘要生成失败: {e}")
            summary = conversation_text[:500]
            topics = []

        # 存入 MongoDB
        save_conversation_summary(self.user_id, summary, topics)

        # 向量化存入 ChromaDB
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
            logger.info(f"[LongTermMemory] 对话摘要已存储: topics={topics}")
        except Exception as e:
            logger.warning(f"[LongTermMemory] 向量存储失败: {e}")

    def recall(self, query: str, top_k: int = 3) -> list[dict]:
        """
        语义检索相关历史对话摘要。
        用于新对话开始时注入相关上下文。
        """
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
                distance = results["distances"][0][i]
                relevance = round(1 - distance, 3)
                if relevance < 0.3:  # 相关度太低就不返回
                    continue
                memories.append({
                    "summary": results["documents"][0][i],
                    "topics": results["metadatas"][0][i].get("topics", ""),
                    "created_at": results["metadatas"][0][i].get("created_at", ""),
                    "relevance": relevance,
                })
            return memories

        except Exception as e:
            logger.warning(f"[LongTermMemory] 记忆检索失败: {e}")
            return []

    # ── 用户画像 ────────────────────────────────────────────────

    def update_profile(self, **kwargs):
        """
        更新用户画像。支持的字段：
        - focus_areas: list[str]  关注领域
        - analysis_style: str     偏好的分析风格（简洁/详细/技术向）
        - language: str           偏好语言
        """
        profile = get_user_profile(self.user_id)
        profile.update(kwargs)
        profile["user_id"] = self.user_id
        profile["updated_at"] = datetime.now().isoformat()
        save_user_profile(self.user_id, profile)
        logger.info(f"[LongTermMemory] 用户画像已更新: {list(kwargs.keys())}")

    def get_profile(self) -> dict:
        """获取用户画像。"""
        return get_user_profile(self.user_id)

    def get_context_prompt(self, query: str) -> str:
        """
        生成长期记忆上下文注入 prompt。
        综合历史对话检索 + 用户画像 → 注入到 system prompt 中。
        """
        parts = []

        # 1. 用户画像
        profile = self.get_profile()
        if profile:
            focus = profile.get("focus_areas", [])
            style = profile.get("analysis_style", "")
            if focus:
                parts.append(f"用户关注领域: {', '.join(focus)}")
            if style:
                parts.append(f"用户偏好风格: {style}")

        # 2. 相关历史对话
        memories = self.recall(query, top_k=3)
        if memories:
            parts.append("相关历史对话：")
            for m in memories:
                parts.append(f"- [{m['created_at'][:10]}] {m['summary']}")

        if not parts:
            return ""

        return "\n[长期记忆上下文]\n" + "\n".join(parts)
