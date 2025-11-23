import streamlit as st
from agent_graph import graph
from langchain_core.messages import HumanMessage, AIMessage

# 페이지 설정
st.set_page_config(page_title="생산 관리 AI Agent", layout="wide")

# 세션 상태 초기화
if "messages" not in st.session_state:
    st.session_state["messages"] = []

st.title("AI Agent")

# 채팅 히스토리 표시
for msg in st.session_state.messages:
    if isinstance(msg, HumanMessage):
        with st.chat_message("user"):
            st.write(msg.content)
    elif isinstance(msg, AIMessage):
        with st.chat_message("assistant"):
            st.write(msg.content)

# 사용자 입력 처리
user_input = st.chat_input("생산 계획 ID(PL-2024-001)에 대한 소요량을 분석해줘.")

if user_input:
    # 사용자 메시지 UI 표시
    with st.chat_message("user"):
        st.write(user_input)
    st.session_state["messages"].append(HumanMessage(content=user_input))

    # LangGraph 실행
    config = {"configurable": {"thread_id": "1"}}

    with st.chat_message("assistant"):
        message_placeholder = st.empty()
        full_response = ""

        # 스트리밍 방식으로 그래프 실행 결과 처리
        # Note: LangGraph의 stream 모드는 단계별 상태를 반환함
        events = graph.stream({"messages": st.session_state["messages"]}, config)

        for event in events:
            if "reasoner" in event:
                msg = event["reasoner"]["messages"][-1]

                if msg.content:
                    # content가 문자열(str)인지 리스트(list)인지 확인하여 처리
                    if isinstance(msg.content, list):
                        # 리스트인 경우 (Gemini가 멀티파트 응답을 줄 때)
                        for part in msg.content:
                            if isinstance(part, str):
                                full_response += part
                            elif isinstance(part, dict) and "text" in part:
                                full_response += part["text"]
                    else:
                        # 문자열인 경우 (일반적인 텍스트 응답)
                        full_response += msg.content

                    message_placeholder.markdown(full_response + "▌")

            # Tool 실행 로그 (디버깅용)
            if "tools" in event:
                with st.expander("Tool Execution Log"):
                    # Tool 메시지 내용도 안전하게 출력
                    tool_msgs = event["tools"]["messages"]
                    for t_msg in tool_msgs:
                        st.write(f"Tool Output: {t_msg.content}")

        message_placeholder.markdown(full_response)

    # AI 응답 저장
    st.session_state["messages"].append(AIMessage(content=full_response))