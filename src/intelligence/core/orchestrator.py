"""Orchestrator Agent — 核心 ReAct 循环。"""
import json
import time
import logging
import threading
from openai import OpenAI, BadRequestError
from intelligence.config import LLM_API_KEY, LLM_BASE_URL, LLM_MODEL
from intelligence.core.tools import TOOLS_SCHEMA, execute_tool
from intelligence.core.memory import ConversationMemory, LongTermMemory
from intelligence.observability import Trace, evaluate as llm_evaluate
from intelligence.rag.sync import ensure_synced
from intelligence import monitor

logger = logging.getLogger("intelligence.orchestrator")

MAX_TOOL_ROUNDS = 5

SYSTEM_PROMPT = """你是一个 DHT 网络情报分析助手。你可以：
1. 在 DHT 数据库中搜索种子内容（search_dht）
2. 查询某个 info_hash 的详细信息（get_torrent_detail）
3. 在 HackerNews 搜索相关技术讨论（search_hackernews）
4. 在 Reddit 搜索相关帖子（search_reddit）
5. 从新闻 RSS 源搜索报道（search_news）
6. 获取最近的 DHT 热门内容（get_trending）

分析策略：
- 对于"xxx 有没有泄露"类问题：先用 search_dht 找 DHT 信号，再用 search_hackernews/search_reddit 补充背景
- 对于"最近有什么动态"类问题：用 get_trending 后再补充外部讨论
- 对于给定 hash 的调查：先 get_torrent_detail，再根据名称去外部搜索
- 综合多个来源的信息给出完整分析，注明信息来源

回答语言：中文，简洁清晰，重要信息加粗。"""


class Orchestrator:

    def __init__(self, user_id: str = "default"):
        self._client = OpenAI(api_key=LLM_API_KEY, base_url=LLM_BASE_URL)
        self.user_id = user_id
        self.memory = ConversationMemory()
        self.long_term = LongTermMemory(user_id)
        ensure_synced()
        monitor.start()

    def chat(self, user_message: str, on_tool_call=None) -> str:
        self.memory.add("user", user_message)
        trace = Trace(query=user_message, user_id=self.user_id)
        _content_filtered = False

        logger.info(f"chat 开始 | query={user_message[:80]}")

        # 注入长期记忆上下文
        long_term_ctx = self.long_term.get_context_prompt(user_message)
        system_prompt = SYSTEM_PROMPT
        if long_term_ctx:
            system_prompt += f"\n\n{long_term_ctx}"

        for round_num in range(MAX_TOOL_ROUNDS):
            try:
                llm_start = time.time()
                response = self._client.chat.completions.create(
                    model=LLM_MODEL,
                    max_tokens=2048,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        *self.memory.get(),
                    ],
                    tools=TOOLS_SCHEMA,
                    tool_choice="none" if _content_filtered else "auto",
                )
                llm_ms = int((time.time() - llm_start) * 1000)
            except BadRequestError as e:
                if "data_inspection_failed" in str(e):
                    logger.warning("LLM 内容审核拦截，清理工具消息后重试")
                    self._strip_last_tool_messages()
                    _content_filtered = True
                    continue
                raise

            usage = response.usage
            tokens = usage.total_tokens if usage else 0
            trace.add_llm_call(round_num, tokens, llm_ms)

            msg = response.choices[0].message

            if not msg.tool_calls:
                final_text = msg.content or ""
                self.memory.add("assistant", final_text)
                trace.finish(response=final_text, status="success")

                logger.info(
                    f"chat 完成 | rounds={round_num + 1} "
                    f"tools={len(trace.tool_calls)} "
                    f"tokens={trace.total_tokens}"
                )

                self._async_post_chat(trace, user_message, final_text)
                return final_text

            self.memory.messages.append(msg.model_dump())

            for tool_call in msg.tool_calls:
                func_name = tool_call.function.name
                func_args = json.loads(tool_call.function.arguments)

                tool_start = time.time()
                result = execute_tool(func_name, func_args)
                tool_ms = int((time.time() - tool_start) * 1000)

                trace.add_tool_call(func_name, func_args, result, tool_ms)
                logger.info(
                    f"tool {func_name} | args={func_args} "
                    f"result_len={len(result)} time={tool_ms}ms"
                )

                if on_tool_call:
                    on_tool_call(func_name, func_args, result)

                self.memory.messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": result,
                })

        trace.finish(status="max_rounds_exceeded")
        return "抱歉，处理这个问题时遇到了困难，请换个方式描述。"

    def _async_post_chat(self, trace: Trace, query: str, response: str):
        def _post_chat():
            text_msgs = self.memory.get_text_messages()
            if len(text_msgs) >= 4:
                try:
                    self.long_term.save_conversation(text_msgs)
                except Exception as e:
                    logger.warning(f"长期记忆存储失败: {e}")
            try:
                llm_evaluate(
                    query=query,
                    response=response,
                    tool_chain=" -> ".join(tc["tool"] for tc in trace.tool_calls),
                    trace_id=trace.trace_id,
                )
            except Exception as e:
                logger.warning(f"LLM 评估失败: {e}")

        threading.Thread(target=_post_chat, daemon=True, name="post-chat").start()

    def _strip_last_tool_messages(self):
        while self.memory.messages and self.memory.messages[-1].get("role") == "tool":
            self.memory.messages.pop()
        if self.memory.messages and self.memory.messages[-1].get("role") == "assistant":
            self.memory.messages.pop()
        self.memory.add(
            "user",
            "[系统提示] 上一轮工具返回的数据因包含敏感内容被过滤，"
            "请直接基于已有信息回答，或尝试其他查询方式。",
        )

    def reset(self):
        text_msgs = self.memory.get_text_messages()
        if len(text_msgs) >= 4:
            try:
                self.long_term.save_conversation(text_msgs)
            except Exception:
                pass
        self.memory.clear()
