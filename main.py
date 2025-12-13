"""
설명: Streamlit 기반의 생산 관리 AI Agent 웹 애플리케이션 진입점 (Entry Point)

[Role & Responsibility]
- Session Management: Streamlit의 session_state를 활용하여 대화 기록(Messages)과 생성된 파일 경로를 유지합니다.
- Event Loop: LangGraph의 stream 이벤트를 받아 실시간으로 분석 단계(Reasoning -> Coding -> Executing)를 시각화합니다.
"""

import streamlit as st
import os
from langchain_core.messages import HumanMessage, AIMessage

# 내부 모듈 Import
from interface import components as ui
from core.graph import create_graph

# --------------------------------------------------------------------------
# 1. 초기 설정 및 리소스 로드 (Initialization)
# --------------------------------------------------------------------------

# 페이지 기본 설정 (브라우저 탭 이름, 레이아웃 등)
# 반드시 스크립트 최상단에 위치해야 합니다.
ui.setup_page_config()


# [Performance] LangGraph 인스턴스 캐싱
# 그래프 생성 비용이 크지 않더라도, 매 리로드마다 재생성하는 것을 방지하여 응답 속도를 높입니다.
@st.cache_resource(show_spinner="AI Agent를 초기화 중입니다...")
def get_graph():
    return create_graph()


# 사이드바 렌더링 (설정 메뉴, 파일 업로더 등)
# 데이터 적재 기능이 이곳에 포함됩니다.
ui.render_sidebar()

# 메인 타이틀
st.title("생산 관리 AI Agent")

# --------------------------------------------------------------------------
# 2. 사용자 입력 및 채팅 히스토리 표시 (Chat Interface)
# --------------------------------------------------------------------------

# 퀵 프롬프트(자주 묻는 질문) 버튼 렌더링
# 사용자가 버튼을 클릭하면 해당 텍스트가 즉시 입력된 것처럼 처리됩니다.
quick_prompt = ui.render_quick_prompts()

# 세션 상태 초기화: 대화 기록이 없으면 빈 리스트로 생성
if "messages" not in st.session_state:
    st.session_state["messages"] = []

# [History Rendering] 기존 대화 내용을 화면에 다시 그립니다.
# Streamlit은 매번 전체 코드를 재실행하므로, 이 루프가 없으면 이전 대화가 사라집니다.
for msg in st.session_state.messages:
    if isinstance(msg, HumanMessage):
        with st.chat_message("user"):
            st.write(msg.content)
    elif isinstance(msg, AIMessage):
        with st.chat_message("assistant"):
            st.write(msg.content)
            # 분석 결과(DataFrame, Chart)가 메타데이터(additional_kwargs)에 있다면 렌더링
            if "artifact" in msg.additional_kwargs:
                ui.render_analysis_result(msg.additional_kwargs["artifact"])

# 채팅 입력창 (Chat Input)
# 사용자가 직접 타이핑하거나, 위에서 퀵 프롬프트를 클릭했을 때 값을 가져옵니다.
chat_input = st.chat_input("질문을 입력하세요.")
user_input = chat_input if chat_input else quick_prompt

# --------------------------------------------------------------------------
# 3. Agent 실행 로직 (Main Event Loop)
# --------------------------------------------------------------------------

if user_input:
    # 1. 사용자 메시지를 UI에 즉시 표시하고 세션에 저장
    st.session_state["messages"].append(HumanMessage(content=user_input))
    with st.chat_message("user"):
        st.write(user_input)

    # 2. Graph 실행 준비
    app = get_graph()
    # thread_id는 대화의 맥락(Memory)을 유지하는 키입니다. 멀티 유저 환경 시 변경 필요.
    config = {"configurable": {"thread_id": "thread-1"}}

    with st.chat_message("assistant"):
        # [UX] 진행 상태를 보여주는 Status Container (스피너 역할)
        status_container = st.status("🔍 AI Agent가 분석 중입니다...", expanded=True)
        message_placeholder = st.empty()  # 최종 답변이 스트리밍될 공간

        full_response = ""
        analysis_artifact = None

        try:
            # 3. LangGraph 스트리밍 실행
            # inputs: 현재까지의 모든 대화 기록을 전달하여 문맥을 파악하게 함
            inputs = {"messages": st.session_state["messages"]}

            # app.stream()은 제너레이터로서, 노드 실행이 완료될 때마다 이벤트를 방출합니다.
            for event in app.stream(inputs, config=config):

                # event 구조: {'node_name': {updated_state_values}}
                for node_name, state_update in event.items():

                    # [Step 1] Reasoner: 계획 수립
                    if node_name == "reasoner":
                        status_container.write("🧠 **[분석]** 사용자 의도를 파악하고 계획을 수립했습니다.")

                    # [Step 2] Code Generator: 코드 작성
                    elif node_name == "code_generator":
                        status_container.write("💻 **[설계]** 데이터 분석용 Python 코드를 생성했습니다.")
                        # 생성된 코드를 Expander로 숨겨서 보여줌 (깔끔한 UI)
                        code = state_update.get("generated_code") or state_update.get("python_code", "")
                        with status_container.expander("생성된 코드 보기"):
                            st.code(code, language="python")

                    # [Step 3] Code Executor: 실행 및 결과 도출
                    elif node_name == "code_executor":
                        status = state_update.get("execution_status")
                        retry_cnt = state_update.get("retry_count", 0)

                        if status == "success":
                            status_container.write("✅ **[실행]** 코드 실행을 성공적으로 완료했습니다.")
                            # 결과 데이터(Artifact) 임시 확보
                            if "analysis_data" in state_update:
                                analysis_artifact = state_update["analysis_data"].get("last_run_result")
                        elif status == "error":
                            status_container.write(
                                f"⚠️ **[오류]** 실행 실패, 재시도합니다. (Retry: {retry_cnt})")

                    # [Step 4] Final Response Streaming
                    # 마지막 노드(reasoner 등)가 최종 답변을 생성하여 messages에 추가했을 때
                    if "messages" in state_update and state_update["messages"]:
                        last_msg = state_update["messages"][-1]
                        if isinstance(last_msg, AIMessage) and last_msg.content:
                            full_response = last_msg.content
                            # 커서 효과(▌)를 주어 실시간 타이핑 느낌 구현
                            message_placeholder.markdown(full_response + " ▌")

            # 4. 완료 처리
            status_container.update(label="분석 완료", state="complete", expanded=False)
            message_placeholder.markdown(full_response)  # 커서 제거

            # 5. Artifact(표/차트) 렌더링
            if analysis_artifact:
                ui.render_analysis_result(analysis_artifact)

            # 6. 세션에 AI 응답 영구 저장
            ai_msg = AIMessage(content=full_response)
            if analysis_artifact:
                # 다음 번 렌더링을 위해 메타데이터에 결과 저장
                ai_msg.additional_kwargs["artifact"] = analysis_artifact
            st.session_state["messages"].append(ai_msg)

        except Exception as e:
            status_container.update(label="오류 발생", state="error")
            st.error(f"시스템 오류가 발생했습니다: {e}")

