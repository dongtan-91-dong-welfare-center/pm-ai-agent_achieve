"""
설명: 재고 조회, 자재 마스터 확인, 장기 재고 분석 등 자재/재고 관련 핵심 로직 구현

[Role & Responsibility]
- Data Consistency: 모든 조회는 메모리에 로드된 `shared.DB`를 참조합니다.
"""

import pandas as pd
from langchain_core.tools import tool
from .utils import df_to_markdown
from .shared import DB


# -------------------------------------------------------------------------
# Internal Helper Functions (내부 전용)
# -------------------------------------------------------------------------

def _normalize_id(val) -> str:
    """
    [ID 정규화] ERP 데이터 특성상 발생하는 포맷 불일치를 해결합니다.
    예: '000100' -> '100', 100.0 -> '100', ' 100 ' -> '100'
    """
    if pd.isna(val) or val == "":
        return ""

    s_val = str(val).strip()

    # 소수점 제거 (엑셀 로드 시 숫자가 float로 읽히는 경우 방지)
    if s_val.endswith(".0"):
        s_val = s_val[:-2]

    # 앞쪽 0 제거 (SAP 자재코드 표준)
    return s_val.lstrip('0')


# -------------------------------------------------------------------------
# AI Agent Tools
# -------------------------------------------------------------------------

@tool
def get_current_stock(product_ids: str) -> str:
    """
    [현재고 간편 조회]
    특정 자재(Product ID)들의 현재 창고 재고(Warehouse Stock) 수량을 조회합니다.
    입력은 콤마(,)로 구분된 문자열입니다.
    """
    # 1. 입력 ID 파싱 및 정규화
    p_ids = [_normalize_id(pid) for pid in str(product_ids).split(',') if pid.strip()]

    stock = DB.get('warehouse_stock', pd.DataFrame())

    if stock.empty:
        return "시스템에 재고 데이터가 없습니다."

    # 2. DB 데이터 임시 정규화 (검색을 위해)
    # 원본 데이터프레임을 건드리지 않기 위해 copy() 사용
    stock_view = stock.copy()
    stock_view['__norm_id'] = stock_view['product_id'].apply(_normalize_id)

    # 3. 조회 및 필터링
    target_stock = stock_view[stock_view['__norm_id'].isin(p_ids)]

    if target_stock.empty:
        return f"요청한 자재({product_ids})의 재고 정보가 없습니다."

    # 4. 결과 반환 (임시 컬럼 제외)
    cols = [c for c in target_stock.columns if c != '__norm_id']
    return df_to_markdown(target_stock[cols])


@tool
def get_product_detail(product_id: str) -> str:
    """
    [자재 상세 조회]
    자재 마스터(Product Master) 정보를 조회하여 품명, 기본 단위, 자재 유형 등을 확인합니다.
    """
    prod_df = DB.get('product', pd.DataFrame())
    if prod_df.empty:
        return "자재 마스터 데이터가 없습니다."

    target_id = _normalize_id(product_id)

    # 마스터 데이터에서 검색 (apply 사용 시 성능 이슈가 있을 수 있으나, 마스터 데이터 크기가 작다고 가정)
    # 대량 데이터일 경우 별도의 매핑 테이블(Dict) 생성을 권장
    mask = prod_df['product_id'].apply(_normalize_id) == target_id
    row = prod_df[mask]

    if row.empty:
        return f"자재 코드 '{product_id}' (식별키: {target_id})를 마스터에서 찾을 수 없습니다."

    # Series를 마크다운 표 형태(Transpose)로 변환하여 가독성 확보
    try:
        # DataFrame 형태로 변환 후 마크다운
        return df_to_markdown(row)
    except Exception:
        return row.iloc[0].to_string()


