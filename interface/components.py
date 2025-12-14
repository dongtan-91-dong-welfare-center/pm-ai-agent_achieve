"""
설명: Streamlit UI를 구성하는 재사용 가능한 컴포넌트 및 스타일 정의 모듈

[Role & Responsibility]
- Component Design: 사이드바, 퀵 프롬프트, 분석 결과 시각화(Chart/Table) 로직을 모듈화하여 main.py의 복잡도를 낮춥니다.
- Interaction Logic: 버튼 클릭 시 Agent 호출 여부(Trigger vs Bypass)를 결정하는 로직을 포함합니다.
"""

import streamlit as st
import pandas as pd
import os
import re
from data_loader import load_master_data, save_uploaded_file_by_type, FILE_PROCESSORS
from tools import button_tools

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
    - Func-112 (데이터 적재): 사용자가 엑셀 파일을 업로드하면 data_loader를 통해 파싱 및 저장합니다.
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

    Returns:
        str | None: Agent에게 전달할 메시지 텍스트 (Direct Execution인 경우 None 반환)
    """
    st.markdown("###### 👋 자주 사용하는 질문")

    col1, col2, col3 = st.columns(3)
    clicked_prompt = None

    # =========================================================================
    # 버튼 1: 월말 구매 마감 리포트 (기존 유지 - 잘 동작함)
    # =========================================================================
    if col1.button("📅 월말 구매 마감 리포트", use_container_width=True):
        clicked_prompt = "이번 달 구매 마감 결과를 알려주고, 리포트를 생성해줘."

    # =========================================================================
    # [수정] 버튼 2: 공급업체 평가
    # 키워드: '평가 관리 양식' (단순 '평가해줘'는 LLM이 직접 계산하려고 함)
    # =========================================================================
    if col2.button("📊 공급업체 평가", use_container_width=True):
        clicked_prompt = "공급업체 평가 관리 양식(엑셀)을 생성해줘."

    # =========================================================================
    # [수정] 버튼 3: 발주 현황 공유 파일
    # 키워드: '발주 현황 공유 파일', '최근 2년' (도구 설명과 일치시킴)
    # =========================================================================
    if col3.button("📂 발주 현황 공유 파일", use_container_width=True):
        clicked_prompt = "최근 2년치 발주 현황 공유 파일을 생성해줘."

    return clicked_prompt

def render_analysis_result(result_data):
    """
    [Visualization] Agent의 분석 결과(Artifact)를 유형에 맞게 렌더링

    Supported Types:
    1. Table (DataFrame): 표 형태로 표시
    2. Chart (Line/Bar): 그래프 시각화
    3. Scalar (Int/Float): 지표(Metric) 형태로 표시
    4. Text/JSON: 일반 텍스트 표시

    Args:
        result_data (dict | DataFrame | Scalar): 직렬화된 분석 결과
    """
    chart_type = "table"
    df_viz = None
    scalar_value = None
    raw_data = result_data

    # 1. 직렬화된 데이터 구조(Dict) 파싱
    if isinstance(result_data, dict) and "type" in result_data and "data" in result_data:
        chart_type = result_data["type"]
        raw_data = result_data["data"]

    # 2. 데이터 타입별 변환 (DataFrame 재구성)
    if isinstance(raw_data, dict) and "columns" in raw_data:
        # Pandas Split Orient 구조 복원
        try:
            df_viz = pd.DataFrame(data=raw_data["data"], columns=raw_data["columns"])
        except:
            pass
    elif isinstance(raw_data, pd.DataFrame):
        df_viz = raw_data
    elif isinstance(raw_data, (int, float, str)):
        scalar_value = raw_data

    # 3. 렌더링 (Priority: Scalar -> Chart/Table -> JSON)
    if scalar_value is not None:
        if isinstance(scalar_value, (int, float)):
            st.metric("분석 결과", f"{scalar_value:,.0f}")
        else:
            st.info(f"분석 결과: {scalar_value}")

    elif df_viz is not None and not df_viz.empty:
        # 데이터가 많을 수 있으므로 Expander 내부에 표시
        with st.expander(f"분석 결과 데이터 ({chart_type})", expanded=True):
            if chart_type == "line":
                st.line_chart(df_viz)
            elif chart_type == "bar":
                st.bar_chart(df_viz)
            else:
                # use_container_width=True (st.dataframe의 stretch 옵션)
                st.dataframe(df_viz, use_container_width=True)

    elif isinstance(raw_data, list):
        st.write("목록 결과:")
        st.json(raw_data)