# --------------------------------------------------------------------------
# 4. Human-in-the-Loop (HIL) 처리
# --------------------------------------------------------------------------
# 그래프 실행이 'interrupt_before'에 의해 멈췄을 때, 사용자 입력을 받아 재개하는 로직

hil_options = ["승인", "반려", "수정/피드백"]

if 'messages' in st.session_state and st.session_state['messages']:
    last_msg = st.session_state['messages'][-1]

    # [Simple Trigger] 마지막 메시지에 '승인' 관련 키워드가 있거나,
    # 실제로는 State의 'user_approval_pending' 값을 확인하는 것이 더 정확함 (UI Component 연동 필요)
    if isinstance(last_msg, AIMessage) and ('승인' in last_msg.content or '확인' in last_msg.content):
        with st.expander("결과 검토 및 승인 요청", expanded=True):
            st.info("발주를 진행하기 위해 사용자의 승인이 필요합니다.")

            # Form을 사용하여 라디오 버튼과 제출 버튼을 묶음
            with st.form("hil_form"):
                choice = st.radio("결정", hil_options, index=0)
                feedback = st.text_input("피드백 (수정/반려 시 입력)", placeholder="수정 사항이나 반려 사유를 입력하세요.")
                submitted = st.form_submit_button("결정 적용")

                if submitted:
                    # 사용자 결정을 HumanMessage로 추가
                    decision_msg = f"결정: {choice}"
                    if feedback:
                        decision_msg += f", 사유: {feedback}"

                    st.session_state['messages'].append(HumanMessage(content=decision_msg))

                    # [Resume Graph] 그래프 재실행 (이전 상태에서 이어서 실행됨)
                    # 실제 구현 시에는 update_state 등을 통해 state를 직접 수정하는 것이 더 깔끔할 수 있음
                    st.rerun()

# --------------------------------------------------------------------------
# 5. 결과 파일 다운로드 영역 (File Downloads)
# --------------------------------------------------------------------------
# Agent가 생성한 파일 경로가 세션에 저장되어 있다면, 다운로드 버튼을 활성화합니다.

# A. 월말 구매 마감 리포트
if "monthly_report_path" in st.session_state:
    file_path = st.session_state["monthly_report_path"]
    if os.path.exists(file_path):
        st.divider()
        with open(file_path, "rb") as f:
            st.download_button(
                label="📥 월말 구매 마감 리포트 다운로드",
                data=f,
                file_name=os.path.basename(file_path),
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                key="dl_monthly",
                use_container_width=True
            )

# B. 발주 현황 공유 파일
if "po_status_path" in st.session_state:
    file_path = st.session_state["po_status_path"]
    if os.path.exists(file_path):
        if "monthly_report_path" not in st.session_state:
            st.divider()
        with open(file_path, "rb") as f:
            st.download_button(
                label="📥 발주 현황 공유 파일 다운로드",
                data=f,
                file_name=os.path.basename(file_path),
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                key="dl_po_status",
                use_container_width=True
            )

# C. 공급업체 평가 양식
if "supplier_eval_path" in st.session_state:
    file_path = st.session_state["supplier_eval_path"]
    if os.path.exists(file_path):
        if "monthly_report_path" not in st.session_state and "po_status_path" not in st.session_state:
            st.divider()
        with open(file_path, "rb") as f:
            st.download_button(
                label="📥 공급업체 평가 양식 다운로드",
                data=f,
                file_name=os.path.basename(file_path),
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                key="dl_supplier_eval",
                use_container_width=True
            )