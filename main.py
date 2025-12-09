import streamlit as st
from langchain_core.messages import HumanMessage, AIMessage

import ui_components as ui
from agent_graph import create_graph

# 페이지 설정 (가장 먼저 실행)
ui.setup_page_config()


# 리소스 캐싱 (Agent Graph)
@st.cache_resource(show_spinner="AI Agent를 초기화 중입니다...")
def get_graph():
    return create_graph()


# 사이드바 렌더링
ui.render_sidebar()


# 메인 타이틀 및 초기 상태 설정
st.title("생산 관리 AI Agent")

if "messages" not in st.session_state:
    st.session_state["messages"] = []

# 대화 기록 표시
for msg in st.session_state.messages:
    if isinstance(msg, HumanMessage):
        with st.chat_message("user"):
            st.write(msg.content)
    elif isinstance(msg, AIMessage):
        with st.chat_message("assistant"):
            st.write(msg.content)
            # Artifact(표/차트)가 있으면 렌더링
            if "artifact" in msg.additional_kwargs:
                ui.render_analysis_result(msg.additional_kwargs["artifact"])

# 사용자 입력 처리 (텍스트 입력 or 버튼 클릭)
quick_prompt = ui.render_quick_prompts()
chat_input = st.chat_input("질문을 입력하세요.")

user_input = chat_input if chat_input else quick_prompt

if user_input:
    # ]사용자 메시지 저장 및 표시
    st.session_state["messages"].append(HumanMessage(content=user_input))
    with st.chat_message("user"):
        st.write(user_input)

    # Agent 실행
    app = get_graph()
    config = {"configurable": {"thread_id": "thread-1"}}

    with st.chat_message("assistant"):
        # UI: 사고 과정 표시용 컨테이너
        status_container = st.status(" AI Agent가 분석 중입니다...", expanded=True)
        message_placeholder = st.empty()

        full_response = ""
        analysis_artifact = None

        try:
            # LangGraph 스트리밍 실행
            # inputs에 messages 리스트 전체를 전달
            inputs = {"messages": st.session_state["messages"]}

            for event in app.stream(inputs, config=config):

                # event는 {'node_name': state_update} 형태
                for node_name, state_update in event.items():

                    # 사고 과정 시각화
                    if node_name == "reasoner":
                        status_container.write(" **[분석]** 사용자 의도를 파악하고 계획을 수립했습니다.")
                        # reasoner의 마지막 메시지(Thinking 내용)를 가져올 수도 있음

                    elif node_name == "code_generator":
                        status_container.write(" **[설계]** 데이터 분석용 Python 코드를 생성했습니다.")
                        with status_container.expander("생성된 코드 보기"):
                            st.code(state_update.get("python_code", ""), language="python")

                    elif node_name == "code_executor":
                        status = state_update.get("generation_status")
                        if status == "SUCCESS":
                            status_container.write(" **[실행]** 코드 실행을 완료했습니다.")
                            # 결과 데이터 임시 저장
                            if "analysis_data" in state_update:
                                analysis_artifact = state_update["analysis_data"].get("last_run_result")
                        elif status == "FAILED":
                            status_container.write(
                                f" **[오류]** 실행 실패, 재시도합니다. (Retry: {state_update.get('retry_count')})")

                    # 최종 답변 메시지 스트리밍 효과 (마지막 노드에서 온 메시지인 경우)
                    if "messages" in state_update and state_update["messages"]:
                        last_msg = state_update["messages"][-1]
                        if isinstance(last_msg, AIMessage) and last_msg.content:
                            full_response = last_msg.content
                            message_placeholder.markdown(full_response + " ▌")

            # 스트리밍 완료 후 정리
            status_container.update(label="분석 완료", state="complete", expanded=False)
            message_placeholder.markdown(full_response)

            # Artifact 렌더링
            if analysis_artifact:
                ui.render_analysis_result(analysis_artifact)

            # 세션에 AI 응답 저장
            ai_msg = AIMessage(content=full_response)
            if analysis_artifact:
                ai_msg.additional_kwargs["artifact"] = analysis_artifact
            st.session_state["messages"].append(ai_msg)

        except Exception as e:
            status_container.update(label="오류 발생", state="error")
            st.error(f"시스템 오류: {e}")