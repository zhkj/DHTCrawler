"""Orchestrator Agent — Plan-Execute-Reflect 三阶段 + 多 Agent 路由。

简单查询走快速路径（原有 ReAct 单步），复杂查询自动拆解为 Plan。
执行失败时动态跳过，不会因单个工具失败导致整体失败。
"""
import json
import logging
import threading
import time

from openai import BadRequestError, OpenAI

from intelligence import monitor
from intelligence.config import LLM_API_KEY, LLM_BASE_URL, LLM_MODEL
from intelligence.core.agents import classify_intent, get_agent
from intelligence.core.guardrails import check_input, validate_tool_input
from intelligence.core.memory import ConversationMemory, LongTermMemory
from intelligence.core.planner import Plan, Planner
from intelligence.core.tools import TOOLS_SCHEMA, execute_tool
from intelligence.observability import Trace
from intelligence.observability import evaluate as llm_evaluate
from intelligence.rag.sync import ensure_synced

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
- 对于"xxx 有没有泄露"类问题：先用 search_dht 找信号，再用 search_hackernews/search_reddit 补充
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
        self.planner = Planner()
        ensure_synced()
        monitor.start()

    # ── 主入口 ────────────────────────────────────────────────────

    def chat(self, user_message: str, on_tool_call=None) -> str:
        """主对话入口：Guardrails → Plan-Execute-Reflect 流程。

        1. 输入防护检查
        2. Planner 判断复杂度
        3. 简单查询 → 直接走 ReAct 快速路径
        4. 复杂查询 → 按 Plan 多步执行 → Reflect 检查
        """
        # Guardrails: 输入防护
        is_safe, reason = check_input(user_message)
        if not is_safe:
            logger.warning(f"Guardrails 拦截 | reason={reason}")
            self.memory.add("user", user_message)
            reply = f"抱歉，您的输入被安全检查拦截：{reason}。请重新描述您的问题。"
            self.memory.add("assistant", reply)
            return reply

        self.memory.add("user", user_message)
        trace = Trace(query=user_message, user_id=self.user_id)

        logger.info(f"chat 开始 | query={user_message[:80]}")

        # 意图分类 + Agent 路由
        intent = classify_intent(user_message)
        agent_profile = get_agent(intent)
        logger.info(f"Agent 路由 | intent={intent} agent={agent_profile.name}")

        # 注入长期记忆上下文
        long_term_ctx = self.long_term.get_context_prompt(user_message)
        system_prompt = SYSTEM_PROMPT
        if agent_profile.system_prompt_extra:
            system_prompt += (
                f"\n\n[Agent 模式: {agent_profile.name}]\n"
                f"{agent_profile.system_prompt_extra}"
            )
        if long_term_ctx:
            system_prompt += f"\n\n{long_term_ctx}"

        # Planner 判断复杂度
        plan = self.planner.plan(user_message)

        if plan.is_simple or not plan.steps:
            result = self._react_loop(system_prompt, trace, on_tool_call)
        else:
            result = self._plan_execute(
                plan, system_prompt, trace, user_message, on_tool_call,
            )

        self._async_post_chat(trace, user_message, result)
        return result

    # ── Streaming 入口 ────────────────────────────────────────────

    def chat_stream(self, user_message: str, on_tool_call=None):
        """流式对话入口：逐 token 输出 + 工具调用状态推送。

        Yields:
            str: 文本 token 片段。
        """
        # Guardrails: 输入防护
        is_safe, reason = check_input(user_message)
        if not is_safe:
            logger.warning(f"Guardrails 拦截 | reason={reason}")
            yield f"抱歉，您的输入被安全检查拦截：{reason}。请重新描述您的问题。"
            return

        self.memory.add("user", user_message)
        trace = Trace(query=user_message, user_id=self.user_id)

        logger.info(f"chat_stream 开始 | query={user_message[:80]}")

        intent = classify_intent(user_message)
        agent_profile = get_agent(intent)

        long_term_ctx = self.long_term.get_context_prompt(user_message)
        system_prompt = SYSTEM_PROMPT
        if agent_profile.system_prompt_extra:
            system_prompt += (
                f"\n\n[Agent 模式: {agent_profile.name}]\n"
                f"{agent_profile.system_prompt_extra}"
            )
        if long_term_ctx:
            system_prompt += f"\n\n{long_term_ctx}"

        _content_filtered = False
        full_response = ""

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
                    stream=True,
                )

                collected_content = ""
                collected_tool_calls = {}

                for chunk in response:
                    delta = chunk.choices[0].delta if chunk.choices else None
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
                                    collected_tool_calls[idx]["name"] = tc.function.name
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
                full_response = collected_content
                self.memory.add("assistant", full_response)
                trace.finish(response=full_response, status="success")
                self._async_post_chat(trace, user_message, full_response)
                return

            assistant_msg = {"role": "assistant", "content": collected_content or None}
            assistant_msg["tool_calls"] = [
                {
                    "id": tc["id"],
                    "type": "function",
                    "function": {"name": tc["name"], "arguments": tc["arguments"]},
                }
                for tc in sorted(
                    collected_tool_calls.values(), key=lambda x: x["id"]
                )
            ]
            self.memory.messages.append(assistant_msg)

            for tc_data in collected_tool_calls.values():
                func_name = tc_data["name"]
                func_args = json.loads(tc_data["arguments"])

                # Guardrails: 工具参数校验
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
                    "content": result,
                })

        trace.finish(status="max_rounds_exceeded")
        yield "抱歉，处理这个问题时遇到了困难，请换个方式描述。"

    # ── ReAct 快速路径（简单查询） ────────────────────────────────

    def _react_loop(self, system_prompt: str, trace: Trace,
                    on_tool_call=None) -> str:
        """原有 ReAct 循环，用于简单查询的快速路径。"""
        _content_filtered = False

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
                    f"chat 完成 (ReAct) | rounds={round_num + 1} "
                    f"tools={len(trace.tool_calls)} tokens={trace.total_tokens}"
                )
                return final_text

            self.memory.messages.append(msg.model_dump())

            for tool_call in msg.tool_calls:
                func_name = tool_call.function.name
                func_args = json.loads(tool_call.function.arguments)

                # Guardrails: 工具参数校验
                func_args = validate_tool_input(func_name, func_args)

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

    # ── Plan-Execute-Reflect（复杂查询） ──────────────────────────

    def _plan_execute(self, plan: Plan, system_prompt: str, trace: Trace,
                      user_query: str, on_tool_call=None) -> str:
        """按 Plan 多步执行，支持步骤间结果引用和失败跳过。"""
        logger.info(f"Plan 执行开始 | steps={len(plan.steps)}")

        max_iterations = len(plan.steps) * 2
        iteration = 0
        while not plan.all_done() and iteration < max_iterations:
            iteration += 1
            executable = plan.get_executable_steps()
            if not executable:
                logger.warning("Plan 无可执行步骤，可能存在循环依赖")
                break

            for step in executable:
                resolved_args = plan.resolve_args(step)
                tool_name = step["tool"]

                # Guardrails: 工具参数校验
                resolved_args = validate_tool_input(tool_name, resolved_args)

                logger.info(
                    f"Plan Step {step['id']} | tool={tool_name} "
                    f"args={resolved_args} purpose={step.get('purpose', '')}"
                )

                if on_tool_call:
                    on_tool_call(tool_name, resolved_args, f"[Plan Step {step['id']}]")

                tool_start = time.time()
                result = execute_tool(tool_name, resolved_args)
                tool_ms = int((time.time() - tool_start) * 1000)

                plan.step_results[step["id"]] = result
                trace.add_tool_call(tool_name, resolved_args, result, tool_ms)

                try:
                    result_data = json.loads(result)
                    if isinstance(result_data, dict) and "error" in result_data:
                        logger.warning(
                            f"Plan Step {step['id']} 失败: "
                            f"{result_data['error']}, 继续执行"
                        )
                except json.JSONDecodeError:
                    pass

        # Reflect: 检查是否需要补充
        supplement = self.planner.reflect(plan, user_query)
        if supplement:
            logger.info(f"Reflect 建议补充: {supplement}")

        # 汇总所有结果，让 LLM 生成最终回答
        summary_parts = []
        for step in plan.steps:
            result = plan.step_results.get(step["id"], "(未执行)")
            summary_parts.append(
                f"## Step {step['id']}: {step.get('purpose', step['tool'])}\n"
                f"工具: {step['tool']}\n"
                f"结果: {result[:500]}"
            )

        synthesis_prompt = (
            f"用户原始问题: {user_query}\n\n"
            f"以下是多步执行的结果:\n\n" + "\n\n".join(summary_parts)
        )
        if plan.final_instruction:
            synthesis_prompt += f"\n\n汇总指令: {plan.final_instruction}"
        if supplement:
            synthesis_prompt += f"\n\n注意: {supplement}"

        self.memory.add("user", f"[系统: 多步执行结果汇总]\n{synthesis_prompt}")

        try:
            llm_start = time.time()
            response = self._client.chat.completions.create(
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

            final_text = response.choices[0].message.content or ""
        except Exception as e:
            logger.error(f"Plan 汇总 LLM 调用失败: {e}")
            final_text = "抱歉，在汇总分析结果时遇到了问题。"

        self.memory.add("assistant", final_text)
        trace.finish(response=final_text, status="success")

        logger.info(
            f"chat 完成 (Plan) | steps={len(plan.steps)} "
            f"tools={len(trace.tool_calls)} tokens={trace.total_tokens}"
        )
        return final_text

    # ── 辅助方法 ──────────────────────────────────────────────────

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