@tool
def check_long_term_stock_criteria(product_id: str) -> str:
    """
    [장기재고 기준 확인]
    Adr-002: 자재별로 설정된 장기재고 판단 기준일(Days)을 조회합니다.
    """
    prod_df = DB.get('product', pd.DataFrame())
    if prod_df.empty:
        return "자재 마스터 데이터가 없습니다."

    target_id = _normalize_id(product_id)
    mask = prod_df['product_id'].apply(_normalize_id) == target_id
    row = prod_df[mask]

    if row.empty:
        return f"자재 '{product_id}'가 존재하지 않습니다."

    # 컬럼 확인 및 값 추출
    if 'long_term_stock_days' in row.columns:
        days = row.iloc[0]['long_term_stock_days']
        if pd.notna(days) and days != 0:
            return f"자재 '{product_id}'의 장기재고 기준일: {int(days)}일"

    return f"자재 '{product_id}'는 기준일이 설정되지 않았습니다 (기본값 180일 적용 필요 또는 SOP 확인)."


@tool
def get_stock_status(product_ids: str) -> str:
    """
    [재고 상태 상세 조회]
    가용(Unrestricted), 품질검사(Inspection), 보류(Blocked) 등 재고의 상태별 수량을 조회합니다.
    """
    stock_df = DB.get('warehouse_stock', pd.DataFrame())
    if stock_df.empty:
        return "재고 데이터가 없습니다."

    p_ids = [_normalize_id(pid) for pid in str(product_ids).split(',') if pid.strip()]

    stock_view = stock_df.copy()
    stock_view['__norm_id'] = stock_view['product_id'].apply(_normalize_id)

    target_stock = stock_view[stock_view['__norm_id'].isin(p_ids)]

    if target_stock.empty:
        return "해당 자재의 재고 정보가 없습니다."

    # 주요 상태 컬럼만 선별하여 표시
    cols = ['product_id', 'batch_no', 'unrestricted_qty', 'inspection_qty', 'blocked_qty']
    valid_cols = [c for c in cols if c in target_stock.columns]

    # 만약 유효한 컬럼이 너무 적으면 전체 반환
    if len(valid_cols) < 2:
        final_cols = [c for c in target_stock.columns if c != '__norm_id']
    else:
        final_cols = valid_cols

    return df_to_markdown(target_stock[final_cols])


@tool
def analyze_long_term_stock(days_threshold: int = 180) -> str:
    """
    [장기 재고 분석]
    배치(Batch) 재고 데이터를 기반으로, 입고일(Receipt Date)로부터
    특정 일수(days_threshold) 이상 경과한 재고 리스트를 추출합니다.
    """
    batch_df = DB.get('batch_stock', pd.DataFrame())
    if batch_df.empty:
        return "배치 재고 데이터가 없습니다."

    if 'receipt_date' not in batch_df.columns:
        return "데이터에 '입고일(receipt_date)' 컬럼이 없어 장기 재고를 분석할 수 없습니다."

    # 기준일 계산 (오늘 - 임계치)
    limit_date = pd.Timestamp.now() - pd.Timedelta(days=int(days_threshold))

    try:
        # 날짜 변환 (에러 발생 시 NaT 처리)
        batch_view = batch_df.copy()
        batch_view['receipt_date'] = pd.to_datetime(batch_view['receipt_date'], errors='coerce')

        # 날짜 데이터가 유효한 것만 필터링
        batch_view = batch_view.dropna(subset=['receipt_date'])

        # 장기 재고 필터링 (입고일 <= 제한일)
        long_term = batch_view[batch_view['receipt_date'] <= limit_date]

        if long_term.empty:
            return f"입고된 지 {days_threshold}일 이상 경과한 장기 재고가 없습니다. (관리 상태 양호)"

        # 결과 컬럼 선별
        result_cols = ['product_id', 'batch_no', 'receipt_date', 'available_stock_value']
        valid_cols = [c for c in result_cols if c in long_term.columns]

        # 상위 20개만 보여주거나 전체 리턴 (여기서는 전체 리턴하되 LLM이 요약하도록 함)
        return df_to_markdown(long_term[valid_cols])

    except Exception as e:
        return f"장기 재고 분석 중 날짜 변환 오류가 발생했습니다: {str(e)}"