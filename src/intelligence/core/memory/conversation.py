"""短期记忆：滑动窗口 + LLM 摘要压缩。"""
from intelligence.config import LLM_MODEL
from intelligence.core.llm_client import get_client

MAX_MESSAGES = 20
MAX_CONTEXT_TOKENS = 12000
KEEP_RECENT = 6


def _estimate_tokens(text: str) -> int:
    """估算文本 token 数。中文约 1-2 字/token，英文约 4 字符/token。"""
    if not text:
        return 0
    chinese_chars = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
    other_chars = len(text) - chinese_chars
    return chinese_chars + max(1, other_chars // 4)


class ConversationMemory:

    def __init__(self):
        self.messages: list[dict] = []
        self._client = get_client()

    def _total_tokens(self) -> int:
        """估算当前所有消息的总 token 数。"""
        total = 0
        for m in self.messages:
            content = m.get("content", "")
            if isinstance(content, str):
                total += _estimate_tokens(content)
        return total

    def add(self, role: str, content: str):
        self.messages.append({"role": role, "content": content})
        if (self._total_tokens() > MAX_CONTEXT_TOKENS
                or len(self.messages) > MAX_MESSAGES):
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
            role = m.get("role", "")
            content = m.get("content", "")
            if role == "tool":
                # Include tool results in compression summary
                history_parts.append(f"TOOL_RESULT: {str(content)[:200]}")
            elif isinstance(content, str) and content:
                history_parts.append(f"{role.upper()}: {content}")
            elif role == "assistant" and m.get("tool_calls"):
                # Include tool call info
                tool_names = [
                    tc.get("function", {}).get("name", "unknown")
                    for tc in m.get("tool_calls", [])
                ]
                history_parts.append(
                    f"ASSISTANT: [调用工具: {', '.join(tool_names)}]"
                )
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
