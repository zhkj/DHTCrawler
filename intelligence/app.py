"""
Streamlit Web UI
运行：streamlit run app.py
功能：聊天 + 告警审批(HITL) + 可观测性面板
"""
import streamlit as st
from agents.orchestrator import Orchestrator
from agents.memory import UserPreferences, LongTermMemory
from db.mongo_client import (
    get_recent_torrents, get_alert_logs, mark_alerts_read,
    get_pending_alerts, get_traces, get_evaluations,
)

st.set_page_config(page_title="DHT 情报助手", page_icon="🔍", layout="wide")

# ── 初始化（session 级别单例）─────────────────────────────────────

if "agent" not in st.session_state:
    st.session_state.agent = Orchestrator()
if "messages" not in st.session_state:
    st.session_state.messages = []
if "tool_logs" not in st.session_state:
    st.session_state.tool_logs = []
if "prefs" not in st.session_state:
    st.session_state.prefs = UserPreferences("default")
if "long_term" not in st.session_state:
    st.session_state.long_term = LongTermMemory("default")

# ── 顶部 Tab 导航 ──────────────────────────────────────────────────

tab_chat, tab_hitl, tab_observe = st.tabs(["💬 对话", "🛡️ 告警审批", "📊 可观测性"])

# ══════════════════════════════════════════════════════════════════
# Tab 1: 聊天
# ══════════════════════════════════════════════════════════════════

with tab_chat:
    st.title("🔍 DHT 情报分析助手")
    st.caption("基于 DHT 网络数据 + HackerNews / Reddit / 新闻多源融合分析")

    # 展示历史消息
    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    # 输入框
    user_input = st.chat_input("输入问题，例如：最近 DHT 上有没有关于 AI 工具的泄露？")

    if user_input:
        st.session_state.messages.append({"role": "user", "content": user_input})
        with st.chat_message("user"):
            st.markdown(user_input)

        with st.chat_message("assistant"):
            tool_placeholder = st.empty()
            response_placeholder = st.empty()

            tool_log_lines = []

            def on_tool_call(name, inputs, result):
                query_str = inputs.get("query") or inputs.get("info_hash") or str(inputs)
                tool_log_lines.append(f"🔧 **{name}** (`{query_str[:60]}`)")
                tool_placeholder.markdown("\n".join(tool_log_lines))

            with st.spinner("分析中..."):
                reply = st.session_state.agent.chat(user_input, on_tool_call=on_tool_call)

            tool_placeholder.empty()
            if tool_log_lines:
                with st.expander(f"查看工具调用过程（共 {len(tool_log_lines)} 次）"):
                    st.markdown("\n".join(tool_log_lines))

            response_placeholder.markdown(reply)

        st.session_state.messages.append({"role": "assistant", "content": reply})

# ══════════════════════════════════════════════════════════════════
# Tab 2: Human-in-the-Loop 告警审批
# ══════════════════════════════════════════════════════════════════

with tab_hitl:
    st.title("🛡️ Human-in-the-Loop 告警审批")
    st.caption("中低置信度告警需人工确认后才会正式推送")

    col_pending, col_history = st.columns([3, 2])

    with col_pending:
        st.subheader("待审批告警")
        pending = get_pending_alerts(limit=20)

        if not pending:
            st.info("暂无待审批告警")
        else:
            st.warning(f"共 {len(pending)} 条待审批")

            for i, alert in enumerate(pending):
                confidence = alert.get("confidence", "unknown")
                conf_colors = {"medium": "🟡", "low": "⚪"}
                conf_icon = conf_colors.get(confidence, "❓")

                with st.container(border=True):
                    st.markdown(
                        f"### {conf_icon} {alert.get('torrent_name', '')[:60]}\n\n"
                        f"**置信度:** {confidence.upper()}  \n"
                        f"**命中关键词:** {', '.join(alert.get('matched_keywords', []))}  \n"
                        f"**分类:** {', '.join(alert.get('categories', [])) or '无'}  \n"
                        f"**info_hash:** `{alert.get('info_hash', '')}`  \n"
                        f"**时间:** {str(alert.get('triggered_at', ''))[:19]}"
                    )

                    col_approve, col_reject = st.columns(2)
                    info_hash = alert.get("info_hash", "")
                    user_id = alert.get("user_id", "__system__")

                    with col_approve:
                        if st.button("✅ 确认推送", key=f"approve_{i}_{info_hash}"):
                            from agents.monitor import approve_and_push
                            approve_and_push(info_hash, user_id)
                            st.success("已审批通过并推送")
                            st.rerun()

                    with col_reject:
                        reason = st.text_input(
                            "拒绝原因", key=f"reason_{i}_{info_hash}",
                            placeholder="误报/不相关..."
                        )
                        if st.button("❌ 标记误报", key=f"reject_{i}_{info_hash}"):
                            from agents.monitor import reject_and_learn
                            reject_and_learn(info_hash, user_id, reason or "误报")
                            st.success("已标记为误报，关键词反馈已记录")
                            st.rerun()

    with col_history:
        st.subheader("已处理告警")
        all_alerts = get_alert_logs(limit=20)
        active_alerts = [a for a in all_alerts if a.get("status") in ("active", "approved")]
        rejected_alerts = [a for a in all_alerts if a.get("status") == "rejected"]

        if active_alerts:
            st.markdown(f"**已推送 ({len(active_alerts)})**")
            for a in active_alerts[:10]:
                conf = a.get("confidence", "?")
                st.markdown(
                    f"- `{conf.upper()}` {a.get('torrent_name', '')[:40]}  \n"
                    f"  关键词: {', '.join(a.get('matched_keywords', []))}"
                )

        if rejected_alerts:
            st.markdown(f"**已拒绝 ({len(rejected_alerts)})**")
            for a in rejected_alerts[:10]:
                reason = a.get("reject_reason", "")
                st.markdown(
                    f"- ~~{a.get('torrent_name', '')[:40]}~~  \n"
                    f"  原因: {reason or '误报'}"
                )

        # 未读普通告警
        st.divider()
        unread = get_alert_logs(user_id="default", limit=20, unread_only=True)
        if unread:
            st.info(f"🔔 {len(unread)} 条未读通知")
            if st.button("全部标为已读"):
                mark_alerts_read("default")
                mark_alerts_read("__system__")
                st.rerun()

