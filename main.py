import streamlit as st
from agent_graph import graph
from langchain_core.messages import HumanMessage, AIMessage
import data_loader

# 페이지 설정
st.set_page_config(page_title="생산 관리 AI Agent", layout="wide")

# [사이드바] 데이터 베이스 관리
with st.sidebar:
    st.header("Data Management")

    # 1. 엑셀 파일 업로드 섹션
    with st.expander("Data Upload (Excel)", expanded=True):
        st.info(".xlsx 파일을 업로드하세요.")

        # 업로드할 데이터 유형 선택
        upload_type = st.selectbox(
            "데이터 유형 선택",
            options=list(data_loader.TABLE_SCHEMA.keys())  # ['product', 'bom', ...]
        )

        uploaded_file = st.file_uploader("엑셀 파일 선택", type=["xlsx"])

        if uploaded_file and st.button("데이터 적재 (ETL)"):
            with st.spinner("데이터 파싱 및 저장 중..."):
                success, msg = data_loader.save_uploaded_excel(uploaded_file, upload_type)
                if success:
                    st.success(msg)
                    # 데이터 갱신을 위해 캐시 초기화 또는 리로드 필요할 수 있음
                else:
                    st.error(msg)

    st.divider()

    # DB 조회 섹션
    st.subheader("DB Explorer")

    # 현재 로드된 데이터 가져오기
    current_db = data_loader.load_master_data()

    if current_db:
        selected_table = st.selectbox("조회할 테이블", list(current_db.keys()))

        if selected_table:
            df = current_db[selected_table]
            st.caption(f"Total Rows: {len(df)}")
            st.dataframe(df, width="stretch", height=300)
    else:
        st.warning("데이터가 없습니다.")

# [메인] 채팅 인터페이스
# 세션 상태 초기화
if "messages" not in st.session_state:
    st.session_state["messages"] = []

st.title("생산 관리 AI Agent")

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

    # LangGraph 실행 설정
    config = {"configurable": {"thread_id": "1"}}

    with st.chat_message("assistant"):
        message_placeholder = st.empty()
        full_response = ""

        # 스트리밍 방식으로 그래프 실행
        # LangGraph의 stream 모드는 단계별 상태를 반환함
        # 데이터가 갱신되었을 수 있으므로 실행 시마다 DB를 로드(Agent 내부에서 처리)
        events = graph.stream({"messages": st.session_state["messages"]}, config)

        for event in events:
            # Reasoner 응답 처리
            if "reasoner" in event:
                msg = event["reasoner"]["messages"][-1]
                if msg.content:
                    # content가 문자열(str)인지 리스트(list)인지 확인하여 처리
                    if isinstance(msg.content, str):
                        full_response += msg.content
                    # 리스트인 경우 (Gemini가 멀티파트 응답을 줄 때)
                    elif isinstance(msg.content, list):
                        for part in msg.content:
                            if isinstance(part, dict) and "text" in part:
                                full_response += part["text"]
                    message_placeholder.markdown(full_response + " ▌")

                # Finalize Order (승인 후) 응답 처리
                if "finalize_order" in event:
                    msg = event["finalize_order"]["messages"][-1]
                    full_response += f"\n\n{msg.content}"
                    message_placeholder.markdown(full_response)

                # Tool 실행 로그 (디버깅용)
                if "tools" in event:
                    with st.expander("Tool Execution Log"):
                        # Tool 메시지 내용도 안전하게 출력
                        for t_msg in event["tools"]["messages"]:
                            st.code(f"Tool: {t_msg.name}\nOutput: {t_msg.content}")
                        # tool_msgs = event["tools"]["messages"]
                        # for t_msg in tool_msgs:
                        #     st.write(f"Tool Output: {t_msg.content}")

                # Code execution 로그 (디버깅용)
                if "code_executor" in event:
                    with st.expander("Python Code Execution"):
                        st.write("실행 결과 데이터가 갱신되었습니다.")
                    # with st.expander("Tool Execution Log"):
                    #     # Tool 메시지 내용도 안전하게 출력
                    #     tool_msgs = event["tools"]["messages"]
                    #     for t_msg in tool_msgs:
                    #         st.write(f"Tool Output: {t_msg.content}")

        message_placeholder.markdown(full_response)

    # AI 응답 저장
    st.session_state["messages"].append(AIMessage(content=full_response))