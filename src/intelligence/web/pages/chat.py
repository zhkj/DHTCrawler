"""聊天页面。"""
import streamlit as st


def render():
    st.title("🔍 DHT 情报分析助手")
    st.caption("基于 DHT 网络数据 + HackerNews / Reddit / 新闻多源融合分析")

    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

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
