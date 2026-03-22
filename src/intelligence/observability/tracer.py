"""Agent 调用链路追踪。"""
import logging
import time
from datetime import datetime

from intelligence.db import save_trace

logger = logging.getLogger("intelligence.observability.tracer")


class Trace:
    """
    一次 Agent chat 调用的 trace 记录。

    用法：
        trace = Trace(query="用户问题")
        trace.add_llm_call(round=0, tokens=100, latency_ms=500)
        trace.add_tool_call("search_dht", {"query": "..."}, "结果...", latency_ms=200)
        trace.finish(response="最终回复", status="success")
    """

    def __init__(self, query: str, user_id: str = "default"):
        self.trace_id = f"trace_{datetime.now().strftime('%Y%m%d%H%M%S%f')}"
        self.user_id = user_id
        self.query = query[:500]
        self.start_time = datetime.now()
        self._start_ts = time.time()

        self.llm_calls: list[dict] = []
        self.tool_calls: list[dict] = []
        self.total_tokens = 0
        self.rounds = 0
        self.response = ""
        self.status = "in_progress"
        self.error = None

    def add_llm_call(self, round_num: int, tokens: int, latency_ms: int):
        self.llm_calls.append({
            "round": round_num, "tokens": tokens, "latency_ms": latency_ms,
        })
        self.total_tokens += tokens
        self.rounds = round_num + 1

    def add_tool_call(self, tool_name: str, tool_input: dict,
                      result_preview: str, latency_ms: int):
        self.tool_calls.append({
            "tool": tool_name,
            "input": {k: str(v)[:100] for k, v in tool_input.items()},
            "result_len": len(result_preview),
            "latency_ms": latency_ms,
        })

    def finish(self, response: str = "", status: str = "success",
               error: str = None):
        self.response = response[:500]
        self.status = status
        self.error = error
        total_ms = int((time.time() - self._start_ts) * 1000)

        trace_doc = {
            "trace_id": self.trace_id,
            "user_id": self.user_id,
            "query": self.query,
            "response": self.response,
            "start_time": self.start_time,
            "total_ms": total_ms,
            "total_tokens": self.total_tokens,
            "rounds": self.rounds,
            "llm_calls": self.llm_calls,
            "tool_calls": self.tool_calls,
            "tool_chain": " -> ".join(tc["tool"] for tc in self.tool_calls),
            "status": self.status,
            "error": self.error,
        }

        try:
            save_trace(trace_doc)
            logger.info(
                f"[Trace] {self.trace_id} | {status} | "
                f"{self.rounds} rounds, {len(self.tool_calls)} tools, "
                f"{self.total_tokens} tokens, {total_ms}ms"
            )
        except Exception as e:
            logger.warning(f"[Trace] 持久化失败: {e}")

        return trace_doc
