"""LongTermMemory 单元测试 — 测试 recall、save、profile。"""
from unittest.mock import patch, MagicMock
import pytest


class TestLongTermMemorySave:

    @patch("intelligence.core.memory.long_term.save_conversation_summary")
    @patch("intelligence.core.memory.long_term.OpenAI")
    def test_save_conversation_generates_summary(self, mock_openai_cls, mock_save):
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client
        mock_resp = MagicMock()
        mock_resp.choices = [MagicMock()]
        mock_resp.choices[0].message.content = "摘要：这是一段关于AI的讨论\n主题：AI,安全,泄露"
        mock_client.chat.completions.create.return_value = mock_resp

        from intelligence.core.memory.long_term import LongTermMemory
        mem = LongTermMemory.__new__(LongTermMemory)
        mem.user_id = "test"
        mem._client = mock_client
        mem._collection = None

        # Mock vector collection
        with patch.object(mem, "_get_memory_collection") as mock_coll, \
             patch.object(mem, "_get_embed_model") as mock_embed:
            import numpy as np
            mock_model = MagicMock()
            mock_model.encode.return_value = np.array([[0.1] * 384])
            mock_embed.return_value = mock_model

            coll = MagicMock()
            mock_coll.return_value = coll

            messages = [
                {"role": "user", "content": "AI有泄露吗"},
                {"role": "assistant", "content": "目前观测到以下情况..."},
                {"role": "user", "content": "详细说说"},
                {"role": "assistant", "content": "具体分析如下..."},
            ]
            mem.save_conversation(messages)

            mock_save.assert_called_once()
            coll.add.assert_called_once()

    @patch("intelligence.core.memory.long_term.save_conversation_summary")
    @patch("intelligence.core.memory.long_term.OpenAI")
    def test_save_skips_short_conversation(self, mock_openai_cls, mock_save):
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client

        from intelligence.core.memory.long_term import LongTermMemory
        mem = LongTermMemory.__new__(LongTermMemory)
        mem.user_id = "test"
        mem._client = mock_client
        mem._collection = None

        mem.save_conversation([{"role": "user", "content": "hi"}])
        mock_save.assert_not_called()


class TestLongTermMemoryRecall:

    @patch("intelligence.core.memory.long_term.OpenAI")
    def test_recall_returns_relevant_memories(self, mock_openai_cls):
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client

        from intelligence.core.memory.long_term import LongTermMemory
        mem = LongTermMemory.__new__(LongTermMemory)
        mem.user_id = "test"
        mem._client = mock_client
        mem._collection = None

        mock_collection = MagicMock()
        mock_collection.query.return_value = {
            "ids": [["doc1", "doc2"]],
            "documents": [["关于AI安全的讨论", "关于数据泄露的分析"]],
            "metadatas": [[
                {"user_id": "test", "topics": "AI,安全", "created_at": "2024-01-01"},
                {"user_id": "test", "topics": "泄露", "created_at": "2024-01-02"},
            ]],
            "distances": [[0.2, 0.4]],
        }

        import numpy as np
        mock_embed = MagicMock()
        mock_embed.encode.return_value = np.array([[0.1] * 384])

        with patch.object(mem, "_get_memory_collection", return_value=mock_collection), \
             patch.object(mem, "_get_embed_model", return_value=mock_embed):

            results = mem.recall("AI安全相关")
            assert len(results) == 2
            assert results[0]["relevance"] == 0.8
            assert "AI安全" in results[0]["summary"]


class TestLongTermMemoryProfile:

    @patch("intelligence.core.memory.long_term.get_user_profile")
    @patch("intelligence.core.memory.long_term.save_user_profile")
    @patch("intelligence.core.memory.long_term.OpenAI")
    def test_update_and_get_profile(self, mock_openai_cls, mock_save, mock_get):
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client

        mock_get.return_value = {"focus_areas": ["AI"]}

        from intelligence.core.memory.long_term import LongTermMemory
        mem = LongTermMemory.__new__(LongTermMemory)
        mem.user_id = "test"
        mem._client = mock_client
        mem._collection = None

        mem.update_profile(analysis_style="详细")
        mock_save.assert_called_once()
        saved_profile = mock_save.call_args[0][1]
        assert saved_profile["focus_areas"] == ["AI"]
        assert saved_profile["analysis_style"] == "详细"

    @patch("intelligence.core.memory.long_term.get_user_profile", return_value={})
    @patch("intelligence.core.memory.long_term.OpenAI")
    def test_get_context_prompt_empty_profile(self, mock_openai_cls, mock_get):
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client

        from intelligence.core.memory.long_term import LongTermMemory
        mem = LongTermMemory.__new__(LongTermMemory)
        mem.user_id = "test"
        mem._client = mock_client
        mem._collection = None

        with patch.object(mem, "recall", return_value=[]):
            ctx = mem.get_context_prompt("test query")
            assert ctx == ""
