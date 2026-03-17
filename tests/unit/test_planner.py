"""Planner 单元测试 — 测试 plan 生成、解析、执行和 Reflect。"""
import json
from unittest.mock import patch, MagicMock
import pytest
from intelligence.core.planner import Plan, Planner


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
                {"id": 2, "tool": "search_hackernews", "args": {"query": "test"}, "depends_on": [1]},
            ],
            final_instruction="汇总分析",
        )
        assert not plan.is_simple
        assert len(plan.steps) == 2

    def test_get_executable_steps(self):
        plan = Plan(
            complexity="multi_step",
            steps=[
                {"id": 1, "tool": "get_trending", "args": {}, "depends_on": []},
                {"id": 2, "tool": "search_hackernews", "args": {}, "depends_on": [1]},
                {"id": 3, "tool": "search_reddit", "args": {}, "depends_on": [1]},
            ],
            final_instruction="",
        )

        # 初始只有 step 1 可执行
        executable = plan.get_executable_steps()
        assert len(executable) == 1
        assert executable[0]["id"] == 1

        # step 1 完成后，step 2 和 3 可执行
        plan.step_results[1] = '["result"]'
        executable = plan.get_executable_steps()
        assert len(executable) == 2
        assert {s["id"] for s in executable} == {2, 3}

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

        plan.step_results[1] = json.dumps([{"name": "Ubuntu ISO"}, {"name": "Other"}])

        resolved = plan.resolve_args(plan.steps[1])
        assert resolved["query"] == "Ubuntu ISO"

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
                {"id": 1, "tool": "a", "args": {}, "depends_on": []},
                {"id": 2, "tool": "b", "args": {}, "depends_on": []},
            ],
            final_instruction="",
        )
        assert not plan.all_done()
        plan.step_results[1] = "done"
        assert not plan.all_done()
        plan.step_results[2] = "done"
        assert plan.all_done()

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


class TestPlannerPlan:

    @patch("intelligence.core.planner.OpenAI")
    def test_plan_returns_plan_object(self, mock_openai_cls):
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client

        mock_resp = MagicMock()
        mock_resp.choices = [MagicMock()]
        mock_resp.choices[0].message.content = json.dumps({
            "complexity": "multi_step",
            "steps": [
                {"id": 1, "tool": "get_trending", "args": {"limit": 10}, "depends_on": []},
                {"id": 2, "tool": "search_hackernews", "args": {"query": "test"}, "depends_on": [1]},
            ],
            "final_instruction": "汇总",
        })
        mock_client.chat.completions.create.return_value = mock_resp

        planner = Planner()
        plan = planner.plan("生成情报摘要")

        assert isinstance(plan, Plan)
        assert not plan.is_simple
        assert len(plan.steps) == 2

    @patch("intelligence.core.planner.OpenAI")
    def test_plan_fallback_on_error(self, mock_openai_cls):
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client
        mock_client.chat.completions.create.side_effect = Exception("API error")

        planner = Planner()
        plan = planner.plan("test query")

        assert plan.is_simple
        assert plan.steps == []


class TestPlannerReflect:

    @patch("intelligence.core.planner.OpenAI")
    def test_reflect_sufficient(self, mock_openai_cls):
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client

        mock_resp = MagicMock()
        mock_resp.choices = [MagicMock()]
        mock_resp.choices[0].message.content = "SUFFICIENT"
        mock_client.chat.completions.create.return_value = mock_resp

        planner = Planner()
        plan = Plan("multi_step", [{"id": 1, "tool": "a", "args": {}, "depends_on": []}], "")
        plan.step_results[1] = "some result"

        result = planner.reflect(plan, "test query")
        assert result is None

    @patch("intelligence.core.planner.OpenAI")
    def test_reflect_need_more(self, mock_openai_cls):
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client

        mock_resp = MagicMock()
        mock_resp.choices = [MagicMock()]
        mock_resp.choices[0].message.content = "NEED_MORE: 需要补充Reddit讨论"
        mock_client.chat.completions.create.return_value = mock_resp

        planner = Planner()
        plan = Plan("multi_step", [{"id": 1, "tool": "a", "args": {}, "depends_on": []}], "")
        plan.step_results[1] = "some result"

        result = planner.reflect(plan, "test query")
        assert result is not None
        assert "Reddit" in result
