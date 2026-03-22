"""Orchestrator Agent — Plan-Execute-Reflect 三阶段 + 多 Agent 路由。

简单查询走快速路径（原有 ReAct 单步），复杂查询自动拆解为 Plan。
执行失败时动态跳过，不会因单个工具失败导致整体失败。
支持语义缓存、输出防护、Streaming Plan 模式。
"""
import json
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from openai import APITimeoutError, BadRequestError, RateLimitError

from intelligence import monitor
from intelligence.config import LLM_MODEL
from intelligence.core.agents import classify_intent, get_agent
from intelligence.core.cache import TokenTracker, cache_lookup, cache_store
from intelligence.core.guardrails import (
    check_input,
    check_output,
    validate_tool_input,
)
from intelligence.core.llm_client import get_client
from intelligence.core.memory import ConversationMemory, LongTermMemory
from intelligence.core.planner import Plan, Planner
from intelligence.core.tools import execute_tool
from intelligence.observability import Trace
from intelligence.observability import evaluate as llm_evaluate
from intelligence.rag.sync import ensure_synced

logger = logging.getLogger("intelligence.orchestrator")

MAX_TOOL_ROUNDS = 5
MAX_TOOL_RESULT_CHARS = 3000


def _cap_tool_result(result: str, max_chars: int = MAX_TOOL_RESULT_CHARS) -> str:
    """截断过长的工具结果，避免占满上下文窗口。"""
    if len(result) <= max_chars:
        return result
    return result[:max_chars] + "...(truncated)"


SYSTEM_PROMPT = """\
你是一个 DHT 网络情报分析助手。你可以：
1. 在 DHT 数据库中搜索种子内容（search_dht）
2. 查询某个 info_hash 的详细信息（get_torrent_detail）
3. 在 HackerNews 搜索相关技术讨论（search_hackernews）
4. 在 Reddit 搜索相关帖子（search_reddit）
5. 从新闻 RSS 源搜索报道（search_news）
6. 获取最近的 DHT 热门内容（get_trending）

分析策略：
- "xxx 有没有泄露"→ search_dht + search_hackernews/search_reddit 补充
- "最近有什么动态"→ get_trending + 外部讨论补充
- 给定 hash → get_torrent_detail + 外部搜索
- 综合多个来源信息给出完整分析，注明信息来源

回答语言：中文，简洁清晰，重要信息加粗。"""


