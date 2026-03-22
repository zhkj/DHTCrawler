"""任务规划器 — Plan-Execute-Reflect 三阶段。

将用户查询分解为多步执行计划，支持步骤间结果引用和动态跳过。
简单查询走快速路径避免过度规划，复杂查询自动拆解。
"""
import json
import logging
import re
import threading

from intelligence.config import LLM_MODEL
from intelligence.core.llm_client import get_client

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

REFLECT_PLAN_PROMPT = """你是一个任务规划器。根据用户问题和已有结果，生成补充步骤。

可用工具：
- search_dht(query, top_k): 在 DHT 数据库中语义搜索种子
- get_torrent_detail(info_hash): 查询种子详情
- search_hackernews(query, days): 搜索 HackerNews 讨论
- search_reddit(query, subreddit): 搜索 Reddit 帖子
- search_news(query): 搜索新闻 RSS
- get_trending(limit): 获取最近热门种子

输出 JSON 格式的补充步骤列表：
[{"id": 100, "tool": "工具名", "args": {"参数": "值"}, "depends_on": [], "purpose": "补充目的"}]

如果不需要补充，输出空列表 []"""

# 已知的合法工具名
_VALID_TOOLS = {
    "search_dht", "get_torrent_detail", "search_hackernews",
    "search_reddit", "search_news", "get_trending",
}


class StepStatus:
    """步骤执行状态。"""
    PENDING = "pending"
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"


class Plan:
    """执行计划数据结构。"""

    def __init__(self, complexity: str, steps: list[dict],
                 final_instruction: str):
        self.complexity = complexity
        self.steps = steps
        self.final_instruction = final_instruction
        self.step_results: dict[int, str] = {}
        self.step_status: dict[int, str] = {}  # id -> StepStatus
        self.step_errors: dict[int, str] = {}
        self._lock = threading.Lock()

    @property
    def is_simple(self) -> bool:
        return self.complexity == "simple"

    def get_step(self, step_id: int) -> dict | None:
        for step in self.steps:
            if step["id"] == step_id:
                return step
        return None

    def mark_success(self, step_id: int, result: str):
        """标记步骤成功。"""
        with self._lock:
            self.step_status[step_id] = StepStatus.SUCCESS
            self.step_results[step_id] = result

    def mark_failed(self, step_id: int, result: str, error: str):
        """标记步骤失败，保留 error 结果。"""
        with self._lock:
            self.step_status[step_id] = StepStatus.FAILED
            self.step_results[step_id] = result
            self.step_errors[step_id] = error
        logger.warning(f"Plan Step {step_id} 失败: {error}")

    def mark_skipped(self, step_id: int, reason: str):
        """标记步骤跳过（依赖失败）。"""
        with self._lock:
            self.step_status[step_id] = StepStatus.SKIPPED
            self.step_errors[step_id] = reason
            self.step_results[step_id] = json.dumps(
                {"skipped": True, "reason": reason}
            )
        logger.info(f"Plan Step {step_id} 跳过: {reason}")

    def is_step_failed(self, step_id: int) -> bool:
        return self.step_status.get(step_id) == StepStatus.FAILED

    def resolve_args(self, step: dict) -> dict:
        """解析步骤参数中的前序结果引用 {step_N.results}。

        如果引用的步骤失败/跳过，返回 None 表示应跳过当前步骤。
        """
        args = step.get("args", {})
        resolved = {}
        for key, value in args.items():
            if isinstance(value, str):
                resolved_val = self._resolve_references(value)
                if resolved_val is None:
                    return None  # 依赖失败，应跳过
                resolved[key] = resolved_val
            else:
                resolved[key] = value
        return resolved

    def _resolve_references(self, text: str) -> str | None:
        """替换文本中的 {step_N.results} 引用。

        Returns:
            解析后的文本，或 None 如果引用的步骤失败。
        """
        pattern = r'\{step_(\d+)\.results(?:\[(\d+)\])?(?:\.(\w+))?\}'

        # 先检查是否所有引用的步骤都成功
        for match in re.finditer(pattern, text):
            step_id = int(match.group(1))
            status = self.step_status.get(step_id)
            if status in (StepStatus.FAILED, StepStatus.SKIPPED):
                return None

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
                # 不截断，保留完整结果供下游使用
                if isinstance(result_data, list) and result_data:
                    return json.dumps(result_data, ensure_ascii=False)
                return result_str
            except (json.JSONDecodeError, IndexError, KeyError):
                return result_str

        return re.sub(pattern, replacer, text)

    def get_executable_steps(self) -> list[dict]:
        """获取当前可执行的步骤（依赖已满足且未执行）。

        如果依赖步骤失败，自动标记当前步骤为 skipped。
        """
        with self._lock:
            completed = set(self.step_results.keys())
            executable = []
            for step in self.steps:
                if step["id"] in completed:
                    continue
                deps = set(step.get("depends_on", []))
                if not deps.issubset(completed):
                    continue

                # 检查依赖是否全部成功
                failed_deps = [
                    d for d in deps
                    if self.step_status.get(d) in (
                        StepStatus.FAILED, StepStatus.SKIPPED,
                    )
                ]
                if failed_deps:
                    # 直接修改，已持有锁
                    self.step_status[step["id"]] = StepStatus.SKIPPED
                    self.step_errors[step["id"]] = (
                        f"依赖步骤 {failed_deps} 失败/跳过"
                    )
                    self.step_results[step["id"]] = json.dumps(
                        {"skipped": True,
                         "reason": f"依赖步骤 {failed_deps} 失败/跳过"}
                    )
                    logger.info(
                        f"Plan Step {step['id']} 跳过: "
                        f"依赖步骤 {failed_deps} 失败/跳过"
                    )
                    continue

                executable.append(step)
        return executable

    def all_done(self) -> bool:
        return len(self.step_results) == len(self.steps)

    def add_steps(self, new_steps: list[dict]):
        """动态追加补充步骤（Reflect 阶段使用）。"""
        for step in new_steps:
            if step.get("id") and not self.get_step(step["id"]):
                step.setdefault("depends_on", [])
                step.setdefault("args", {})
                step.setdefault("purpose", "")
                self.steps.append(step)

    def summary_for_synthesis(self) -> str:
        """生成汇总文本供 LLM 合成最终回答，包含状态信息。"""
        parts = []
        for step in self.steps:
            status = self.step_status.get(step["id"], "未执行")
            result = self.step_results.get(step["id"], "(未执行)")

            if status == StepStatus.SKIPPED:
                parts.append(
                    f"## Step {step['id']}: {step.get('purpose', step['tool'])}\n"
                    f"状态: 已跳过\n结果: {result}"
                )
            elif status == StepStatus.FAILED:
                parts.append(
                    f"## Step {step['id']}: {step.get('purpose', step['tool'])}\n"
                    f"状态: 执行失败\n结果: {result[:300]}"
                )
            else:
                # 成功或其他状态 — 给更多空间展示
                parts.append(
                    f"## Step {step['id']}: {step.get('purpose', step['tool'])}\n"
                    f"工具: {step['tool']}\n结果: {result[:800]}"
                )
        return "\n\n".join(parts)


