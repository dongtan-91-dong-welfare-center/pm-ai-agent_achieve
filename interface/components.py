"""
설명: Streamlit UI를 구성하는 재사용 가능한 컴포넌트 및 스타일 정의 모듈

[Role & Responsibility]
- Component Design: 사이드바, 퀵 프롬프트, 분석 결과 시각화(Chart/Table) 로직을 모듈화하여 main.py의 복잡도를 낮춥니다.
- Interaction Logic: 버튼 클릭 시 Agent 호출 여부(Trigger vs Bypass)를 결정하는 로직을 포함합니다.
"""

from datetime import datetime
import streamlit as st
import pandas as pd
import base64
import matplotlib.pyplot as plt
from data_loader import load_master_data, save_uploaded_file_by_type, FILE_PROCESSORS

# 브랜드 컬러 정의 (Orange)
PRIMARY_COLOR = "#d78632"

def setup_page_config():
    """
    [Init] 페이지 기본 설정 및 커스텀 CSS 스타일 적용
    - 브라우저 탭 타이틀, 레이아웃(Wide) 설정
    - 버튼 및 사이드바 스타일 오버라이딩 (Brand Identity 반영)
    """
    st.set_page_config(page_title="생산 관리 AI Agent", layout="wide")

    # CSS Injection
    st.markdown(
        f"""
        <style>
        /* 헤더 폰트 색상 조정 */
        h1, h2, h3 {{ color: #494c50; }}

        /* 버튼 스타일 커스터마이징 (Hover 효과 포함) */
        div.stButton > button {{
            border: 1px solid {PRIMARY_COLOR};
            color: {PRIMARY_COLOR};
            background-color: white;
            border-radius: 8px;
            font-weight: 500;
            transition: all 0.2s ease;
        }}
        div.stButton > button:hover {{
            border-color: {PRIMARY_COLOR};
            background-color: {PRIMARY_COLOR};
            color: white;
        }}

        /* 알림 메시지(Alert) 좌측 강조선 */
        div[data-testid="stAlert"] {{ border-left: 4px solid {PRIMARY_COLOR}; }}

        /* 사이드바 배경색 */
        section[data-testid="stSidebar"] {{ background-color: #f4f5f9; }}
        </style>
        """,
        unsafe_allow_html=True
    )


def render_sidebar():
    """
    [Sidebar] 데이터 관리 및 파일 업로더 영역
    - 사용자가 엑셀 파일을 업로드하면 data_loader를 통해 파싱 및 저장합니다.
    - Data Explorer: 현재 로드된 마스터 데이터(DB)를 미리보기 형태로 제공하여 정합성을 체크합니다.
    """
    with st.sidebar:
        st.header("Data Management")

        # 1. 파일 업로드 섹션
        with st.expander("마스터 파일 업로드", expanded=True):
            # 업로드할 데이터 유형 선택 (product, bom, stock 등)
            source_type = st.selectbox("업로드할 파일 유형", options=list(FILE_PROCESSORS.keys()))
            uploaded_file = st.file_uploader("엑셀 파일 선택", type=["xlsx"])

            if uploaded_file and st.button("데이터 추가"):
                with st.spinner("데이터 처리 및 적재 중..."):
                    # data_loader 모듈을 통해 파싱 및 병합 수행
                    success, msg = save_uploaded_file_by_type(uploaded_file, source_type)
                    if success:
                        st.success(msg)
                    else:
                        st.error(msg)

        st.divider()

        # 2. 데이터 탐색기 (Debugging Tool)
        st.subheader("데이터 탐색기")
        try:
            current_db = load_master_data()
            if current_db:
                # 테이블 선택 후 상위 5행 등 미리보기
                selected_table = st.selectbox("조회할 테이블", list(current_db.keys()))
                if selected_table:
                    st.dataframe(current_db[selected_table], height=200)
            else:
                st.info("로드된 데이터가 없습니다.")
        except Exception:
            st.warning("데이터 로드 중 오류가 발생했습니다.")


