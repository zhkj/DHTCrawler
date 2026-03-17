"""Human-in-the-Loop 告警审批页面。"""
import streamlit as st
from intelligence.db import get_pending_alerts, get_alert_logs, mark_alerts_read


def render():
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
                conf_icon = {"medium": "🟡", "low": "⚪"}.get(confidence, "❓")

                with st.container(border=True):
                    st.markdown(
                        f"### {conf_icon} {alert.get('torrent_name', '')[:60]}\n\n"
                        f"**置信度:** {confidence.upper()}  \n"
                        f"**命中关键词:** {', '.join(alert.get('matched_keywords', []))}  \n"
                        f"**分类:** {', '.join(alert.get('categories', [])) or '无'}  \n"
                        f"**info_hash:** `{alert.get('info_hash', '')}`  \n"
                        f"**时间:** {str(alert.get('triggered_at', ''))[:19]}"
                    )

                    info_hash = alert.get("info_hash", "")
                    user_id = alert.get("user_id", "__system__")

                    col_approve, col_reject = st.columns(2)
                    with col_approve:
                        if st.button("✅ 确认推送", key=f"approve_{i}_{info_hash}"):
                            from intelligence.monitor import approve_and_push
                            approve_and_push(info_hash, user_id)
                            st.success("已审批通过并推送")
                            st.rerun()

                    with col_reject:
                        reason = st.text_input(
                            "拒绝原因", key=f"reason_{i}_{info_hash}",
                            placeholder="误报/不相关...",
                        )
                        if st.button("❌ 标记误报", key=f"reject_{i}_{info_hash}"):
                            from intelligence.monitor import reject_and_learn
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
                st.markdown(
                    f"- `{a.get('confidence', '?').upper()}` "
                    f"{a.get('torrent_name', '')[:40]}  \n"
                    f"  关键词: {', '.join(a.get('matched_keywords', []))}"
                )

        if rejected_alerts:
            st.markdown(f"**已拒绝 ({len(rejected_alerts)})**")
            for a in rejected_alerts[:10]:
                st.markdown(
                    f"- ~~{a.get('torrent_name', '')[:40]}~~  \n"
                    f"  原因: {a.get('reject_reason', '误报')}"
                )

        st.divider()
        unread = get_alert_logs(user_id="default", limit=20, unread_only=True)
        if unread:
            st.info(f"🔔 {len(unread)} 条未读通知")
            if st.button("全部标为已读"):
                mark_alerts_read("default")
                mark_alerts_read("__system__")
                st.rerun()
