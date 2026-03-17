"""LLM-as-Judge 质量评估。"""
import logging
from datetime import datetime
from openai import OpenAI
from intelligence.config import LLM_API_KEY, LLM_BASE_URL, LLM_MODEL
from intelligence.db import save_evaluation

logger = logging.getLogger("intelligence.observability.evaluator")

EVAL_PROMPT = """你是一个 AI 回答质量评估专家。请对以下 Agent 的回答进行评分。

用户问题：{query}

Agent 回答：{response}

工具调用链：{tool_chain}

请从以下 4 个维度评分（每项 1-5 分），并给出简短理由：

1. **相关性**：回答是否切题，是否回答了用户的问题
2. **完整性**：是否综合了多个数据源，信息是否充分
3. **准确性**：表述是否准确，有无自相矛盾或编造信息
4. **信源引用**：是否标注了信息来源（DHT数据/HN/Reddit/新闻）

输出格式（严格遵循）：
相关性: <分数>
完整性: <分数>
准确性: <分数>
信源引用: <分数>
总评: <一句话总结>"""


def evaluate(query: str, response: str, tool_chain: str = "",
             trace_id: str = "") -> dict | None:
    if not response or len(response) < 10:
        return None

    client = OpenAI(api_key=LLM_API_KEY, base_url=LLM_BASE_URL)
    prompt = EVAL_PROMPT.format(
        query=query[:500],
        response=response[:1000],
        tool_chain=tool_chain or "无工具调用",
    )

    try:
        resp = client.chat.completions.create(
            model=LLM_MODEL,
            max_tokens=300,
            messages=[{"role": "user", "content": prompt}],
        )
        eval_text = resp.choices[0].message.content or ""
    except Exception as e:
        logger.warning(f"[Evaluator] LLM 调用失败: {e}")
        return None

    scores = {}
    summary = ""
    for line in eval_text.split("\n"):
        line = line.strip()
        for dim in ("相关性", "完整性", "准确性", "信源引用"):
            if line.startswith(f"{dim}:") or line.startswith(f"{dim}："):
                try:
                    score_str = line.split(":", 1)[-1].split("：", 1)[-1].strip()
                    scores[dim] = int(score_str[0])
                except (ValueError, IndexError):
                    pass
        if line.startswith("总评:") or line.startswith("总评："):
            summary = line.split(":", 1)[-1].split("：", 1)[-1].strip()

    if not scores:
        logger.warning(f"[Evaluator] 评分解析失败: {eval_text[:200]}")
        return None

    avg_score = round(sum(scores.values()) / len(scores), 1) if scores else 0

    evaluation = {
        "trace_id": trace_id,
        "query": query[:500],
        "response_preview": response[:200],
        "scores": scores,
        "avg_score": avg_score,
        "summary": summary,
        "raw_eval": eval_text,
        "created_at": datetime.now(),
    }

    try:
        save_evaluation(evaluation)
        logger.info(f"[Evaluator] trace={trace_id} avg={avg_score} scores={scores}")
    except Exception as e:
        logger.warning(f"[Evaluator] 持久化失败: {e}")

    return evaluation
