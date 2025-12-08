import streamlit as st
import pandas as pd
from langchain_core.messages import HumanMessage, AIMessage

# 페이지 설정
st.set_page_config(page_title="생산 관리 AI Agent", layout="wide")

PRIMARY = "#d78632"  # Daewoong Orange

st.markdown(
    f"""
    <style>
    /* ------------------------------
       메인 제목 색상 (h1, h2 등)
    ------------------------------ */
    h1, h2, h3 {{
        color: #494c50;
    }}
    /* ------------------------------
       버튼
    ------------------------------ */
    div.stButton > button {{
        border: 1px solid {PRIMARY};
        color: {PRIMARY};
        background-color: white;
        border-radius: 8px;
        font-weight: 500;
        transition: all 0.2s ease;
    }}
    div.stButton > button:hover {{
        border-color: {PRIMARY};
        background-color: {PRIMARY};
        color: white;
    }}

    /* ------------------------------
       Selectbox / Multiselect
    ------------------------------ */
    div[data-baseweb="select"] > div {{
        border: 1px solid {PRIMARY} !important;
        border-radius: 6px !important;
    }}
    div[data-baseweb="select"] svg {{
        color: {PRIMARY} !important;
    }}
    div[data-baseweb="select"] > div:hover {{
        box-shadow: 0 0 0 1px {PRIMARY};
    }}

    /* ------------------------------
       Slider 색상
    ------------------------------ */
    .stSlider [data-baseweb="slider"] > div[role="slider"] {{
        background-color: {PRIMARY} !important;
        border: 2px solid {PRIMARY} !important;
    }}
    .stSlider [data-baseweb="track"] > div {{
        background-color: {PRIMARY} !important;
    }}
    /* ------------------------------
       사이드바
    ------------------------------ */
    section[data-testid="stSidebar"] {{
        background-color: #f4f5f9;
    }}
    section[data-testid="stSidebar"] h2, 
    section[data-testid="stSidebar"] h3 {{
        color: #494c50;
    }}

    /* ------------------------------
       알림 박스 (st.success / st.warning 등)
    ------------------------------ */
    div[data-testid="stAlert"] {{
        border-left: 4px solid {PRIMARY};
    }}
    </style>
    """,
    unsafe_allow_html=True
)

# 리소스 로딩 (캐싱 적용)
@st.cache_resource(show_spinner="AI Agent를 초기화 중입니다...")
def get_agent_graph():
    """Agent Graph를 한 번만 로드하여 캐싱합니다."""
    from agent_graph import graph
    return graph


@st.cache_resource
def get_data_loader_modules():
    """데이터 로더 모듈을 지연 로딩합니다."""
    from data_loader import TABLE_SCHEMA, save_uploaded_file_by_type, load_master_data, FILE_PROCESSORS
    return TABLE_SCHEMA, save_uploaded_file_by_type, load_master_data, FILE_PROCESSORS

# 모듈 로드
_, save_uploaded_file_by_type, load_master_data, FILE_PROCESSORS = get_data_loader_modules()


# 유틸리티 함수: 분석 결과 시각화
def render_analysis_result(result_data):
    """
    Backend에서 전달받은 데이터(Dict/DataFrame/Scalar)를 시각화합니다.
    숫자, 텍스트, 데이터프레임 등 다양한 타입을 지원합니다.
    """
    chart_type = "table"
    df_viz = None
    scalar_value = None
    raw_data_content = result_data

    # 딕셔너리 구조인 경우 ({type: ..., data: ...})
    if isinstance(result_data, dict) and "type" in result_data and "data" in result_data:
        chart_type = result_data["type"]
        raw_data_content = result_data["data"]

    # DataFrame 복원 (msgpack 직렬화 해제된 Dict 구조)
    if isinstance(raw_data_content, dict) and "columns" in raw_data_content and "data" in raw_data_content:
        try:
            df_viz = pd.DataFrame(
                data=raw_data_content["data"],
                columns=raw_data_content["columns"],
                index=raw_data_content.get("index")
            )
        except Exception:
            df_viz = None
    # 이미 DataFrame인 경우
    elif isinstance(raw_data_content, pd.DataFrame):
        df_viz = raw_data_content
    # 단순 숫자나 문자열인 경우 (Scalar)
    elif isinstance(raw_data_content, (int, float, str)):
        scalar_value = raw_data_content

    # 실제 렌더링
    # 단순 숫자/텍스트 (KPI 지표 등)
    if scalar_value is not None:
        if isinstance(scalar_value, (int, float)):
            st.metric(label="분석 결과", value=f"{scalar_value:,.0f}")
        else:
            st.info(f"분석 결과: {scalar_value}")

    # DataFrame 시각화
    elif df_viz is not None and not df_viz.empty:
        with st.expander(f"분석 결과 데이터 ({chart_type})", expanded=True):
            if chart_type == "line":
                st.line_chart(df_viz)
            elif chart_type == "bar":
                st.bar_chart(df_viz)
            elif chart_type == "area":
                st.area_chart(df_viz)
            else:
                st.dataframe(df_viz, width="stretch")

    # 리스트 데이터
    elif isinstance(raw_data_content, list):
        st.write("목록 결과:")
        st.json(raw_data_content)


