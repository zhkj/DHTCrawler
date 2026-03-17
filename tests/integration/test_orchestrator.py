"""Orchestrator 集成测试（需要 MongoDB + LLM API）。"""
import pytest

# 标记为集成测试，默认跳过
pytestmark = pytest.mark.skipif(
    True, reason="集成测试需要 MongoDB 和 LLM API，手动运行: pytest -k integration"
)


class TestOrchestrator:

    def test_chat_returns_string(self):
        from intelligence.core import Orchestrator
        agent = Orchestrator(user_id="test")
        reply = agent.chat("你好")
        assert isinstance(reply, str)
        assert len(reply) > 0
