"""Planner 单元测试 — 测试 plan 生成、解析、执行、状态管理和 Reflect。"""
import json
from unittest.mock import MagicMock, patch

from intelligence.core.planner import Plan, Planner, StepStatus


class TestPlan:

    def test_simple_plan(self):
        plan = Plan(
            complexity="simple",
            steps=[{"id": 1, "tool": "search_dht", "args": {"query": "test"}, "depends_on": []}],
            final_instruction="直接返回搜索结果",
        )
        assert plan.is_simple
        assert not plan.all_done()

    def test_multi_step_plan(self):
        plan = Plan(
            complexity="multi_step",
            steps=[
                {"id": 1, "tool": "get_trending", "args": {"limit": 10}, "depends_on": []},
                {"id": 2, "tool": "search_hackernews",
                 "args": {"query": "test"}, "depends_on": [1]},
            ],
            final_instruction="汇总分析",
        )
        assert not plan.is_simple
        assert len(plan.steps) == 2

    def test_get_executable_steps_basic(self):
        plan = Plan(
            complexity="multi_step",
            steps=[
                {"id": 1, "tool": "get_trending", "args": {}, "depends_on": []},
                {"id": 2, "tool": "search_hackernews", "args": {}, "depends_on": [1]},
                {"id": 3, "tool": "search_reddit", "args": {}, "depends_on": [1]},
            ],
            final_instruction="",
        )

        executable = plan.get_executable_steps()
        assert len(executable) == 1
        assert executable[0]["id"] == 1

        plan.mark_success(1, '["result"]')
        executable = plan.get_executable_steps()
        assert len(executable) == 2
        assert {s["id"] for s in executable} == {2, 3}

    def test_get_executable_steps_skips_on_failed_dep(self):
        """依赖步骤失败时，下游步骤自动标记为 skipped。"""
        plan = Plan(
            complexity="multi_step",
            steps=[
                {"id": 1, "tool": "get_trending", "args": {}, "depends_on": []},
                {"id": 2, "tool": "search_hackernews", "args": {}, "depends_on": [1]},
            ],
            final_instruction="",
        )

        plan.mark_failed(1, '{"error": "timeout"}', "timeout")
        executable = plan.get_executable_steps()
        assert len(executable) == 0
        assert plan.step_status[2] == StepStatus.SKIPPED

    def test_resolve_args_with_reference(self):
        plan = Plan(
            complexity="multi_step",
            steps=[
                {"id": 1, "tool": "get_trending", "args": {"limit": 5}, "depends_on": []},
                {"id": 2, "tool": "search_hackernews",
                 "args": {"query": "{step_1.results[0].name}"}, "depends_on": [1]},
            ],
            final_instruction="",
        )

        plan.mark_success(1, json.dumps([{"name": "Ubuntu ISO"}, {"name": "Other"}]))
        resolved = plan.resolve_args(plan.steps[1])
        assert resolved["query"] == "Ubuntu ISO"

    def test_resolve_args_returns_none_on_failed_ref(self):
        """引用的步骤失败时，resolve_args 返回 None。"""
        plan = Plan(
            complexity="multi_step",
            steps=[
                {"id": 1, "tool": "get_trending", "args": {}, "depends_on": []},
                {"id": 2, "tool": "search_hackernews",
                 "args": {"query": "{step_1.results[0].name}"}, "depends_on": [1]},
            ],
            final_instruction="",
        )

        plan.mark_failed(1, '{"error": "fail"}', "fail")
        resolved = plan.resolve_args(plan.steps[1])
        assert resolved is None

    def test_resolve_args_no_reference(self):
        plan = Plan(
            complexity="simple",
            steps=[{"id": 1, "tool": "search_dht", "args": {"query": "test"}, "depends_on": []}],
            final_instruction="",
        )
        resolved = plan.resolve_args(plan.steps[0])
        assert resolved["query"] == "test"

    def test_all_done(self):
        plan = Plan(
            complexity="multi_step",
            steps=[
                {"id": 1, "tool": "search_dht", "args": {}, "depends_on": []},
                {"id": 2, "tool": "get_trending", "args": {}, "depends_on": []},
            ],
            final_instruction="",
        )
        assert not plan.all_done()
        plan.mark_success(1, "done")
        assert not plan.all_done()
        plan.mark_success(2, "done")
        assert plan.all_done()

    def test_mark_success_and_failed(self):
        plan = Plan("simple", [{"id": 1, "tool": "search_dht", "args": {}, "depends_on": []}], "")
        plan.mark_success(1, '{"data": "ok"}')
        assert plan.step_status[1] == StepStatus.SUCCESS
        assert not plan.is_step_failed(1)

        plan2 = Plan("simple", [{"id": 1, "tool": "search_dht", "args": {}, "depends_on": []}], "")
        plan2.mark_failed(1, '{"error": "bad"}', "bad")
        assert plan2.step_status[1] == StepStatus.FAILED
        assert plan2.is_step_failed(1)

    def test_add_steps(self):
        steps = [{"id": 1, "tool": "search_dht", "args": {}, "depends_on": []}]
        plan = Plan("multi_step", steps, "")
        plan.add_steps([{"id": 100, "tool": "search_reddit", "args": {"query": "补充"}}])
        assert len(plan.steps) == 2
        assert plan.steps[1]["id"] == 100

    def test_add_steps_no_duplicate(self):
        steps = [{"id": 1, "tool": "search_dht", "args": {}, "depends_on": []}]
        plan = Plan("multi_step", steps, "")
        plan.add_steps([{"id": 1, "tool": "search_dht", "args": {}}])
        assert len(plan.steps) == 1

    def test_summary_for_synthesis(self):
        plan = Plan(
            "multi_step",
            [
                {"id": 1, "tool": "search_dht", "args": {}, "depends_on": [], "purpose": "搜索"},
                {"id": 2, "tool": "get_trending", "args": {}, "depends_on": [1], "purpose": "趋势"},
            ],
            "",
        )
        plan.mark_success(1, '[{"name": "test"}]')
        plan.mark_skipped(2, "依赖失败")

        summary = plan.summary_for_synthesis()
        assert "搜索" in summary
        assert "已跳过" in summary

    def test_get_step(self):
        plan = Plan(
            complexity="simple",
            steps=[{"id": 1, "tool": "search_dht", "args": {}, "depends_on": []}],
            final_instruction="",
        )
        assert plan.get_step(1) is not None
        assert plan.get_step(99) is None