# 사이드바 UI
with st.sidebar:
    st.header("Data Management")

    # 파일 업로드
    with st.expander("마스터 파일 업로드", expanded=True):
        source_type = st.selectbox("업로드할 파일 유형", options=list(FILE_PROCESSORS.keys()))
        uploaded_file = st.file_uploader("엑셀 파일 선택", type=["xlsx"])
        if uploaded_file and st.button("데이터 추가"):
            with st.spinner("처리 중..."):
                success, msg = save_uploaded_file_by_type(uploaded_file, source_type)
                if success:
                    st.success(msg)
                else:
                    st.error(msg)

    st.divider()

    # 데이터 탐색기
    st.subheader("데이터 탐색기")
    try:
        # Mock Data 로드 (테스트용) 혹은 load_master_data() 사용
        # from agent_nodes import load_mock_data_for_test
        # current_db = load_mock_data_for_test()
        current_db = load_master_data()  # 실제 환경용

        if current_db:
            selected_table = st.selectbox("조회할 테이블", list(current_db.keys()))
            if selected_table:
                st.dataframe(current_db[selected_table], height=200)
    except Exception:
        st.warning("데이터를 로드할 수 없습니다.")

# 메인 채팅 인터페이스
st.title("생산 관리 AI Agent")

if "messages" not in st.session_state:
    st.session_state["messages"] = []

# 히스토리 렌더링
for msg in st.session_state.messages:
    if isinstance(msg, HumanMessage):
        with st.chat_message("user"):
            st.write(msg.content)
    elif isinstance(msg, AIMessage):
        with st.chat_message("assistant"):
            st.write(msg.content)
            # Artifact(시각화 데이터)가 있으면 출력
            if "artifact" in msg.additional_kwargs:
                render_analysis_result(msg.additional_kwargs["artifact"])

# Agent 로드
try:
    graph = get_agent_graph()
except Exception as e:
    st.error(f"Agent 초기화 실패: {e}")
    st.stop()

# 사용자 입력 처리
# ... (이전 코드: Agent 초기화 부분 등)

# =========================================================
# [UI 개선] 빠른 실행 버튼 (Quick Prompts)
# =========================================================
st.markdown("###### 👋 자주 사용하는 질문")  # 섹션 제목 (선택 사항)

# 버튼 레이아웃 (3개 컬럼)
col1, col2, col3 = st.columns(3)
clicked_prompt = None

# 버튼 생성 및 클릭 이벤트 처리
# 버튼 라벨은 짧게, 실제 전송되는 메시지는 길게 설정
if col1.button("📅 월말 구매 마감 리포트", use_container_width=True):
    clicked_prompt = "월말 리포트 보내줘"

if col2.button("📊 당월 자재 소요량", use_container_width=True):
    clicked_prompt = "당월 자재별 소요량 보내줘"

if col3.button("📂 발주 현황 공유 파일", use_container_width=True):
    clicked_prompt = "자재 발주 현황 공유용 파일 만들어줘"

# =========================================================
# 사용자 입력 처리 (텍스트 입력 OR 버튼 클릭)
# =========================================================
chat_input_text = st.chat_input("질문을 입력하세요. (예: M-1001의 재고 가치는?)")

# 텍스트 입력이 있으면 그것을 우선, 없으면 버튼 클릭 값을 사용
user_input = chat_input_text if chat_input_text else clicked_prompt

if user_input:
    # 1. 사용자 메시지 표시 & 저장
    with st.chat_message("user"):
        st.write(user_input)
    st.session_state["messages"].append(HumanMessage(content=user_input))

    # 2. Agent 실행 (스트리밍) - 기존 코드와 동일
    config = {"configurable": {"thread_id": "1"}}

    with st.chat_message("assistant"):
        message_placeholder = st.empty()
        full_response = ""
        analysis_artifact = None

        try:
            # LangGraph 실행
            events = graph.stream({"messages": st.session_state["messages"]}, config)

            for event in events:
                # ... (이하 기존 Agent 실행 로직 그대로 유지) ...
                if "reasoner" in event:
                    payload = event["reasoner"]
                    if isinstance(payload, dict) and "messages" in payload:
                        last_msg = payload["messages"][-1]
                        if hasattr(last_msg, 'content') and last_msg.content:
                            full_response = last_msg.content
                            message_placeholder.markdown(full_response + " ▌")

                if "code_generator" in event:
                    payload = event["code_generator"]
                    if "generated_code" in payload:
                        gen_code = payload["generated_code"]
                        with st.expander("AI가 생성한 분석 코드 확인", expanded=False):
                            st.code(gen_code, language="python")

                if "code_executor" in event:
                    payload = event["code_executor"]
                    if "analysis_data" in payload:
                        result = payload["analysis_data"].get("last_run_result")
                        if result is not None:
                            render_analysis_result(result)
                            analysis_artifact = result

            message_placeholder.markdown(full_response)

            ai_msg = AIMessage(content=full_response)
            if analysis_artifact is not None:
                ai_msg.additional_kwargs["artifact"] = analysis_artifact

            st.session_state["messages"].append(ai_msg)

        except Exception as e:
            st.error(f"실행 중 오류가 발생했습니다: {e}")