class Planner:
    """任务规划器，通过一次 LLM 调用生成结构化执行计划。"""

    def __init__(self):
        self._client = get_client()

    def plan(self, user_query: str) -> Plan:
        """根据用户查询生成执行计划。"""
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

        if "complexity" not in data:
            data["complexity"] = "simple"
        if "steps" not in data:
            data["steps"] = []

        # 校验并修正每个 step
        valid_steps = []
        for idx, step in enumerate(data["steps"]):
            step.setdefault("id", idx + 1)
            step.setdefault("depends_on", [])
            step.setdefault("args", {})
            step.setdefault("purpose", "")
            # 校验工具名合法性
            if step.get("tool") in _VALID_TOOLS:
                valid_steps.append(step)
            else:
                logger.warning(
                    f"Plan 跳过非法工具: {step.get('tool')}"
                )
        data["steps"] = valid_steps

        return data

    def mid_reflect(self, plan: Plan, user_query: str,
                    just_completed: list[int]) -> list[dict]:
        """执行中反思：根据刚完成步骤的结果，判断是否需要调整后续计划。

        与 reflect() 不同，mid_reflect 在执行过程中调用，可以根据中间结果
        动态补充步骤（如搜索为空时切换策略）。

        Args:
            plan: 当前执行计划。
            user_query: 用户原始问题。
            just_completed: 刚完成的步骤 ID 列表。

        Returns:
            补充步骤列表，空列表表示无需调整。
        """
        # 只在有步骤失败或返回空结果时触发
        needs_reflect = False
        for step_id in just_completed:
            status = plan.step_status.get(step_id)
            if status in (StepStatus.FAILED, StepStatus.SKIPPED):
                needs_reflect = True
                break
            result = plan.step_results.get(step_id, "")
            try:
                data = json.loads(result)
                if isinstance(data, list) and len(data) == 0:
                    needs_reflect = True
                    break
                if isinstance(data, dict) and "error" in data:
                    needs_reflect = True
                    break
            except (json.JSONDecodeError, TypeError):
                pass

        if not needs_reflect:
            return []

        # 构建中间状态摘要
        completed_summary = []
        for step in plan.steps:
            sid = step["id"]
            status = plan.step_status.get(sid)
            if status is None:
                completed_summary.append(
                    f"Step {sid} ({step['tool']}): 待执行"
                )
            else:
                result = plan.step_results.get(sid, "")
                preview = result[:200] if result else "(无结果)"
                completed_summary.append(
                    f"Step {sid} ({step['tool']}) [{status}]: {preview}"
                )

        prompt = (
            f"用户问题: {user_query}\n\n"
            f"当前执行状态:\n" + "\n".join(completed_summary) + "\n\n"
            "部分步骤失败或返回空结果。请判断是否需要补充替代步骤来弥补信息缺口。\n"
            "如果不需要，回复: SUFFICIENT\n"
            "如果需要，输出补充步骤的 JSON 列表（使用不同的工具或参数）"
        )

        try:
            response = self._client.chat.completions.create(
                model=LLM_MODEL,
                max_tokens=500,
                temperature=0,
                messages=[
                    {"role": "system", "content": REFLECT_PLAN_PROMPT},
                    {"role": "user", "content": prompt},
                ],
            )
            content = response.choices[0].message.content or ""
            if content.strip().startswith("SUFFICIENT"):
                return []
            return self._parse_supplement_steps(content, plan)
        except Exception as e:
            logger.warning(f"Mid-Reflect 失败: {e}")
            return []

    def reflect(self, plan: Plan, user_query: str) -> list[dict]:
        """执行完成后反思：检查是否需要补充，返回补充步骤列表。

        Returns:
            补充步骤列表（可直接 add_steps），空列表表示无需补充。
        """
        results_summary = []
        for step in plan.steps:
            status = plan.step_status.get(step["id"], "unknown")
            result = plan.step_results.get(step["id"], "")
            preview = result[:300] if result else "(无结果)"
            results_summary.append(
                f"Step {step['id']} ({step['tool']}) "
                f"[{status}]: {preview}"
            )

        prompt = (
            f"用户问题: {user_query}\n\n"
            f"已执行步骤结果:\n" + "\n".join(results_summary) + "\n\n"
            "请判断：这些结果是否足以回答用户问题？\n"
            "如果足够，回复: SUFFICIENT\n"
            "如果需要补充，输出补充步骤的 JSON 列表"
        )

        try:
            response = self._client.chat.completions.create(
                model=LLM_MODEL,
                max_tokens=500,
                temperature=0,
                messages=[
                    {"role": "system", "content": REFLECT_PLAN_PROMPT},
                    {"role": "user", "content": prompt},
                ],
            )
            content = response.choices[0].message.content or ""
            if content.strip().startswith("SUFFICIENT"):
                return []

            # 尝试解析补充步骤
            return self._parse_supplement_steps(content, plan)

        except Exception as e:
            logger.warning(f"Reflect 失败: {e}")
            return []

    def _parse_supplement_steps(self, content: str, plan: Plan) -> list[dict]:
        """解析 Reflect 返回的补充步骤。"""
        try:
            # 从 markdown block 或直接 JSON 解析
            json_match = re.search(r'```(?:json)?\s*([\s\S]*?)```', content)
            if json_match:
                content = json_match.group(1)

            bracket_start = content.find('[')
            if bracket_start < 0:
                return []

            # 找匹配的 ]
            depth = 0
            for i in range(bracket_start, len(content)):
                if content[i] == '[':
                    depth += 1
                elif content[i] == ']':
                    depth -= 1
                    if depth == 0:
                        content = content[bracket_start:i + 1]
                        break

            steps = json.loads(content)
            if not isinstance(steps, list):
                return []

            max_id = max((s["id"] for s in plan.steps), default=0)
            valid = []
            for step in steps:
                if not isinstance(step, dict):
                    continue
                if step.get("tool") not in _VALID_TOOLS:
                    continue
                step.setdefault("id", max_id + 1 + len(valid))
                step.setdefault("depends_on", [])
                step.setdefault("args", {})
                step.setdefault("purpose", "补充信息")
                valid.append(step)

            return valid

        except (json.JSONDecodeError, ValueError):
            return []