class TestPlannerParsePlan:

    def test_parse_simple_json(self):
        planner = Planner.__new__(Planner)
        planner._client = MagicMock()

        data = planner._parse_plan(json.dumps({
            "complexity": "simple",
            "steps": [{"id": 1, "tool": "search_dht", "args": {"query": "test"}}],
            "final_instruction": "返回结果",
        }))

        assert data["complexity"] == "simple"
        assert len(data["steps"]) == 1

    def test_parse_markdown_wrapped_json(self):
        planner = Planner.__new__(Planner)
        planner._client = MagicMock()

        content = '```json\n{"complexity": "simple", "steps": [], "final_instruction": ""}\n```'
        data = planner._parse_plan(content)
        assert data["complexity"] == "simple"

    def test_parse_adds_defaults(self):
        planner = Planner.__new__(Planner)
        planner._client = MagicMock()

        data = planner._parse_plan('{"steps": [{"tool": "search_dht"}]}')
        assert data["complexity"] == "simple"
        assert data["steps"][0].get("depends_on") == []
        assert data["steps"][0].get("args") == {}

    def test_parse_filters_invalid_tools(self):
        planner = Planner.__new__(Planner)
        planner._client = MagicMock()

        data = planner._parse_plan(json.dumps({
            "complexity": "multi_step",
            "steps": [
                {"id": 1, "tool": "search_dht", "args": {}},
                {"id": 2, "tool": "hack_system", "args": {}},
            ],
        }))
        assert len(data["steps"]) == 1
        assert data["steps"][0]["tool"] == "search_dht"


class TestPlannerPlan:

    @patch("intelligence.core.planner.get_client")
    def test_plan_returns_plan_object(self, mock_openai_cls):
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client

        mock_resp = MagicMock()
        mock_resp.choices = [MagicMock()]
        mock_resp.choices[0].message.content = json.dumps({
            "complexity": "multi_step",
            "steps": [
                {"id": 1, "tool": "get_trending", "args": {"limit": 10}, "depends_on": []},
                {"id": 2, "tool": "search_hackernews",
                 "args": {"query": "test"}, "depends_on": [1]},
            ],
            "final_instruction": "汇总",
        })
        mock_client.chat.completions.create.return_value = mock_resp

        planner = Planner()
        plan = planner.plan("生成情报摘要")

        assert isinstance(plan, Plan)
        assert not plan.is_simple
        assert len(plan.steps) == 2

    @patch("intelligence.core.planner.get_client")
    def test_plan_fallback_on_error(self, mock_openai_cls):
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client
        mock_client.chat.completions.create.side_effect = Exception("API error")

        planner = Planner()
        plan = planner.plan("test query")

        assert plan.is_simple
        assert plan.steps == []


class TestPlannerReflect:

    @patch("intelligence.core.planner.get_client")
    def test_reflect_sufficient(self, mock_openai_cls):
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client

        mock_resp = MagicMock()
        mock_resp.choices = [MagicMock()]
        mock_resp.choices[0].message.content = "SUFFICIENT"
        mock_client.chat.completions.create.return_value = mock_resp

        planner = Planner()
        plan = Plan(
            "multi_step",
            [{"id": 1, "tool": "search_dht", "args": {}, "depends_on": []}],
            "",
        )
        plan.mark_success(1, "some result")

        result = planner.reflect(plan, "test query")
        assert result == []

    @patch("intelligence.core.planner.get_client")
    def test_reflect_returns_supplement_steps(self, mock_openai_cls):
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client

        mock_resp = MagicMock()
        mock_resp.choices = [MagicMock()]
        mock_resp.choices[0].message.content = json.dumps([
            {"id": 100, "tool": "search_reddit", "args": {"query": "补充讨论"}, "purpose": "补充"}
        ])
        mock_client.chat.completions.create.return_value = mock_resp

        planner = Planner()
        plan = Plan(
            "multi_step",
            [{"id": 1, "tool": "search_dht", "args": {}, "depends_on": []}],
            "",
        )
        plan.mark_success(1, "some result")

        result = planner.reflect(plan, "test query")
        assert len(result) == 1
        assert result[0]["tool"] == "search_reddit"

    @patch("intelligence.core.planner.get_client")
    def test_reflect_filters_invalid_tools(self, mock_openai_cls):
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client

        mock_resp = MagicMock()
        mock_resp.choices = [MagicMock()]
        mock_resp.choices[0].message.content = json.dumps([
            {"id": 100, "tool": "hack_system", "args": {}},
            {"id": 101, "tool": "search_news", "args": {"query": "安全"}},
        ])
        mock_client.chat.completions.create.return_value = mock_resp

        planner = Planner()
        steps = [{"id": 1, "tool": "search_dht", "args": {}, "depends_on": []}]
        plan = Plan("multi_step", steps, "")
        plan.mark_success(1, "result")

        result = planner.reflect(plan, "test")
        assert len(result) == 1
        assert result[0]["tool"] == "search_news"
