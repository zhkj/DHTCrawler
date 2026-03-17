"""可观测性 & 质量评估页面。"""
import streamlit as st
from intelligence.db import get_traces, get_evaluations


def render():
    st.title("📊 可观测性 & 质量评估")

    col_traces, col_eval = st.columns([3, 2])

    with col_traces:
        st.subheader("Agent 调用链路")
        traces = get_traces(limit=20)

        if not traces:
            st.info("暂无 trace 记录")
        else:
            for t in traces:
                status_icon = "✅" if t.get("status") == "success" else "⚠️"
                with st.expander(
                    f"{status_icon} {t.get('query', '')[:50]}... "
                    f"({t.get('total_ms', 0)}ms, {t.get('total_tokens', 0)} tokens)"
                ):
                    st.markdown(f"**Trace ID:** `{t.get('trace_id', '')}`")
                    st.markdown(f"**时间:** {str(t.get('start_time', ''))[:19]}")
                    st.markdown(f"**轮次:** {t.get('rounds', 0)}")

                    tool_chain = t.get("tool_chain", "")
                    if tool_chain:
                        st.markdown(f"**工具链:** `{tool_chain}`")

                    for tc in t.get("tool_calls", []):
                        st.markdown(
                            f"- `{tc['tool']}` ({tc.get('latency_ms', 0)}ms, "
                            f"{tc.get('result_len', 0)} chars)"
                        )

                    for lc in t.get("llm_calls", []):
                        st.markdown(
                            f"- Round {lc['round']}: "
                            f"{lc.get('tokens', 0)} tokens, {lc.get('latency_ms', 0)}ms"
                        )

                    resp = t.get("response", "")
                    if resp:
                        st.markdown(f"**回复预览:** {resp[:200]}...")

    with col_eval:
        st.subheader("质量评估 (LLM-as-Judge)")
        evals = get_evaluations(limit=20)

        if not evals:
            st.info("暂无评估记录")
        else:
            avg_scores = [e.get("avg_score", 0) for e in evals if e.get("avg_score")]
            if avg_scores:
                overall_avg = round(sum(avg_scores) / len(avg_scores), 1)
                st.metric("平均质量分", f"{overall_avg} / 5.0")

                dims = ["相关性", "完整性", "准确性", "信源引用"]
                dim_avgs = {}
                for dim in dims:
                    vals = [e["scores"].get(dim, 0) for e in evals if e.get("scores")]
                    dim_avgs[dim] = round(sum(vals) / len(vals), 1) if vals else 0

                cols = st.columns(4)
                for i, dim in enumerate(dims):
                    with cols[i]:
                        st.metric(dim, f"{dim_avgs[dim]}")

            st.divider()

            for ev in evals:
                score = ev.get("avg_score", 0)
                score_icon = "🟢" if score >= 4 else ("🟡" if score >= 3 else "🔴")
                with st.expander(
                    f"{score_icon} {score}/5 — {ev.get('query', '')[:40]}..."
                ):
                    st.markdown(f"**总评:** {ev.get('summary', '')}")
                    for dim, s in ev.get("scores", {}).items():
                        bar = "█" * s + "░" * (5 - s)
                        st.markdown(f"- {dim}: {bar} {s}/5")
                    st.caption(f"trace: {ev.get('trace_id', '')}")