class Orchestrator:

    def __init__(self, user_id: str = "default"):
        self._client = get_client()
        self.user_id = user_id
        self.memory = ConversationMemory()
        self.long_term = LongTermMemory(user_id)
        self.planner = Planner()
        self.token_tracker = TokenTracker()
        ensure_synced()
        monitor.start()

    def _llm_create(self, **kwargs):
        """LLM API 调用，带重试。"""
        max_retries = 3
        for attempt in range(max_retries + 1):
            try:
                return self._client.chat.completions.create(**kwargs)
            except (RateLimitError, APITimeoutError) as e:
                if attempt == max_retries:
                    raise
                wait = min(2 ** attempt * 2, 30)
                logger.warning(
                    "%s, %ds 后重试 (attempt %d/%d)",
                    type(e).__name__, wait, attempt + 1, max_retries,
                )
                time.sleep(wait)
        return None

    # ── 主入口 ────────────────────────────────────────────────────

    def chat(self, user_message: str, on_tool_call=None) -> str:
        """主对话入口：Cache → Guardrails → Plan-Execute-Reflect。"""
        # Guardrails: 输入防护
        is_safe, reason = check_input(user_message)
        if not is_safe:
            logger.warning(f"Guardrails 拦截 | reason={reason}")
            self.memory.add("user", user_message)
            reply = f"抱歉，您的输入被安全检查拦截：{reason}。请重新描述您的问题。"
            self.memory.add("assistant", reply)
            return reply

        # Build context from recent conversation
        _cache_ctx = ""
        recent = self.memory.get_text_messages()[-2:]
        if recent:
            _cache_ctx = " ".join(
                m.get("content", "")[:100] for m in recent
            )

        # 语义缓存: 查询
        cached = cache_lookup(user_message, context=_cache_ctx)
        if cached:
            logger.info("语义缓存命中，直接返回")
            self.memory.add("user", user_message)
            self.memory.add("assistant", cached)
            return cached

        self.memory.add("user", user_message)
        trace = Trace(query=user_message, user_id=self.user_id)

        logger.info(f"chat 开始 | query={user_message[:80]}")

        # 意图分类 + Agent 路由
        intent = classify_intent(user_message)
        agent_profile = get_agent(intent)
        tools_schema = agent_profile.filter_tools_schema()
        logger.info(
            f"Agent 路由 | intent={intent} agent={agent_profile.name} "
            f"tools={len(tools_schema)}"
        )

        # 构建 system prompt
        system_prompt = self._build_system_prompt(
            agent_profile, user_message,
        )

        # Planner 判断复杂度
        plan = self.planner.plan(user_message)

        if plan.is_simple or not plan.steps:
            result = self._react_loop(
                system_prompt, tools_schema, trace, on_tool_call,
            )
        else:
            result = self._plan_execute(
                plan, system_prompt, tools_schema, trace,
                user_message, on_tool_call,
            )

        # Guardrails: 输出防护
        result = check_output(result, trace.tool_calls or None)

        # 语义缓存: 存储
        cache_store(user_message, result, context=_cache_ctx)

        self._async_post_chat(trace, user_message, result)
        return result

    # ── Streaming 入口 ────────────────────────────────────────────

    def chat_stream(self, user_message: str, on_tool_call=None):
        """流式对话入口：支持 Plan 模式 + 逐 token 输出。

        Yields:
            str: 文本 token 片段。
        """
        # Guardrails: 输入防护
        is_safe, reason = check_input(user_message)
        if not is_safe:
            logger.warning(f"Guardrails 拦截 | reason={reason}")
            yield f"抱歉，您的输入被安全检查拦截：{reason}。请重新描述您的问题。"
            return

        # Build context from recent conversation
        _cache_ctx = ""
        recent = self.memory.get_text_messages()[-2:]
        if recent:
            _cache_ctx = " ".join(
                m.get("content", "")[:100] for m in recent
            )

        # 语义缓存: 查询
        cached = cache_lookup(user_message, context=_cache_ctx)
        if cached:
            logger.info("语义缓存命中 (stream)")
            self.memory.add("user", user_message)
            self.memory.add("assistant", cached)
            yield cached
            return

        self.memory.add("user", user_message)
        trace = Trace(query=user_message, user_id=self.user_id)

        logger.info(f"chat_stream 开始 | query={user_message[:80]}")

        intent = classify_intent(user_message)
        agent_profile = get_agent(intent)
        tools_schema = agent_profile.filter_tools_schema()
        system_prompt = self._build_system_prompt(
            agent_profile, user_message,
        )

        # Planner 判断复杂度
        plan = self.planner.plan(user_message)

        if plan.is_simple or not plan.steps:
            # 简单查询: 流式 ReAct
            yield from self._stream_react_loop(
                system_prompt, tools_schema, trace,
                user_message, on_tool_call,
            )
        else:
            # 复杂查询: 先执行 Plan（非流式），最终合成流式输出
            yield from self._stream_plan_execute(
                plan, system_prompt, tools_schema, trace,
                user_message, on_tool_call,
            )

    # ── 流式 ReAct ────────────────────────────────────────────────

    def _stream_react_loop(self, system_prompt, tools_schema, trace,
                           user_message, on_tool_call=None):
        """流式 ReAct 循环。"""
        _content_filtered = False

        for round_num in range(MAX_TOOL_ROUNDS):
            try:
                llm_start = time.time()
                response = self._llm_create(
                    model=LLM_MODEL,
                    max_tokens=2048,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        *self.memory.get(),
                    ],
                    tools=tools_schema,
                    tool_choice="none" if _content_filtered else "auto",
                    stream=True,
                )

                collected_content = ""
                collected_tool_calls = {}

                for chunk in response:
                    delta = (
                        chunk.choices[0].delta if chunk.choices else None
                    )
                    if delta is None:
                        continue

                    if delta.content:
                        collected_content += delta.content
                        yield delta.content

                    if delta.tool_calls:
                        for tc in delta.tool_calls:
                            idx = tc.index
                            if idx not in collected_tool_calls:
                                collected_tool_calls[idx] = {
                                    "id": tc.id or "",
                                    "name": (
                                        tc.function.name
                                        if tc.function and tc.function.name
                                        else ""
                                    ),
                                    "arguments": "",
                                }
                            if tc.id:
                                collected_tool_calls[idx]["id"] = tc.id
                            if tc.function:
                                if tc.function.name:
                                    collected_tool_calls[idx]["name"] = (
                                        tc.function.name
                                    )
                                if tc.function.arguments:
                                    collected_tool_calls[idx]["arguments"] += (
                                        tc.function.arguments
                                    )

                llm_ms = int((time.time() - llm_start) * 1000)
                trace.add_llm_call(round_num, 0, llm_ms)

            except BadRequestError as e:
                if "data_inspection_failed" in str(e):
                    self._strip_last_tool_messages()
                    _content_filtered = True
                    continue
                raise

            if not collected_tool_calls:
                full_response = check_output(
                    collected_content, trace.tool_calls or None,
                )
                self.memory.add("assistant", full_response)
                trace.finish(response=full_response, status="success")
                cache_store(user_message, full_response)
                self._async_post_chat(trace, user_message, full_response)
                return

            # 有工具调用 → 执行后继续
            self._append_stream_tool_calls(
                collected_content, collected_tool_calls,
            )
            self._execute_stream_tools(
                collected_tool_calls, tools_schema, trace, on_tool_call,
            )

        trace.finish(status="max_rounds_exceeded")
        yield "抱歉，处理这个问题时遇到了困难，请换个方式描述。"

    # ── 流式 Plan 执行 ───────────────────────────────────────────

    def _stream_plan_execute(self, plan, system_prompt, tools_schema,
                             trace, user_query, on_tool_call=None):
        """Plan 模式流式输出：先执行 Plan，最终合成阶段流式。"""
        # Plan 执行阶段（非流式，因为需要收集结果）
        self._run_plan_steps(plan, trace, on_tool_call,
                             user_query=user_query)

        # Reflect + 补充执行
        supplement_steps = self.planner.reflect(plan, user_query)
        if supplement_steps:
            logger.info(
                f"Reflect 补充 {len(supplement_steps)} 个步骤"
            )
            plan.add_steps(supplement_steps)
            self._run_plan_steps(plan, trace, on_tool_call,
                                 user_query=user_query)

        # 合成阶段 — 流式输出最终回答
        synthesis_prompt = (
            f"用户原始问题: {user_query}\n\n"
            f"以下是多步执行的结果:\n\n"
            f"{plan.summary_for_synthesis()}"
        )
        if plan.final_instruction:
            synthesis_prompt += f"\n\n汇总指令: {plan.final_instruction}"

        self.memory.add(
            "user", f"[系统: 多步执行结果汇总]\n{synthesis_prompt}",
        )

        try:
            llm_start = time.time()
            response = self._llm_create(
                model=LLM_MODEL,
                max_tokens=2048,
                messages=[
                    {"role": "system", "content": system_prompt},
                    *self.memory.get(),
                ],
                stream=True,
            )

            full_text = ""
            for chunk in response:
                delta = chunk.choices[0].delta if chunk.choices else None
                if delta and delta.content:
                    full_text += delta.content
                    yield delta.content

            llm_ms = int((time.time() - llm_start) * 1000)
            trace.add_llm_call(len(plan.steps), 0, llm_ms)

        except Exception as e:
            logger.error(f"Plan 汇总 LLM 调用失败: {e}")
            full_text = "抱歉，在汇总分析结果时遇到了问题。"
            yield full_text

        full_text = check_output(full_text, trace.tool_calls or None)
        self.memory.add("assistant", full_text)
        trace.finish(response=full_text, status="success")
        cache_store(user_query, full_text)
        self._async_post_chat(trace, user_query, full_text)

    # ── ReAct 快速路径（非流式） ──────────────────────────────────

    def _react_loop(self, system_prompt, tools_schema, trace,
                    on_tool_call=None) -> str:
        """原有 ReAct 循环，用于简单查询的快速路径。"""
        _content_filtered = False

        for round_num in range(MAX_TOOL_ROUNDS):
            try:
                llm_start = time.time()
                response = self._llm_create(
                    model=LLM_MODEL,
                    max_tokens=2048,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        *self.memory.get(),
                    ],
                    tools=tools_schema,
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
            self.token_tracker.track(usage)

            msg = response.choices[0].message

            if not msg.tool_calls:
                final_text = msg.content or ""
                self.memory.add("assistant", final_text)
                trace.finish(response=final_text, status="success")
                logger.info(
                    f"chat 完成 (ReAct) | rounds={round_num + 1} "
                    f"tools={len(trace.tool_calls)} "
                    f"tokens={trace.total_tokens}"
                )
                return final_text

            self.memory.messages.append(msg.model_dump())

            for tool_call in msg.tool_calls:
                func_name = tool_call.function.name
                func_args = json.loads(tool_call.function.arguments)
                func_args = validate_tool_input(func_name, func_args)

                tool_start = time.time()
                result = execute_tool(func_name, func_args)
                tool_ms = int((time.time() - tool_start) * 1000)

                trace.add_tool_call(
                    func_name, func_args, result, tool_ms,
                )
                logger.info(
                    f"tool {func_name} | args={func_args} "
                    f"result_len={len(result)} time={tool_ms}ms"
                )

                if on_tool_call:
                    on_tool_call(func_name, func_args, result)

                self.memory.messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": _cap_tool_result(result),
                })

        trace.finish(status="max_rounds_exceeded")
        return "抱歉，处理这个问题时遇到了困难，请换个方式描述。"

    # ── Plan-Execute-Reflect（非流式） ────────────────────────────

    def _plan_execute(self, plan, system_prompt, tools_schema, trace,
                      user_query, on_tool_call=None) -> str:
        """按 Plan 多步执行，支持步骤间结果引用和失败跳过。"""
        logger.info(f"Plan 执行开始 | steps={len(plan.steps)}")

        self._run_plan_steps(plan, trace, on_tool_call,
                             user_query=user_query)

        # Reflect: 检查是否需要补充，返回可执行的补充步骤
        supplement_steps = self.planner.reflect(plan, user_query)
        if supplement_steps:
            logger.info(
                f"Reflect 补充 {len(supplement_steps)} 个步骤"
            )
            plan.add_steps(supplement_steps)
            self._run_plan_steps(plan, trace, on_tool_call,
                                 user_query=user_query)

        # 汇总所有结果，让 LLM 生成最终回答
        synthesis_prompt = (
            f"用户原始问题: {user_query}\n\n"
            f"以下是多步执行的结果:\n\n"
            f"{plan.summary_for_synthesis()}"
        )
        if plan.final_instruction:
            synthesis_prompt += f"\n\n汇总指令: {plan.final_instruction}"

        self.memory.add(
            "user", f"[系统: 多步执行结果汇总]\n{synthesis_prompt}",
        )

        try:
            llm_start = time.time()
            response = self._llm_create(
                model=LLM_MODEL,
                max_tokens=2048,
                messages=[
                    {"role": "system", "content": system_prompt},
                    *self.memory.get(),
                ],
            )
            llm_ms = int((time.time() - llm_start) * 1000)
            usage = response.usage
            tokens = usage.total_tokens if usage else 0
            trace.add_llm_call(len(plan.steps), tokens, llm_ms)
            self.token_tracker.track(usage)

            final_text = response.choices[0].message.content or ""
        except Exception as e:
            logger.error(f"Plan 汇总 LLM 调用失败: {e}")
            final_text = "抱歉，在汇总分析结果时遇到了问题。"

        self.memory.add("assistant", final_text)
        trace.finish(response=final_text, status="success")

        logger.info(
            f"chat 完成 (Plan) | steps={len(plan.steps)} "
            f"tools={len(trace.tool_calls)} "
            f"tokens={trace.total_tokens}"
        )
        return final_text

    # ── Plan 步骤执行引擎 ─────────────────────────────────────────

    def _run_plan_steps(self, plan: Plan, trace: Trace,
                        on_tool_call=None, user_query: str = ""):
        """执行 Plan 中所有待执行步骤，支持并发、失败跳过和动态重规划。"""
        max_iterations = len(plan.steps) * 2 + 3  # extra room for supplements
        iteration = 0
        while not plan.all_done() and iteration < max_iterations:
            iteration += 1
            executable = plan.get_executable_steps()
            if not executable:
                break

            just_completed_ids = [s["id"] for s in executable]

            # 多个无依赖步骤并发执行
            if len(executable) > 1:
                self._execute_steps_concurrent(
                    plan, executable, trace, on_tool_call,
                )
            else:
                self._execute_step(
                    plan, executable[0], trace, on_tool_call,
                )

            # 动态重规划：中间步骤失败或为空时尝试补充
            if user_query and not plan.all_done():
                supplements = self.planner.mid_reflect(
                    plan, user_query, just_completed_ids,
                )
                if supplements:
                    logger.info(
                        f"Mid-Reflect 补充 {len(supplements)} 个步骤"
                    )
                    plan.add_steps(supplements)

    def _execute_step(self, plan: Plan, step: dict, trace: Trace,
                      on_tool_call=None):
        """执行单个 Plan 步骤。"""
        resolved_args = plan.resolve_args(step)

        # 依赖步骤失败导致参数无法解析 → 跳过
        if resolved_args is None:
            plan.mark_skipped(
                step["id"], "参数引用的前序步骤失败",
            )
            return

        tool_name = step["tool"]
        resolved_args = validate_tool_input(tool_name, resolved_args)

        logger.info(
            f"Plan Step {step['id']} | tool={tool_name} "
            f"args={resolved_args} purpose={step.get('purpose', '')}"
        )

        if on_tool_call:
            on_tool_call(
                tool_name, resolved_args,
                f"[Plan Step {step['id']}]",
            )

        tool_start = time.time()
        result = execute_tool(tool_name, resolved_args)
        tool_ms = int((time.time() - tool_start) * 1000)

        trace.add_tool_call(tool_name, resolved_args, result, tool_ms)

        # 判断是否执行失败
        try:
            result_data = json.loads(result)
            if isinstance(result_data, dict) and "error" in result_data:
                plan.mark_failed(
                    step["id"], result, result_data["error"],
                )
                return
        except json.JSONDecodeError:
            pass

        plan.mark_success(step["id"], result)

    def _execute_steps_concurrent(self, plan: Plan, steps: list[dict],
                                  trace: Trace, on_tool_call=None):
        """并发执行多个无依赖的 Plan 步骤。"""
        with ThreadPoolExecutor(max_workers=min(len(steps), 4)) as pool:
            futures = {
                pool.submit(
                    self._execute_step, plan, step, trace, on_tool_call,
                ): step
                for step in steps
            }
            for future in as_completed(futures):
                step = futures[future]
                try:
                    future.result()
                except Exception as e:
                    plan.mark_failed(
                        step["id"],
                        json.dumps({"error": str(e)}),
                        str(e),
                    )

    # ── Streaming 辅助方法 ────────────────────────────────────────

    def _append_stream_tool_calls(self, content, collected_tool_calls):
        """将流式收集的工具调用追加到 memory。"""
        assistant_msg = {
            "role": "assistant",
            "content": content or None,
            "tool_calls": [
                {
                    "id": tc["id"],
                    "type": "function",
                    "function": {
                        "name": tc["name"],
                        "arguments": tc["arguments"],
                    },
                }
                for tc in sorted(
                    collected_tool_calls.values(),
                    key=lambda x: x["id"],
                )
            ],
        }
        self.memory.messages.append(assistant_msg)

    def _execute_stream_tools(self, collected_tool_calls, tools_schema,
                              trace, on_tool_call=None):
        """执行流式模式中收集到的工具调用。"""
        for tc_data in collected_tool_calls.values():
            func_name = tc_data["name"]
            func_args = json.loads(tc_data["arguments"])
            func_args = validate_tool_input(func_name, func_args)

            tool_start = time.time()
            result = execute_tool(func_name, func_args)
            tool_ms = int((time.time() - tool_start) * 1000)

            trace.add_tool_call(func_name, func_args, result, tool_ms)

            if on_tool_call:
                on_tool_call(func_name, func_args, result)

            self.memory.messages.append({
                "role": "tool",
                "tool_call_id": tc_data["id"],
                "content": _cap_tool_result(result),
            })

    # ── 通用辅助方法 ──────────────────────────────────────────────

    def _build_system_prompt(self, agent_profile, user_message: str) -> str:
        """构建带有 Agent 模式和长期记忆的 system prompt。"""
        system_prompt = SYSTEM_PROMPT
        if agent_profile.system_prompt_extra:
            system_prompt += (
                f"\n\n[Agent 模式: {agent_profile.name}]\n"
                f"{agent_profile.system_prompt_extra}"
            )
        long_term_ctx = self.long_term.get_context_prompt(user_message)
        if long_term_ctx:
            system_prompt += f"\n\n{long_term_ctx}"
        return system_prompt

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
                    tool_chain=" -> ".join(
                        tc["tool"] for tc in trace.tool_calls
                    ),
                    trace_id=trace.trace_id,
                )
            except Exception as e:
                logger.warning(f"LLM 评估失败: {e}")

        threading.Thread(
            target=_post_chat, daemon=True, name="post-chat",
        ).start()

    def _strip_last_tool_messages(self):
        while (self.memory.messages
               and self.memory.messages[-1].get("role") == "tool"):
            self.memory.messages.pop()
        if (self.memory.messages
                and self.memory.messages[-1].get("role") == "assistant"):
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