# ══════════════════════════════════════════════════════════════════
# Tab 3: 可观测性 & 评估
# ══════════════════════════════════════════════════════════════════

with tab_observe:
    st.title("📊 可观测性 & 质量评估")

    col_traces, col_eval = st.columns([3, 2])

    # ── Traces ────────────────────────────────────────────────
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
                    st.markdown(f"**状态:** {t.get('status', '')}")

                    # 工具调用链
                    tool_chain = t.get("tool_chain", "")
                    if tool_chain:
                        st.markdown(f"**工具链:** `{tool_chain}`")

                    # 详细工具调用
                    tool_calls = t.get("tool_calls", [])
                    if tool_calls:
                        st.markdown("**工具调用详情:**")
                        for tc in tool_calls:
                            st.markdown(
                                f"- `{tc['tool']}` "
                                f"({tc.get('latency_ms', 0)}ms, "
                                f"结果 {tc.get('result_len', 0)} chars)"
                            )

                    # LLM 调用
                    llm_calls = t.get("llm_calls", [])
                    if llm_calls:
                        st.markdown("**LLM 调用:**")
                        for lc in llm_calls:
                            st.markdown(
                                f"- Round {lc['round']}: "
                                f"{lc.get('tokens', 0)} tokens, "
                                f"{lc.get('latency_ms', 0)}ms"
                            )

                    # 回复预览
                    resp = t.get("response", "")
                    if resp:
                        st.markdown(f"**回复预览:** {resp[:200]}...")

    # ── 质量评估 ──────────────────────────────────────────────
    with col_eval:
        st.subheader("质量评估 (LLM-as-Judge)")
        evals = get_evaluations(limit=20)

        if not evals:
            st.info("暂无评估记录")
        else:
            # 平均分统计
            avg_scores = [e.get("avg_score", 0) for e in evals if e.get("avg_score")]
            if avg_scores:
                overall_avg = round(sum(avg_scores) / len(avg_scores), 1)
                st.metric("平均质量分", f"{overall_avg} / 5.0")

                # 各维度平均
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

            # 评估详情
            for ev in evals:
                score = ev.get("avg_score", 0)
                score_icon = "🟢" if score >= 4 else ("🟡" if score >= 3 else "🔴")
                with st.expander(
                    f"{score_icon} {score}/5 — {ev.get('query', '')[:40]}..."
                ):
                    st.markdown(f"**总评:** {ev.get('summary', '')}")
                    scores = ev.get("scores", {})
                    for dim, s in scores.items():
                        bar = "█" * s + "░" * (5 - s)
                        st.markdown(f"- {dim}: {bar} {s}/5")
                    st.caption(f"trace: {ev.get('trace_id', '')}")

# ══════════════════════════════════════════════════════════════════
# 侧边栏：系统设置
# ══════════════════════════════════════════════════════════════════

with st.sidebar:
    st.title("⚙️ 系统设置")

    # ── 用户画像 ────────────────────────────────────────────────
    st.subheader("用户画像")
    profile = st.session_state.long_term.get_profile()
    focus_areas = st.text_input(
        "关注领域（逗号分隔）",
        value=", ".join(profile.get("focus_areas", [])),
    )
    analysis_style = st.selectbox(
        "分析风格",
        ["简洁", "详细", "技术向"],
        index=["简洁", "详细", "技术向"].index(
            profile.get("analysis_style", "简洁")
        ) if profile.get("analysis_style") in ["简洁", "详细", "技术向"] else 0,
    )
    if st.button("保存画像"):
        areas = [a.strip() for a in focus_areas.split(",") if a.strip()]
        st.session_state.long_term.update_profile(
            focus_areas=areas, analysis_style=analysis_style,
        )
        st.success("用户画像已更新")

    st.divider()

    # ── 告警关键词配置 ────────────────────────────────────────
    st.subheader("告警关键词")
    current_alerts = st.session_state.prefs.get_alerts()
    alerts_text = st.text_area(
        "每行一个关键词",
        value="\n".join(current_alerts),
        height=120,
    )
    if st.button("保存告警规则"):
        keywords = [k.strip() for k in alerts_text.splitlines() if k.strip()]
        st.session_state.prefs.set_alerts(keywords)
        st.success(f"已保存 {len(keywords)} 个关键词")

    st.divider()

    # ── DHT 数据概况 ──────────────────────────────────────────
    st.subheader("DHT 数据概况")
    try:
        recent = get_recent_torrents(limit=5)
        st.metric("最近采集", f"{len(recent)} 条")
        for t in recent[:3]:
            st.text(t.get("name", "")[:40] + "...")
    except Exception:
        st.warning("MongoDB 未连接")

    st.divider()

    # ── Monitor 状态 ──────────────────────────────────────────
    from agents.monitor import is_running as monitor_running
    monitor_status = "运行中" if monitor_running() else "未启动"
    st.caption(f"Monitor Agent: {monitor_status}")

    st.divider()

    if st.button("清空对话"):
        st.session_state.messages = []
        st.session_state.tool_logs = []
        st.session_state.agent.reset()
        st.rerun()
