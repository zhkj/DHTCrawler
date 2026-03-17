"""
Streamlit Web UI 入口。
运行：cd src && streamlit run intelligence/web/app.py
"""
import streamlit as st
from intelligence.core import Orchestrator
from intelligence.core.memory import UserPreferences, LongTermMemory
from intelligence.db import get_recent_torrents
from intelligence.web.pages import chat, hitl, observability

st.set_page_config(page_title="DHT 情报助手", page_icon="🔍", layout="wide")

# ── Session 初始化 ──────────────────────────────────────────────

if "agent" not in st.session_state:
    st.session_state.agent = Orchestrator()
if "messages" not in st.session_state:
    st.session_state.messages = []
if "prefs" not in st.session_state:
    st.session_state.prefs = UserPreferences("default")
if "long_term" not in st.session_state:
    st.session_state.long_term = LongTermMemory("default")

# ── Tab 导航 ────────────────────────────────────────────────────

tab_chat, tab_hitl, tab_observe = st.tabs(["💬 对话", "🛡️ 告警审批", "📊 可观测性"])

with tab_chat:
    chat.render()

with tab_hitl:
    hitl.render()

with tab_observe:
    observability.render()

# ── 侧边栏 ─────────────────────────────────────────────────────

with st.sidebar:
    st.title("⚙️ 系统设置")

    # 用户画像
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

    # 告警关键词
    st.subheader("告警关键词")
    current_alerts = st.session_state.prefs.get_alerts()
    alerts_text = st.text_area(
        "每行一个关键词", value="\n".join(current_alerts), height=120,
    )
    if st.button("保存告警规则"):
        keywords = [k.strip() for k in alerts_text.splitlines() if k.strip()]
        st.session_state.prefs.set_alerts(keywords)
        st.success(f"已保存 {len(keywords)} 个关键词")

    st.divider()

    # DHT 概况
    st.subheader("DHT 数据概况")
    try:
        recent = get_recent_torrents(limit=5)
        st.metric("最近采集", f"{len(recent)} 条")
        for t in recent[:3]:
            st.text(t.get("name", "")[:40] + "...")
    except Exception:
        st.warning("MongoDB 未连接")

    st.divider()

    from intelligence.monitor import is_running as monitor_running
    st.caption(f"Monitor Agent: {'运行中' if monitor_running() else '未启动'}")

    st.divider()

    if st.button("清空对话"):
        st.session_state.messages = []
        st.session_state.agent.reset()
        st.rerun()
