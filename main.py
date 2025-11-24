import streamlit as st
import pandas as pd
from agent_graph import graph
from langchain_core.messages import HumanMessage, AIMessage
import data_loader

# 공통 함수 - 시각화 렌더러
def render_analysis_result(result_data):
    """
    Backend에서 전달받은 데이터(Dict/DataFrame)를 시각화합니다.
    채팅 히스토리 출력 시와 실시간 스트리밍 시 공통으로 사용됩니다.
    """
    chart_type = "table"
    df_viz = None
    raw_data = result_data

    # 1. 데이터 구조 파악 (Dict vs DataFrame)
    if isinstance(raw_data, dict) and "type" in raw_data and "data" in raw_data:
        chart_type = raw_data["type"]
        raw_data_content = raw_data["data"]
    else:
        raw_data_content = raw_data

    # 2. DataFrame 복원 (msgpack 직렬화 해제)
    if isinstance(raw_data_content, dict) and "columns" in raw_data_content and "data" in raw_data_content:
        try:
            df_viz = pd.DataFrame(
                data=raw_data_content["data"],
                columns=raw_data_content["columns"],
                index=raw_data_content.get("index")
            )
        except Exception:
            df_viz = None  # 복원 실패
    elif isinstance(raw_data_content, pd.DataFrame):
        df_viz = raw_data_content

    # 3. 실제 렌더링
    if df_viz is not None and not df_viz.empty:
        with st.expander(f"분석 결과 ({chart_type})", expanded=True):
            if chart_type == "line":
                st.line_chart(df_viz)
            elif chart_type == "bar":
                st.bar_chart(df_viz)
            elif chart_type == "area":
                st.area_chart(df_viz)
            else:
                st.dataframe(df_viz, use_container_width=True)
    else:
        st.caption("※ 시각화할 데이터가 없습니다.")

# 페이지 설정
st.set_page_config(page_title="생산 관리 AI Agent", layout="wide")

# [사이드바] 데이터 베이스 관리
with st.sidebar:
    st.header("Data Management")

    # 엑셀 파일 업로드 섹션
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
                    # 캐시 데이터 갱신을 위해 필요한 경우 st.rerun() 사용 가능
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

# 기존 채팅 히스토리 렌더링
for msg in st.session_state.messages:
    if isinstance(msg, HumanMessage):
        with st.chat_message("user"):
            st.write(msg.content)
    elif isinstance(msg, AIMessage):
        with st.chat_message("assistant"):
            st.write(msg.content)
            # 저장된 시각화 데이터가 있는지 확인
            if "artifact" in msg.additional_kwargs:
                render_analysis_result(msg.additional_kwargs["artifact"])

# Langgraph 실행 및 응답 처리
user_input = st.chat_input("생산 계획 ID(PL-2024-001)에 대한 소요량을 분석해줘.")

if user_input:
    # 사용자 메시지 UI 표시
    with st.chat_message("user"):
        st.write(user_input)
    st.session_state["messages"].append(HumanMessage(content=user_input))

    # LangGraph 실행 설정
    config = {"configurable": {"thread_id": "1"}}

    # AI 응답 처리(스트리밍)
    with st.chat_message("assistant"):
        message_placeholder = st.empty()
        full_response = ""

        # LangGraph 스트림 실행
        events = graph.stream({"messages": st.session_state["messages"]}, config)

        for event in events:
            # [디버깅용] 어떤 이벤트가 들어오는지 화면에 잠시 출력합니다. (테스트 후 주석 처리)
            # with st.expander("🔍 Debug: Event Stream", expanded=False):
            #     st.write(event)

            # [A] Reasoner (LLM 답변) 처리
            if "reasoner" in event:
                msg = event["reasoner"]["messages"][-1]
                if msg.content:
                    if isinstance(msg.content, str):
                        full_response += msg.content
                    elif isinstance(msg.content, list):
                        for part in msg.content:
                            if isinstance(part, dict) and "text" in part:
                                full_response += part["text"]
                    message_placeholder.markdown(full_response + " ▌")

            # [B] Finalize Order
            if "finalize_order" in event:
                msg = event["finalize_order"]["messages"][-1]
                full_response += f"\n\n✅ {msg.content}"
                message_placeholder.markdown(full_response)

            # [D] Code Executor (실시간 시각화 및 데이터 캡처)
            # 중요: agent_graph.py에서 노드 이름을 "code_executor"로 설정했는지 확인 필수!
            if "code_executor" in event:
                node_output = event["code_executor"]

                # 데이터 추출
                analysis_data = node_output.get("analysis_data", {})
                last_result = analysis_data.get("last_run_result")

                # [디버깅] 데이터가 도착했다면 로그를 띄웁니다.
                if last_result:
                    print("✅ 시각화 데이터 수신 성공!")  # 터미널 로그 확인용

                if last_result is not None:
                    # 화면 렌더링 (함수 호출)
                    render_analysis_result(last_result)

                    # 데이터 캡처 (저장용)
                    analysis_artifact = last_result

                # 만약 last_result가 없으면 에러 메시지를 표시해봅니다.
                else:
                    st.warning("⚠️ Code Executor가 실행되었으나 결과 데이터(last_run_result)가 비어있습니다.")
                    with st.expander("Node Output 확인"):
                        st.write(node_output)

        message_placeholder.markdown(full_response)
    # AI 응답 저장
    st.session_state["messages"].append(AIMessage(content=full_response))