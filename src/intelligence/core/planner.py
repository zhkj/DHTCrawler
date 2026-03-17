"""任务规划器 — Plan-Execute-Reflect 三阶段。

将用户查询分解为多步执行计划，支持步骤间结果引用和动态跳过。
简单查询走快速路径避免过度规划，复杂查询自动拆解。
"""
import json
import logging
import re

from openai import OpenAI

from intelligence.config import LLM_API_KEY, LLM_BASE_URL, LLM_MODEL

logger = logging.getLogger("intelligence.core.planner")

PLAN_PROMPT = """你是一个任务规划器。根据用户查询，判断查询复杂度并生成执行计划。

可用工具：
- search_dht(query, top_k): 在 DHT 数据库中语义搜索种子
- get_torrent_detail(info_hash): 查询种子详情
- search_hackernews(query, days): 搜索 HackerNews 讨论
- search_reddit(query, subreddit): 搜索 Reddit 帖子
- search_news(query): 搜索新闻 RSS
- get_trending(limit): 获取最近热门种子

规则：
1. 如果查询可以用 1 个工具直接回答，返回 complexity="simple"
2. 如果需要多个工具配合，返回 complexity="multi_step" 并给出步骤
3. 步骤间可以用 {step_N.results} 引用前序步骤的结果
4. depends_on 表示该步骤依赖哪些前序步骤完成

严格输出 JSON，不要有其他文字：
{
  "complexity": "simple" | "multi_step",
  "steps": [
    {"id": 1, "tool": "工具名", "args": {"参数": "值"}, "depends_on": [], "purpose": "目的说明"}
  ],
  "final_instruction": "如何汇总这些结果生成最终回答"
}

对于 simple 类型，steps 只包含 1 个步骤。"""


class Plan:
    """执行计划数据结构。"""

    def __init__(self, complexity: str, steps: list[dict], final_instruction: str):
        self.complexity = complexity
        self.steps = steps
        self.final_instruction = final_instruction
        self.step_results: dict[int, str] = {}

    @property
    def is_simple(self) -> bool:
        return self.complexity == "simple"

    def get_step(self, step_id: int) -> dict | None:
        for step in self.steps:
            if step["id"] == step_id:
                return step
        return None

    def resolve_args(self, step: dict) -> dict:
        """解析步骤参数中的前序结果引用 {step_N.results}。"""
        args = step.get("args", {})
        resolved = {}
        for key, value in args.items():
            if isinstance(value, str):
                resolved[key] = self._resolve_references(value)
            else:
                resolved[key] = value
        return resolved

    def _resolve_references(self, text: str) -> str:
        """替换文本中的 {step_N.results} 引用。"""
        pattern = r'\{step_(\d+)\.results(?:\[(\d+)\])?(?:\.(\w+))?\}'

        def replacer(match):
            step_id = int(match.group(1))
            index = match.group(2)
            field = match.group(3)

            result_str = self.step_results.get(step_id, "")
            if not result_str:
                return match.group(0)

            try:
                result_data = json.loads(result_str)
                if index is not None and isinstance(result_data, list):
                    item = result_data[int(index)]
                    if field and isinstance(item, dict):
                        return str(item.get(field, ""))
                    return str(item) if not isinstance(item, str) else item
                return result_str[:200]
            except (json.JSONDecodeError, IndexError, KeyError):
                return result_str[:200]

        return re.sub(pattern, replacer, text)

    def get_executable_steps(self) -> list[dict]:
        """获取当前可执行的步骤（依赖已满足且未执行）。"""
        executed = set(self.step_results.keys())
        executable = []
        for step in self.steps:
            if step["id"] in executed:
                continue
            deps = set(step.get("depends_on", []))
            if deps.issubset(executed):
                executable.append(step)
        return executable

    def all_done(self) -> bool:
        return len(self.step_results) == len(self.steps)


class Planner:
    """任务规划器，通过一次 LLM 调用生成结构化执行计划。"""

    def __init__(self):
        self._client = OpenAI(api_key=LLM_API_KEY, base_url=LLM_BASE_URL)

    def plan(self, user_query: str) -> Plan:
        """根据用户查询生成执行计划。

        Args:
            user_query: 用户输入的查询文本。

        Returns:
            Plan 对象，包含复杂度判断和步骤列表。
        """
        try:
            response = self._client.chat.completions.create(
                model=LLM_MODEL,
                max_tokens=1024,
                temperature=0,
                messages=[
                    {"role": "system", "content": PLAN_PROMPT},
                    {"role": "user", "content": user_query},
                ],
            )
            content = response.choices[0].message.content or ""
            plan_data = self._parse_plan(content)
            logger.info(
                f"Plan 生成 | complexity={plan_data['complexity']} "
                f"steps={len(plan_data['steps'])}"
            )
            return Plan(
                complexity=plan_data["complexity"],
                steps=plan_data["steps"],
                final_instruction=plan_data.get("final_instruction", ""),
            )
        except Exception as e:
            logger.warning(f"Plan 生成失败，回退到 simple: {e}")
            return Plan(complexity="simple", steps=[], final_instruction="")

    def _parse_plan(self, content: str) -> dict:
        """解析 LLM 返回的 JSON 计划。"""
        # 尝试从 markdown code block 中提取 JSON
        json_match = re.search(r'```(?:json)?\s*([\s\S]*?)```', content)
        if json_match:
            content = json_match.group(1)

        # 尝试直接找 JSON 对象
        brace_start = content.find('{')
        if brace_start >= 0:
            # 找到匹配的最后一个 }
            depth = 0
            for i in range(brace_start, len(content)):
                if content[i] == '{':
                    depth += 1
                elif content[i] == '}':
                    depth -= 1
                    if depth == 0:
                        content = content[brace_start:i + 1]
                        break

        data = json.loads(content)

        # 校验必须字段
        if "complexity" not in data:
            data["complexity"] = "simple"
        if "steps" not in data:
            data["steps"] = []

        # 确保每个 step 有必需字段
        for step in data["steps"]:
            step.setdefault("id", data["steps"].index(step) + 1)
            step.setdefault("depends_on", [])
            step.setdefault("args", {})
            step.setdefault("purpose", "")

        return data

    def reflect(self, plan: Plan, user_query: str) -> str | None:
        """执行完成后反思：检查是否需要补充信息。

        Args:
            plan: 已执行完成的计划。
            user_query: 原始用户查询。

        Returns:
            补充指令字符串，或 None 表示无需补充。
        """
        results_summary = []
        for step in plan.steps:
            result = plan.step_results.get(step["id"], "")
            result_preview = result[:200] if result else "(无结果)"
            results_summary.append(
                f"Step {step['id']} ({step['tool']}): {result_preview}"
            )

        prompt = (
            f"用户问题: {user_query}\n\n"
            f"已执行步骤结果:\n" + "\n".join(results_summary) + "\n\n"
            "请判断：这些结果是否足以回答用户问题？\n"
            "如果足够，回复: SUFFICIENT\n"
            "如果需要补充，回复: NEED_MORE: <具体说明需要什么信息>"
        )

        try:
            response = self._client.chat.completions.create(
                model=LLM_MODEL,
                max_tokens=200,
                temperature=0,
                messages=[{"role": "user", "content": prompt}],
            )
            content = response.choices[0].message.content or ""
            if content.strip().startswith("SUFFICIENT"):
                return None
            if content.strip().startswith("NEED_MORE:"):
                return content.split("NEED_MORE:", 1)[1].strip()
        except Exception as e:
            logger.warning(f"Reflect 失败: {e}")

        return None
