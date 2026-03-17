"""短期记忆：滑动窗口 + LLM 摘要压缩。"""
from openai import OpenAI
from intelligence.config import LLM_API_KEY, LLM_BASE_URL, LLM_MODEL

MAX_MESSAGES = 20
KEEP_RECENT = 6


class ConversationMemory:

    def __init__(self):
        self.messages: list[dict] = []
        self._client = OpenAI(api_key=LLM_API_KEY, base_url=LLM_BASE_URL)

    def add(self, role: str, content: str):
        self.messages.append({"role": role, "content": content})
        if len(self.messages) > MAX_MESSAGES:
            self._compress()

    def get(self) -> list[dict]:
        return self.messages

    def get_text_messages(self) -> list[dict]:
        """获取纯文本消息（过滤工具调用），用于生成摘要。"""
        return [
            m for m in self.messages
            if isinstance(m.get("content"), str)
            and m.get("role") in ("user", "assistant")
        ]

    def _compress(self):
        old_messages = self.messages[:-KEEP_RECENT]
        recent_messages = self.messages[-KEEP_RECENT:]

        history_parts = []
        for m in old_messages:
            content = m.get("content", "")
            if isinstance(content, str) and content:
                history_parts.append(f"{m['role'].upper()}: {content}")
        history_text = "\n".join(history_parts)

        try:
            resp = self._client.chat.completions.create(
                model=LLM_MODEL,
                max_tokens=300,
                messages=[{
                    "role": "user",
                    "content": f"请用3-5句话概括以下对话的要点：\n\n{history_text}",
                }],
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
