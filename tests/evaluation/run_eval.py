"""离线评估脚本 — 批量运行评估集并统计指标。

用法：
    python tests/evaluation/run_eval.py
    python tests/evaluation/run_eval.py --dataset tests/evaluation/eval_dataset.json
"""
import json
import time
import argparse
import logging
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("eval")


def load_dataset(path: str) -> list[dict]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def run_evaluation(dataset_path: str, output_path: str | None = None):
    """运行评估集，统计各项指标。"""
    from intelligence.core.orchestrator import Orchestrator
    from intelligence.observability.metrics import MetricsCollector

    dataset = load_dataset(dataset_path)
    logger.info(f"加载评估集: {len(dataset)} 条")

    agent = Orchestrator(user_id="eval")
    metrics = MetricsCollector()

    results = []

    for i, case in enumerate(dataset):
        query = case["query"]
        expected_tools = set(case.get("expected_tools", []))
        expected_keywords = case.get("expected_keywords", [])
        category = case.get("category", "unknown")

        logger.info(f"[{i + 1}/{len(dataset)}] {query[:50]}...")

        # 收集工具调用
        tool_calls = []

        def on_tool(name, args, result):
            tool_calls.append(name)

        start = time.time()
        try:
            response = agent.chat(query, on_tool_call=on_tool)
            latency_ms = int((time.time() - start) * 1000)
            status = "success"
        except Exception as e:
            response = str(e)
            latency_ms = int((time.time() - start) * 1000)
            status = "error"

        # 工具调用准确率
        actual_tools = set(tool_calls)
        tool_precision = (
            len(actual_tools & expected_tools) / len(actual_tools)
            if actual_tools else (1.0 if not expected_tools else 0.0)
        )
        tool_recall = (
            len(actual_tools & expected_tools) / len(expected_tools)
            if expected_tools else 1.0
        )

        # 关键词覆盖率
        keyword_hits = sum(1 for kw in expected_keywords if kw in response)
        keyword_coverage = keyword_hits / len(expected_keywords) if expected_keywords else 1.0

        eval_result = {
            "id": case.get("id", i + 1),
            "query": query,
            "category": category,
            "status": status,
            "response_preview": response[:200],
            "latency_ms": latency_ms,
            "tool_calls": tool_calls,
            "expected_tools": list(expected_tools),
            "tool_precision": round(tool_precision, 3),
            "tool_recall": round(tool_recall, 3),
            "keyword_coverage": round(keyword_coverage, 3),
        }
        results.append(eval_result)

        # 记录到 metrics
        metrics.record_query(
            category=category,
            latency_ms=latency_ms,
            tool_precision=tool_precision,
            tool_recall=tool_recall,
            keyword_coverage=keyword_coverage,
            status=status,
        )

        # 重置对话上下文
        agent.reset()

    # 生成汇总报告
    report = metrics.summary()
    report["details"] = results

    # 输出报告
    print("\n" + "=" * 60)
    print("评估报告")
    print("=" * 60)
    print(f"总计: {report['total_queries']} 条")
    print(f"成功: {report['success_count']} 条")
    print(f"平均延迟: {report['avg_latency_ms']}ms")
    print(f"工具调用精确率: {report['avg_tool_precision']}")
    print(f"工具调用召回率: {report['avg_tool_recall']}")
    print(f"关键词覆盖率: {report['avg_keyword_coverage']}")
    print()

    if report.get("by_category"):
        print("按类别统计:")
        for cat, stats in report["by_category"].items():
            print(f"  {cat}: {stats['count']} 条, "
                  f"精确率={stats['avg_tool_precision']}, "
                  f"关键词覆盖={stats['avg_keyword_coverage']}")

    print("=" * 60)

    # 保存结果
    if output_path is None:
        output_path = str(Path(dataset_path).parent / "eval_results.json")

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    logger.info(f"评估结果已保存至: {output_path}")

    return report


def main():
    parser = argparse.ArgumentParser(description="DHT Intelligence 离线评估")
    parser.add_argument(
        "--dataset",
        default=str(Path(__file__).parent / "eval_dataset.json"),
        help="评估数据集路径",
    )
    parser.add_argument("--output", default=None, help="结果输出路径")
    args = parser.parse_args()

    run_evaluation(args.dataset, args.output)


if __name__ == "__main__":
    main()
