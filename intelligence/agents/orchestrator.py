"""
Orchestrator Agent — 核心 ReAct 循环
思路：接收用户消息 → 让 Claude 决定调用哪些工具 → 执行工具 → 返回结果 → 循环直到 Claude 给出最终回复
"""
import anthropic
from config import ANTHROPIC_API_KEY, LLM_MODEL
from agents.tools import TOOLS, execute_tool
from agents.memory import ConversationMemory

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
        self._client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        self.memory = ConversationMemory()

    def chat(self, user_message: str, on_tool_call=None) -> str:
        """
        处理一条用户消息，返回 Agent 的最终回复。
        on_tool_call: 可选回调，每次工具调用时触发，用于 UI 展示 Agent 思考过程
                      签名：on_tool_call(tool_name, tool_input, tool_result)
        """
        self.memory.add("user", user_message)

        for round_num in range(MAX_TOOL_ROUNDS):
            response = self._client.messages.create(
                model=LLM_MODEL,
                max_tokens=2048,
                system=SYSTEM_PROMPT,
                tools=TOOLS,
                messages=self.memory.get(),
            )

            # Claude 给出最终文字回复（无工具调用）
            if response.stop_reason == "end_turn":
                final_text = response.content[0].text
                self.memory.add("assistant", final_text)
                return final_text

            # Claude 请求调用工具
            if response.stop_reason == "tool_use":
                # 把 Claude 的整个响应（含工具调用请求）加入消息历史
                self.memory.messages.append({
                    "role": "assistant",
                    "content": response.content,
                })

                # 执行所有工具调用（Claude 可能一次请求多个）
                tool_results = []
                for block in response.content:
                    if block.type != "tool_use":
                        continue

                    result = execute_tool(block.name, block.input)

                    if on_tool_call:
                        on_tool_call(block.name, block.input, result)

                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": result,
                    })

                # 把工具结果返回给 Claude
                self.memory.messages.append({
                    "role": "user",
                    "content": tool_results,
                })

        return "抱歉，处理这个问题时遇到了困难，请换个方式描述。"

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
