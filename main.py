"""
설명: Streamlit 앱 진입점
"""

import streamlit as st
import os
# ToolMessage 추가 Import
from langchain_core.messages import HumanMessage, AIMessage, ToolMessage

import interface.components as ui
from core.graph import create_graph

# --------------------------------------------------------------------------
# 1. 초기 설정 및 리소스 로드
# --------------------------------------------------------------------------
ui.setup_page_config()

@st.cache_resource(show_spinner="AI Agent를 초기화 중입니다...")
def get_graph():
    return create_graph()

ui.render_sidebar()
st.title("생산 관리 AI Agent")

# --------------------------------------------------------------------------
# 2. 사용자 입력 및 채팅 히스토리 표시
# --------------------------------------------------------------------------
quick_prompt = ui.render_quick_prompts()

if "messages" not in st.session_state:
    st.session_state["messages"] = []

# [수정 2] 대화 기록 표시 루프 (도구 결과 시각화 추가)
for msg in st.session_state.messages:
    if isinstance(msg, HumanMessage):
        with st.chat_message("user"):
            st.write(msg.content)

    elif isinstance(msg, AIMessage):
        with st.chat_message("assistant"):
            st.write(msg.content)
            if "artifact" in msg.additional_kwargs:
                ui.render_analysis_result(msg.additional_kwargs["artifact"])

chat_input = st.chat_input("질문을 입력하세요.")
user_input = chat_input if chat_input else quick_prompt

# --------------------------------------------------------------------------
# 3. Agent 실행 로직
# --------------------------------------------------------------------------
if user_input:
    st.session_state["messages"].append(HumanMessage(content=user_input))
    with st.chat_message("user"):
        st.write(user_input)

    app = get_graph()
    config = {"configurable": {"thread_id": "thread-1"}}

    with st.chat_message("assistant"):
        status_container = st.status("🔍 AI Agent가 분석 중입니다...", expanded=True)
        message_placeholder = st.empty()

        full_response = ""
        analysis_artifact = None

        try:
            inputs = {"messages": st.session_state["messages"]}

            for event in app.stream(inputs, config=config):
                for node_name, state_update in event.items():

                    if node_name == "reasoner":
                        status_container.write("🧠 **[분석]** 사용자 의도를 파악하고 계획을 수립했습니다.")

                    elif node_name == "code_generator":
                        status_container.write("💻 **[설계]** 데이터 분석용 Python 코드를 생성했습니다.")
                        code = state_update.get("generated_code") or state_update.get("python_code", "")
                        with status_container.expander("생성된 코드 보기"):
                            st.code(code, language="python")

                    elif node_name == "code_executor":
                        status = state_update.get("execution_status")
                        if status == "success":
                            status_container.write("✅ **[실행]** 코드 실행을 성공적으로 완료했습니다.")
                            if "analysis_data" in state_update:
                                analysis_artifact = state_update["analysis_data"].get("last_run_result")
                        elif status == "error":
                            status_container.write(f"⚠️ **[오류]** 실행 실패, 재시도합니다.")

                    # 최종 답변 스트리밍
                    if "messages" in state_update and state_update["messages"]:
                        last_msg = state_update["messages"][-1]
                        if isinstance(last_msg, AIMessage) and last_msg.content:
                            full_response = last_msg.content
                            message_placeholder.markdown(full_response + " ▌")

            status_container.update(label="분석 완료", state="complete", expanded=False)
            message_placeholder.markdown(full_response)

            if analysis_artifact:
                ui.render_analysis_result(analysis_artifact)

            ai_msg = AIMessage(content=full_response)
            if analysis_artifact:
                ai_msg.additional_kwargs["artifact"] = analysis_artifact

            # 중복 추가 방지 (스트리밍 중 이미 추가된 경우가 아니라면 추가)
            if not st.session_state["messages"] or st.session_state["messages"][-1].content != full_response:
                st.session_state["messages"].append(ai_msg)

        except Exception as e:
            status_container.update(label="오류 발생", state="error")
            st.error(f"시스템 오류가 발생했습니다: {e}")

# --------------------------------------------------------------------------
# 4. HIL (Human-in-the-Loop)
# --------------------------------------------------------------------------
# hil_options = ["승인", "반려", "수정/피드백"]
#
# if 'messages' in st.session_state and st.session_state['messages']:
#     last_msg = st.session_state['messages'][-1]
#
#     if isinstance(last_msg, AIMessage) and ('승인' in last_msg.content or '확인' in last_msg.content):
#         with st.expander("결과 검토 및 승인 요청", expanded=True):
#             st.info("발주를 진행하기 위해 사용자의 승인이 필요합니다.")
#             with st.form("hil_form"):
#                 choice = st.radio("결정", hil_options, index=0)
#                 feedback = st.text_input("피드백 (수정/반려 시 입력)")
#                 submitted = st.form_submit_button("결정 적용")
#
#                 if submitted:
#                     decision_msg = f"결정: {choice}"
#                     if feedback: decision_msg += f", 사유: {feedback}"
#                     st.session_state['messages'].append(HumanMessage(content=decision_msg))
#                     st.rerun()

# --------------------------------------------------------------------------
# 5. 파일 다운로드 영역
# --------------------------------------------------------------------------
# (기존 코드 유지)
if "monthly_report_path" in st.session_state:
    file_path = st.session_state["monthly_report_path"]
    if os.path.exists(file_path):
        st.divider()
        with open(file_path, "rb") as f:
            st.download_button("📥 월말 구매 마감 리포트 다운로드", f, os.path.basename(file_path), key="dl_monthly", use_container_width=True)

if "po_status_path" in st.session_state:
    file_path = st.session_state["po_status_path"]
    if os.path.exists(file_path):
        if "monthly_report_path" not in st.session_state: st.divider()
        with open(file_path, "rb") as f:
            st.download_button("📥 발주 현황 공유 파일 다운로드", f, os.path.basename(file_path), key="dl_po", use_container_width=True)

if "supplier_eval_path" in st.session_state:
    file_path = st.session_state["supplier_eval_path"]
    if os.path.exists(file_path):
        if "monthly_report_path" not in st.session_state and "po_status_path" not in st.session_state: st.divider()
        with open(file_path, "rb") as f:
            st.download_button("📥 공급업체 평가 양식 다운로드", f, os.path.basename(file_path), key="dl_eval", use_container_width=True)