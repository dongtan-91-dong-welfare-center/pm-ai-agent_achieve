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

def extract_file_path_from_tool(content):
    """도구 실행 결과에서 파일 경로 추출"""
    try:
        if isinstance(content, dict):
            return content.get("file_path")
        if isinstance(content, str) and "file_path" in content:
            # 딕셔너리 형태의 문자열 파싱 시도
            try:
                # 안전하지 않은 eval 대신 ast.literal_eval 사용 권장되나,
                # 포맷이 불확실할 경우를 대비해 간단한 정규식이나 string search도 고려
                if content.strip().startswith("{"):
                    data = ast.literal_eval(content)
                    if isinstance(data, dict):
                        return data.get("file_path")
            except:
                pass

            # Markdown 링크 등에서 경로 추출 시도 (백업 로직)
            import re
            match = re.search(r'`(.*?\.xlsx)`', content)
            if match:
                return match.group(1)
    except:
        pass
    return None

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

        # 스트리밍 중 발생한 ToolMessage를 임시 저장할 리스트
        new_tool_messages = []

        # 새로운 요청이 오면 기존 다운로드 버튼 상태 초기화
        keys_to_clear = ["monthly_report_path", "po_status_path", "supplier_eval_path"]
        for key in keys_to_clear:
            if key in st.session_state:
                del st.session_state[key]

        try:
            inputs = {"messages": st.session_state["messages"]}

            # [Fix 1] 상태 업데이트 지연을 위한 임시 저장소 생성
            pending_paths = {}

            for event in app.stream(inputs, config=config):
                for node_name, state_update in event.items():

                    # 1. Reasoner (생각 및 대화)
                    if node_name == "reasoner":
                        messages = state_update.get("messages", [])
                        if messages:
                            last_msg = messages[-1]
                            if hasattr(last_msg, 'tool_calls') and last_msg.tool_calls:
                                tools_str = ", ".join([tc['name'] for tc in last_msg.tool_calls])
                                status_container.markdown(f"🧠 **[계획 수립]** `{tools_str}` 도구를 실행합니다.")
                            else:
                                content_preview = last_msg.content[:100] + "..." if len(
                                    last_msg.content) > 100 else last_msg.content
                                # status_container.markdown(f"🤔 **[생각/질문]** {content_preview}")

                    # 2. Tools (실행 및 경로 감지)
                    elif node_name == "tools":
                        tool_msgs = state_update.get("messages", [])
                        for t_msg in tool_msgs:
                            if isinstance(t_msg, ToolMessage):
                                # (1) UI 표시 (Write는 괜찮음)
                                if "create_" in t_msg.name:
                                    status_container.write(f"💾 **[파일 생성]** {t_msg.name} 완료")
                                else:
                                    status_container.write(f"🔧 **[실행 완료]** {t_msg.name}")
                                    # Expander 등이 필요하면 여기서 렌더링

                                # (2) [Fix 2] 세션 직접 수정 금지 -> 임시 변수(pending_paths)에 저장
                                file_path = extract_file_path_from_tool(t_msg.content)
                                if file_path:
                                    if "monthly" in t_msg.name:
                                        pending_paths["monthly_report_path"] = file_path
                                    elif "po_status" in t_msg.name:
                                        pending_paths["po_status_path"] = file_path
                                    elif "supplier" in t_msg.name:
                                        pending_paths["supplier_eval_path"] = file_path

                                new_tool_messages.append(t_msg)

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

            # [Fix 3] 루프 종료 후 상태 일괄 업데이트 (이때 Rerun 되어도 안전함)
            for key, path in pending_paths.items():
                st.session_state[key] = path

            status_container.update(label="분석 완료", state="complete", expanded=False)
            message_placeholder.markdown(full_response)

            if analysis_artifact:
                ui.render_analysis_result(analysis_artifact)

            # 메시지 저장 로직
            for tm in new_tool_messages:
                st.session_state["messages"].append(tm)

            ai_msg = AIMessage(content=full_response)
            if analysis_artifact:
                ai_msg.additional_kwargs["artifact"] = analysis_artifact

            if not st.session_state["messages"] or st.session_state["messages"][-1].content != full_response:
                st.session_state["messages"].append(ai_msg)

        # GeneratorExit 및 모든 시스템 예외 처리
        except BaseException as e:
            # GeneratorExit는 정상 종료의 일종일 수 있으므로 무시하거나 로그만 남김
            if type(e).__name__ == "GeneratorExit":
                pass
            else:
                status_container.update(label="오류 발생", state="error")
                st.error(f"시스템 오류 발생: {str(e)}")

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