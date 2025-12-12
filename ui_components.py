import streamlit as st
import pandas as pd
import os
import re
from data_loader import load_master_data, save_uploaded_file_by_type, FILE_PROCESSORS
from tools import button_tools

PRIMARY_COLOR = "#d78632"  # Daewoong Orange


def setup_page_config():
    """페이지 기본 설정 및 CSS 스타일 적용"""
    st.set_page_config(page_title="생산 관리 AI Agent", layout="wide")

    st.markdown(
        f"""
        <style>
        h1, h2, h3 {{ color: #494c50; }}
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
        div[data-testid="stAlert"] {{ border-left: 4px solid {PRIMARY_COLOR}; }}
        section[data-testid="stSidebar"] {{ background-color: #f4f5f9; }}
        </style>
        """,
        unsafe_allow_html=True
    )


def render_sidebar():
    """사이드바: 파일 업로드 및 데이터 탐색기"""
    with st.sidebar:
        st.header("Data Management")

        # 1. 파일 업로드
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

        # 2. 데이터 탐색기
        st.subheader("데이터 탐색기")
        try:
            current_db = load_master_data()
            if current_db:
                selected_table = st.selectbox("조회할 테이블", list(current_db.keys()))
                if selected_table:
                    st.dataframe(current_db[selected_table], height=200)
            else:
                st.info("데이터가 없습니다.")
        except Exception:
            st.warning("데이터 로드 실패")


def render_quick_prompts():
    """
    [상단 버튼 영역]
    - 수정: '공급업체 평가' 버튼 클릭 시 Agent(채팅)를 호출하지 않도록 clicked_prompt 제거
    """
    st.markdown("###### 👋 자주 사용하는 질문")

    col1, col2, col3 = st.columns(3)
    clicked_prompt = None

    # =========================================================================
    # 버튼 1: 월말 구매 마감 리포트 (Agent 호출 유지)
    # =========================================================================
    if col1.button("📅 월말 구매 마감 리포트", use_container_width=True):
        clicked_prompt = "월말 리포트 보내줘"
        with st.spinner("데이터 집계 및 월말 리포트 생성 중입니다..."):
            try:
                # Logic 호출
                result_message = button_tools.run_monthly_closing_process()

                if "실패" in result_message or "오류" in result_message:
                    st.error(result_message)
                else:
                    st.success(result_message)
                    # 파일 경로 추출 및 세션 저장
                    match = re.search(r"리포트 생성 완료:\s*(.*?.xlsx)", result_message)
                    if match:
                        st.session_state['monthly_report_path'] = match.group(1).strip()
            except Exception as e:
                st.error(f"오류 발생: {str(e)}")

    # =========================================================================
    # 버튼 2: 공급업체 평가 (Agent Bypass - 즉시 실행)
    # =========================================================================
    if col2.button("📊 공급업체 평가", use_container_width=True):
        # [수정] clicked_prompt 할당 삭제 -> Agent 실행 안 함

        with st.spinner("입고 이력 및 부적합 내역 분석 중..."):
            try:
                # Logic 호출
                result_msg = button_tools.run_supplier_evaluation_report()

                if "완료" in result_msg:
                    st.success(result_msg)
                    # 경로 추출 및 세션 저장
                    match = re.search(r'평가양식 생성 완료:\s*(.*?.xlsx)', result_msg)
                    if match:
                        st.session_state['supplier_eval_path'] = match.group(1).strip()
                else:
                    st.error(result_msg)

            except Exception as e:
                st.error(f"오류 발생: {e}")

    # =========================================================================
    # 버튼 3: 발주 현황 공유 파일 (Agent Bypass - 즉시 실행)
    # =========================================================================
    if col3.button("📂 발주 현황 공유 파일", use_container_width=True):
        with st.spinner("최근 2년 데이터를 조회하여 시트 분할 중입니다..."):
            try:
                # Logic 호출
                result_msg = button_tools.run_po_status_report()

                if "파일 생성 완료" in result_msg:
                    st.success(result_msg)
                    # 파일 경로 추출 및 세션 저장
                    match = re.search(r'파일 생성 완료:\s*(.*?.xlsx)', result_msg)
                    if match:
                        st.session_state['po_status_path'] = match.group(1).strip()
                elif "알림" in result_msg:
                    st.warning(result_msg)
                else:
                    st.error(result_msg)
            except Exception as e:
                st.error(f"오류 발생: {e}")

    return clicked_prompt


def render_analysis_result(result_data):
    """분석 결과(DataFrame, Scalar 등) 시각화"""
    chart_type = "table"
    df_viz = None
    scalar_value = None
    raw_data = result_data

    if isinstance(result_data, dict) and "type" in result_data and "data" in result_data:
        chart_type = result_data["type"]
        raw_data = result_data["data"]

    if isinstance(raw_data, dict) and "columns" in raw_data:
        try:
            df_viz = pd.DataFrame(data=raw_data["data"], columns=raw_data["columns"])
        except:
            pass
    elif isinstance(raw_data, pd.DataFrame):
        df_viz = raw_data
    elif isinstance(raw_data, (int, float, str)):
        scalar_value = raw_data

    if scalar_value is not None:
        if isinstance(scalar_value, (int, float)):
            st.metric("분석 결과", f"{scalar_value:,.0f}")
        else:
            st.info(f"분석 결과: {scalar_value}")
    elif df_viz is not None and not df_viz.empty:
        with st.expander(f"분석 결과 데이터 ({chart_type})", expanded=True):
            if chart_type == "line":
                st.line_chart(df_viz)
            elif chart_type == "bar":
                st.bar_chart(df_viz)
            else:
                st.dataframe(df_viz, width="stretch")
    elif isinstance(raw_data, list):
        st.write("목록 결과:")
        st.json(raw_data)