"""
上下文管理 + 记忆层
- 短期记忆：滑动窗口 + 摘要压缩（单次对话内）
- 长期记忆：用户偏好和告警规则（跨对话，存 MongoDB）
"""
from openai import OpenAI
from config import LLM_API_KEY, LLM_BASE_URL, LLM_MODEL
from db.mongo_client import save_alert, get_alerts

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

        # 只提取文本消息做摘要，跳过工具调用消息
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

    def clear(self):
        self.messages = []


class UserPreferences:
    """
    长期记忆：用户偏好和告警规则，持久化到 MongoDB。
    """

    def __init__(self, user_id: str = "default"):
        self.user_id = user_id

    def set_alerts(self, keywords: list[str]):
        save_alert(self.user_id, keywords)

    def get_alerts(self) -> list[str]:
        return get_alerts(self.user_id)
