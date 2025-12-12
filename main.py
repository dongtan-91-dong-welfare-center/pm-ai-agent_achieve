import streamlit as st
import os  # [필수] 파일 경로 처리를 위해 추가
from langchain_core.messages import HumanMessage, AIMessage

import ui_components as ui
from agent_graph import create_graph

# --------------------------------------------------------------------------
# 1. 초기 설정 및 리소스 로드
# --------------------------------------------------------------------------
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

# --------------------------------------------------------------------------
# 2. 사용자 입력 및 채팅 히스토리 표시
# --------------------------------------------------------------------------
# 상단 버튼 렌더링 (여기서는 로직 실행 및 경로 저장만 수행)
quick_prompt = ui.render_quick_prompts()

if "messages" not in st.session_state:
    st.session_state["messages"] = []

# 대화 기록 표시 (이 부분이 실행되어야 채팅창이 그려짐)
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

# 채팅 입력창
chat_input = st.chat_input("질문을 입력하세요.")
user_input = chat_input if chat_input else quick_prompt

# --------------------------------------------------------------------------
# 3. Agent 실행 로직 (사용자 입력이 있을 경우)
# --------------------------------------------------------------------------
if user_input:
    # 사용자 메시지 저장 및 표시
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
            # inputs에 messages 리스트 전체를 전달 (기존 로직 유지)
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

    # HIL 승인 대기 여부 UI 처리
    # 그래프 실행 중에 'user_approval_pending'가 발생할 수 있으므로, 사용자가 승인/반려 버튼을 누르면 그래프를 재실행하여 이어감
    hil_options = ["승인", "반려", "수정/피드백"]
    if 'messages' in st.session_state and st.session_state['messages']:
        # 마지막 대화가 AI 메시지인지 확인
        last_msg = st.session_state['messages'][-1]
        # 여기서는 간단 조건으로 UI 표시: 마지막 AIMessage의 컨텐츠에 '승인' 프롬프트가 있는 경우
        if isinstance(last_msg, AIMessage) and '승인' in last_msg.content:
            with st.expander("결과를 검토하고 승인하세요"):
                choice = st.radio("결정", hil_options, index=0, key='hil_choice')
                if st.button("결정 적용", key='hil_apply'):
                    # Append user decision as human message and resume the graph
                    st.session_state['messages'].append(HumanMessage(content=choice))
                    app = get_graph()
                    config = {"configurable": {"thread_id": "thread-1"}}
                    try:
                        for event in app.stream({"messages": st.session_state['messages']}, config=config):
                            for node_name, state_update in event.items():
                                if 'messages' in state_update and state_update['messages']:
                                    last_msg = state_update['messages'][-1]
                                    if isinstance(last_msg, AIMessage) and last_msg.content:
                                        with st.chat_message("assistant"):
                                            st.write(last_msg.content)
                                            st.session_state['messages'].append(last_msg)
                    except Exception as e:
                        st.error(f"승인 재실행 중 오류가 발생했습니다: {e}")

# --------------------------------------------------------------------------
# 4. [New] 결과 파일 다운로드 영역
# --------------------------------------------------------------------------
# 이 코드가 맨 마지막에 있으므로, 채팅창(Agent 실행 결과 포함) 아래에 버튼이 생성됩니다.

# A. 월말 구매 마감 리포트 다운로드
if "monthly_report_path" in st.session_state:
    file_path = st.session_state["monthly_report_path"]

    # 파일이 실제로 존재할 때만 버튼 표시
    if os.path.exists(file_path):
        st.divider()  # 시각적 구분선
        with open(file_path, "rb") as f:
            st.download_button(
                label="📥 월말 구매 마감 리포트 다운로드",
                data=f,
                file_name=os.path.basename(file_path),
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                key="dl_main_monthly",
                use_container_width=True
            )

# B. 발주 현황 공유 파일 다운로드
if "po_status_path" in st.session_state:
    file_path = st.session_state["po_status_path"]

    if os.path.exists(file_path):
        # 월말 리포트 버튼이 없을 때만 구분선 추가 (중복 방지)
        if "monthly_report_path" not in st.session_state:
            st.divider()

        with open(file_path, "rb") as f:
            st.download_button(
                label="📥 발주 현황 공유 파일 다운로드",
                data=f,
                file_name=os.path.basename(file_path),
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                key="dl_main_po",
                use_container_width=True
            )

# C. [추가됨] 공급업체 평가 양식 다운로드
if "supplier_eval_path" in st.session_state:
    file_path = st.session_state["supplier_eval_path"]

    if os.path.exists(file_path):
        # 다른 리포트들이 하나도 없을 때만 구분선 추가 (깔끔한 UI 유지)
        if "monthly_report_path" not in st.session_state and "po_status_path" not in st.session_state:
            st.divider()

        with open(file_path, "rb") as f:
            st.download_button(
                label="📥 공급업체 평가 양식 다운로드",
                data=f,
                file_name=os.path.basename(file_path),
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                key="dl_btn_supplier_eval",
                use_container_width=True
            )