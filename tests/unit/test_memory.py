"""短期记忆单元测试。"""
from unittest.mock import patch

from intelligence.core.memory.conversation import ConversationMemory


class TestConversationMemory:

    def test_add_and_get(self):
        mem = ConversationMemory()
        mem.add("user", "hello")
        mem.add("assistant", "hi there")
        msgs = mem.get()
        assert len(msgs) == 2
        assert msgs[0]["role"] == "user"
        assert msgs[1]["content"] == "hi there"

    def test_clear(self):
        mem = ConversationMemory()
        mem.add("user", "test")
        mem.clear()
        assert len(mem.get()) == 0

    def test_get_text_messages_filters_tool(self):
        mem = ConversationMemory()
        mem.add("user", "query")
        mem.messages.append({"role": "tool", "content": "result"})
        mem.add("assistant", "answer")
        text_msgs = mem.get_text_messages()
        assert len(text_msgs) == 2
        assert all(m["role"] in ("user", "assistant") for m in text_msgs)

    @patch.object(ConversationMemory, "_compress")
    def test_compress_triggered_on_overflow(self, mock_compress):
        mem = ConversationMemory()
        for i in range(21):
            mem.add("user", f"msg {i}")
        mock_compress.assert_called()
