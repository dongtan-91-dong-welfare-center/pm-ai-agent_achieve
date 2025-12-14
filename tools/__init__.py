"""
설명: tools 패키지의 진입점(Entry Point)이자, AI Agent가 사용할 도구들의 레지스트리(Registry)입니다.

[Role & Responsibility]
- 모듈화(Modularity): 기능별로 분리된(stock, order, report) 도구들을 하나로 묶어 외부로 노출합니다.
- 의존성 관리(Dependency): DB 인스턴스, 설정 값(OUTPUT_DIR) 등 공통 자원을 관리합니다.
- 도구 등록(Registration): LLM에게 바인딩(bind_tools)될 함수 리스트(`AGENT_TOOLS`)를 정의합니다.
"""

# -------------------------------------------------------------------------
# 1. 공통 자원 및 유틸리티 노출 (Shared Resources)
# -------------------------------------------------------------------------
# [핵심] 다른 모듈에서 'from tools import DB'로 접근할 수 있도록 편의성을 제공합니다.
# DB: 전역 데이터베이스 인스턴스 (Singleton 패턴 유사)
# OUTPUT_DIR: 생성된 보고서 파일이 저장될 경로
from .shared import DB, OUTPUT_DIR
from .utils import get_db, df_to_markdown

# -------------------------------------------------------------------------
# 2. 도구 모듈 임포트 (Tool Imports)
# -------------------------------------------------------------------------

# A. 재고 관련 도구 (Stock Management)
# 용도: 현재 재고 조회, 장기 재고 분석, 자재 상세 정보 확인
from .stock_tools import (
    get_current_stock,              # 실시간 가용 재고 조회
    get_product_detail,             # 자재 마스터(특성) 정보 조회
    check_long_term_stock_criteria, # 장기 재고 판별 기준(일수) 확인 (Adr-002)
    get_stock_status,               # 재고 상태 종합 대시보드 데이터 조회
    analyze_long_term_stock,        # 장기 재고 상세 분석 리포트 데이터 생성
)

# B. 발주 및 소요량 도구 (Order & MRP)
# 용도: 소요량 전개(MRP), 발주량 계산(Adr-008), 발주 실행
from .order_tools import (
    calculate_gross_requirement,    # 총 소요량 계산 (생산계획 * BOM)
    generate_purchase_prediction,   # [핵심] 발주 필요량 예측 (총 소요 - 가용 재고)
    get_purchase_order_status,      # 발주 진행 현황 조회
    submit_purchase_order,          # 비동기 발주 실행 (Agent용)
    submit_purchase_order_sync,     # 동기 발주 실행 (UI 버튼용 등)
)

# C. 보고서 생성 도구 (Reporting)
# 용도: 엑셀 파일 생성, 월간 마감 리포트
from .report_tools import (
    # 월말 구매 마감 보고서 (refactored)
    generate_monthly_purchase_closing_report, analyze_monthly_closing, create_monthly_closing_file,
    # 발주 현황
    generate_po_status_report, analyze_po_status, create_po_status_file,
    # 공급업체 평가
    generate_supplier_evaluation_report, analyze_supplier_evaluation, create_supplier_evaluation_file,
)

# -------------------------------------------------------------------------
# 4. Agent 도구 레지스트리 (Tool Registry)
# -------------------------------------------------------------------------
# LangGraph의 'bind_tools'에 전달될 리스트입니다.
# LLM은 이 리스트에 포함된 함수들의 Docstring을 읽고 실행 여부를 결정합니다.

AGENT_TOOLS = [
    # --- 조회 및 분석 (Read) ---
    get_current_stock,
    get_product_detail,
    check_long_term_stock_criteria,
    get_stock_status,
    analyze_long_term_stock,
    get_purchase_order_status,

    # --- 계산 및 예측 (Calculation) ---
    calculate_gross_requirement,
    generate_purchase_prediction,

    # --- 실행 및 생성 (Action/Write) ---
    # analysis-only tools
    analyze_monthly_closing, analyze_po_status, analyze_supplier_evaluation,
    # create tools
    create_monthly_closing_file, create_po_status_file, create_supplier_evaluation_file,
    generate_monthly_purchase_closing_report,
    submit_purchase_order,
    generate_po_status_report,
    generate_supplier_evaluation_report,

]