def render_quick_prompts():
    """
    [Action Buttons] 상단 퀵 액션 버튼 영역

    Logic Difference:
    1. Agent Trigger: 버튼 클릭 시 특정 텍스트(예: "리포트 줘")를 반환하여 main.py에서 Agent가 실행되도록 함.
    2. Direct Execution: 버튼 클릭 시 즉시 Python 함수를 실행하고 결과만 표시 (Agent LLM 비용 절감).
    3. Agent에게 명확한 날짜를 포함하여 지시합니다.

    Returns:
        str | None: Agent에게 전달할 메시지 텍스트 (Direct Execution인 경우 None 반환)
    """
    st.markdown("###### 👋 자주 사용하는 질문")

    col1, col2, col3 = st.columns(3)
    clicked_prompt = None

    # 현재 날짜 계산
    now = datetime.now()
    current_ym = f"{now.year}년 {now.month}월"

    # =========================================================================
    # 버튼 1: 월말 구매 마감 리포트 (기존 유지 - 잘 동작함)
    # =========================================================================
    if col1.button("📅 월말 구매 마감 리포트", width="stretch"):
        clicked_prompt = (
            f"{current_ym} 구매 마감 현황을 먼저 '분석(Analyze)'하여 요약표를 보여주고, "
            "특이사항이 없다면 '리포트 파일(Excel)'을 생성해줘."
        )
    # =========================================================================
    # [수정] 버튼 2: 공급업체 평가
    # 키워드: '평가 관리 양식' (단순 '평가해줘'는 LLM이 직접 계산하려고 함)
    # =========================================================================
    if col2.button("📊 공급업체 평가", width="stretch"):
        clicked_prompt = (
            "현재 공급업체들의 입고 및 부적합 내역을 먼저 '분석(Analyze)'하여 결과를 보여주고, "
            "이후 '평가 양식 파일'을 생성해줘."
        )
    # =========================================================================
    # [수정] 버튼 3: 발주 현황 공유 파일
    # 키워드: '발주 현황 공유 파일', '최근 2년' (도구 설명과 일치시킴)
    # =========================================================================
    if col3.button("📂 발주 현황 공유 파일", width="stretch"):
        clicked_prompt = (
            "최근 2년치 발주 현황 데이터를 제품 유형별로 '분석(Analyze)'하여 요약해주고, "
            "그 다음 '공유 파일(Excel)'을 생성해줘."
        )
    return clicked_prompt


def render_analysis_result(result_data):
    """
    [Visualization] Agent의 분석 결과(Artifact)를 유형에 맞게 렌더링
    """
    if result_data is None:
        st.info("결과 데이터가 없습니다.")
        return

    # ---------------------------------------------------------
    # Case 1: Base64 Encoded Image (저장된 그래프)
    # ---------------------------------------------------------
    if isinstance(result_data, dict) and result_data.get("type") == "image_base64":
        try:
            # Base64 문자열 -> 이미지 디코딩
            img_data = base64.b64decode(result_data["data"])
            st.image(img_data, caption="생성된 시각화 결과")
        except Exception as e:
            st.error(f"이미지 렌더링 실패: {e}")
        return

    # ---------------------------------------------------------
    # Case 2: Live Figure (실시간 객체)
    # ---------------------------------------------------------
    if hasattr(result_data, "figure") or isinstance(result_data, plt.Figure):
        st.pyplot(result_data)
        return

    # ---------------------------------------------------------
    # Case 3: 일반 데이터 (DataFrame, Dict, List, Scalar)
    # ---------------------------------------------------------
    chart_type = "table"
    df_viz = None
    scalar_value = None
    raw_data = result_data

    # 1. 직렬화된 데이터 구조(Dict) 파싱
    if isinstance(result_data, dict) and "type" in result_data and "data" in result_data:
        chart_type = result_data.get("type", "table")
        raw_data = result_data["data"]
        # DataFrame 복원 시도
        if isinstance(raw_data, dict) and "columns" in raw_data:
            try:
                df_viz = pd.DataFrame(data=raw_data["data"], columns=raw_data["columns"])
            except:
                pass

    # 2. Raw DataFrame인 경우
    elif isinstance(raw_data, pd.DataFrame):
        df_viz = raw_data

    # 3. 단순 값(Scalar)인 경우
    elif isinstance(raw_data, (int, float, str)):
        scalar_value = raw_data

    # 4. 리스트인 경우
    elif isinstance(raw_data, list):
        st.write("목록 결과:")
        st.json(raw_data)
        return

    # ---------------------------------------------------------
    # 최종 렌더링 (Priority: Scalar -> Chart -> Table)
    # ---------------------------------------------------------
    if scalar_value is not None:
        if isinstance(scalar_value, (int, float)):
            st.metric("분석 결과", f"{scalar_value:,.0f}")
        else:
            st.info(f"분석 결과: {scalar_value}")

    elif df_viz is not None and not df_viz.empty:
        # [수정된 부분] chart_type에 따라 적절한 그래프 그리기
        with st.expander(f"📊 분석 결과 확인 ({chart_type})", expanded=True):
            if chart_type == "line":
                st.line_chart(df_viz)
            elif chart_type == "bar":
                st.bar_chart(df_viz)
            elif chart_type == "area":
                st.area_chart(df_viz)
            else:
                # 기본값: 테이블 표시
                st.dataframe(df_viz, width="stretch")

    else:
        # 그 외 처리 못한 데이터는 JSON으로 표시
        with st.expander("원본 데이터 확인"):
            st.json(result_data)