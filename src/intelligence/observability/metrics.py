"""指标聚合模块 — 收集和汇总评估指标。"""
import logging
from collections import defaultdict

logger = logging.getLogger("intelligence.observability.metrics")


class MetricsCollector:
    """评估指标收集器，支持按类别聚合。"""

    def __init__(self):
        self._records: list[dict] = []
        self._by_category: dict[str, list[dict]] = defaultdict(list)

    def record_query(self, category: str, latency_ms: int,
                     tool_precision: float, tool_recall: float,
                     keyword_coverage: float, status: str = "success",
                     llm_judge_score: float | None = None):
        """记录单次查询的评估指标。"""
        record = {
            "category": category,
            "latency_ms": latency_ms,
            "tool_precision": tool_precision,
            "tool_recall": tool_recall,
            "keyword_coverage": keyword_coverage,
            "status": status,
            "llm_judge_score": llm_judge_score,
        }
        self._records.append(record)
        self._by_category[category].append(record)

    def summary(self) -> dict:
        """生成汇总报告。"""
        if not self._records:
            return {"total_queries": 0}

        total = len(self._records)
        success = sum(1 for r in self._records if r["status"] == "success")

        report = {
            "total_queries": total,
            "success_count": success,
            "success_rate": round(success / total, 3),
            "avg_latency_ms": round(
                sum(r["latency_ms"] for r in self._records) / total
            ),
            "avg_tool_precision": round(
                sum(r["tool_precision"] for r in self._records) / total, 3
            ),
            "avg_tool_recall": round(
                sum(r["tool_recall"] for r in self._records) / total, 3
            ),
            "avg_keyword_coverage": round(
                sum(r["keyword_coverage"] for r in self._records) / total, 3
            ),
            "avg_llm_judge": self._avg_llm_judge(self._records),
        }

        # 按类别统计
        by_category = {}
        for cat, records in self._by_category.items():
            n = len(records)
            by_category[cat] = {
                "count": n,
                "avg_tool_precision": round(
                    sum(r["tool_precision"] for r in records) / n, 3
                ),
                "avg_tool_recall": round(
                    sum(r["tool_recall"] for r in records) / n, 3
                ),
                "avg_keyword_coverage": round(
                    sum(r["keyword_coverage"] for r in records) / n, 3
                ),
                "avg_latency_ms": round(
                    sum(r["latency_ms"] for r in records) / n
                ),
                "avg_llm_judge": self._avg_llm_judge(records),
            }

        report["by_category"] = by_category
        return report

    @staticmethod
    def _avg_llm_judge(records: list[dict]) -> float | None:
        """计算有 LLM-as-Judge 评分记录的平均值。"""
        scores = [r["llm_judge_score"] for r in records
                  if r.get("llm_judge_score") is not None]
        if not scores:
            return None
        return round(sum(scores) / len(scores), 2)

    def reset(self):
        self._records.clear()
        self._by_category.clear()
