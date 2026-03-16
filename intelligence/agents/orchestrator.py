"""
Orchestrator Agent — 核心 ReAct 循环
使用 OpenAI 兼容接口（支持通义千问等国产大模型）
思路：接收用户消息 → LLM 决定调用哪些工具 → 执行工具 → 返回结果 → 循环直到给出最终回复
"""
import json
from openai import OpenAI, BadRequestError
from config import LLM_API_KEY, LLM_BASE_URL, LLM_MODEL
from agents.tools import TOOLS_OPENAI, execute_tool
from agents.memory import ConversationMemory
from rag.sync import ensure_synced
from agents import monitor

MAX_TOOL_ROUNDS = 5     # 最多工具调用轮次，防止无限循环

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

    def __init__(self):
        self._client = OpenAI(api_key=LLM_API_KEY, base_url=LLM_BASE_URL)
        self.memory = ConversationMemory()
        # 启动后台 RAG 索引同步（MongoDB → ChromaDB）
        ensure_synced()
        # 启动后台 Monitor Agent（告警监控）
        monitor.start()

    def chat(self, user_message: str, on_tool_call=None) -> str:
        """
        处理一条用户消息，返回 Agent 的最终回复。
        on_tool_call: 可选回调，每次工具调用时触发，用于 UI 展示 Agent 思考过程
                      签名：on_tool_call(tool_name, tool_input, tool_result)
        """
        self.memory.add("user", user_message)

        _content_filtered = False

        for round_num in range(MAX_TOOL_ROUNDS):
            try:
                response = self._client.chat.completions.create(
                    model=LLM_MODEL,
                    max_tokens=2048,
                    messages=[
                        {"role": "system", "content": SYSTEM_PROMPT},
                        *self.memory.get(),
                    ],
                    tools=TOOLS_OPENAI,
                    # 内容审核失败后禁止再调工具，强制直接回复
                    tool_choice="none" if _content_filtered else "auto",
                )
            except BadRequestError as e:
                # 通义千问内容审核拦截 — 清理最近的工具返回并重试
                if "data_inspection_failed" in str(e):
                    self._strip_last_tool_messages()
                    _content_filtered = True
                    continue
                raise

            msg = response.choices[0].message

            # LLM 给出最终文字回复（无工具调用）
            if not msg.tool_calls:
                final_text = msg.content or ""
                self.memory.add("assistant", final_text)
                return final_text

            # LLM 请求调用工具
            # 把 LLM 的响应（含工具调用请求）加入消息历史
            self.memory.messages.append(msg.model_dump())

            # 执行所有工具调用
            for tool_call in msg.tool_calls:
                func_name = tool_call.function.name
                func_args = json.loads(tool_call.function.arguments)

                result = execute_tool(func_name, func_args)

                if on_tool_call:
                    on_tool_call(func_name, func_args, result)

                # 把工具结果返回给 LLM
                self.memory.messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": result,
                })

        return "抱歉，处理这个问题时遇到了困难，请换个方式描述。"

    def _strip_last_tool_messages(self):
        """移除最近一轮的 assistant(tool_calls) + tool 消息，避免内容审核循环触发。"""
        # 从后往前找，移除 tool 消息和对应的 assistant 消息
        while self.memory.messages and self.memory.messages[-1].get("role") == "tool":
            self.memory.messages.pop()
        # 移除触发工具调用的 assistant 消息
        if self.memory.messages and self.memory.messages[-1].get("role") == "assistant":
            self.memory.messages.pop()
        # 加一条提示让 LLM 知道工具结果被过滤了
        self.memory.add("user", "[系统提示] 上一轮工具返回的数据因包含敏感内容被过滤，请直接基于已有信息回答，或尝试其他查询方式。")

    def reset(self):
        """清空当前对话上下文。"""
        self.memory.clear()


if __name__ == "__main__":
    agent = Orchestrator()

    def show_tool_call(name, inputs, result):
        print(f"\n  [工具调用] {name}")
        print(f"  输入: {inputs}")
        print(f"  结果预览: {result[:200]}...")

    print("DHT 情报助手已启动（输入 quit 退出）\n")
    while True:
        user_input = input("你: ").strip()
        if user_input.lower() in ("quit", "exit", "q"):
            break
        if not user_input:
            continue

        reply = agent.chat(user_input, on_tool_call=show_tool_call)
        print(f"\n助手: {reply}\n")
