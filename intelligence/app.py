"""
Streamlit Web UI
运行：streamlit run app.py
"""
import streamlit as st
from agents.orchestrator import Orchestrator
from agents.memory import UserPreferences
from db.mongo_client import get_recent_torrents, get_alert_logs, mark_alerts_read

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

# ── 侧边栏 ────────────────────────────────────────────────────────

with st.sidebar:
    st.title("⚙️ 系统设置")

    # ── 告警通知 ──────────────────────────────────────────────
    st.subheader("告警通知")

    unread_alerts = get_alert_logs(user_id="default", limit=50, unread_only=True)
    # 也展示系统级信号词告警
    system_alerts = get_alert_logs(user_id="__system__", limit=20, unread_only=True)
    all_unread = unread_alerts + system_alerts
    all_unread.sort(key=lambda x: x.get("triggered_at", ""), reverse=True)

    if all_unread:
        st.error(f"🔔 {len(all_unread)} 条未读告警")
        for alert in all_unread[:10]:
            alert_type = "🏷️ 信号词" if alert.get("type") == "signal" else "👤 自定义"
            torrent_name = alert.get("torrent_name", "")[:50]
            keywords = ", ".join(alert.get("matched_keywords", []))
            categories = alert.get("categories", [])
            cat_str = f" [{', '.join(categories)}]" if categories else ""

            with st.container():
                st.markdown(
                    f"**{alert_type}{cat_str}**\n\n"
                    f"`{torrent_name}`\n\n"
                    f"命中: {keywords}"
                )
                triggered = alert.get("triggered_at", "")
                if triggered:
                    st.caption(str(triggered)[:19])
                st.divider()

        if st.button("全部标为已读"):
            mark_alerts_read("default")
            mark_alerts_read("__system__")
            st.rerun()
    else:
        st.info("暂无未读告警")

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

# ── 主聊天区 ──────────────────────────────────────────────────────

st.title("🔍 DHT 情报分析助手")
st.caption("基于 DHT 网络数据 + HackerNews / Reddit / 新闻多源融合分析")

# 展示历史消息
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

# 输入框
user_input = st.chat_input("输入问题，例如：最近 DHT 上有没有关于 AI 工具的泄露？")

if user_input:
    # 展示用户消息
    st.session_state.messages.append({"role": "user", "content": user_input})
    with st.chat_message("user"):
        st.markdown(user_input)

    # Agent 思考过程展示区
    with st.chat_message("assistant"):
        tool_placeholder = st.empty()
        response_placeholder = st.empty()

        tool_log_lines = []

        def on_tool_call(name, inputs, result):
            """每次工具调用时更新 UI 展示思考链路。"""
            query_str = inputs.get("query") or inputs.get("info_hash") or str(inputs)
            tool_log_lines.append(f"🔧 **{name}** (`{query_str[:60]}`)")
            tool_placeholder.markdown("\n".join(tool_log_lines))

        # 调用 Agent
        with st.spinner("分析中..."):
            reply = st.session_state.agent.chat(user_input, on_tool_call=on_tool_call)

        tool_placeholder.empty()
        if tool_log_lines:
            with st.expander(f"查看工具调用过程（共 {len(tool_log_lines)} 次）"):
                st.markdown("\n".join(tool_log_lines))

        response_placeholder.markdown(reply)

    st.session_state.messages.append({"role": "assistant", "content": reply})
