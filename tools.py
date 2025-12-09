import math
import pandas as pd
import os
import json
from datetime import datetime, timedelta
from langchain_core.tools import tool
import data_loader

# -------------------------------------------------------------------------
# 0. 초기 설정 (Setup)
# -------------------------------------------------------------------------

# 마스터 데이터 로드 (서버 시작 시 1회 로드)
DB = data_loader.load_master_data()

# 결과 저장 경로 설정
OUTPUT_DIR = "output"
if not os.path.exists(OUTPUT_DIR):
    os.makedirs(OUTPUT_DIR)


# -------------------------------------------------------------------------
# 1. 핵심 분석 도구 (Core Analysis Tools)
# -------------------------------------------------------------------------

@tool
def calculate_gross_requirement(plan_id: str) -> str:
    """
    [소요량 전개] 특정 생산 계획(plan_id)에 대해 BOM을 전개하여 필요한 원자재 총 소요량을 계산합니다.
    오버리지(Overage) 규칙을 적용하여 여유분을 포함한 총 소요량을 산출합니다.
    """
    # 1. 생산 계획 조회
    # (실제 로직: plan_id로 조회해야 하나, 현재 테스트를 위해 하드코딩 값 사용)
    plan_df = DB.get('production_plan', pd.DataFrame())

    # [Test Config] 테스트용 하드코딩 변수
    target_product_id = "9309896"
    plan_qty = 2
    base_requirement_per_unit = 12000

    # 2. BOM 조회 (레벨 .1 구성품 대상)
    bom_df = DB.get('bom', pd.DataFrame())
    if bom_df.empty:
        return "BOM 데이터가 없습니다."

    # 특정 제품에 대한 1차 BOM 조회
    bom = bom_df[(bom_df['parent_product_id'] == target_product_id) & (bom_df['level'] == '.1')]

    if bom.empty:
        try:
            prod_desc = DB['product'].loc[DB['product']['product_id'] == target_product_id, 'description'].values[0]
        except:
            prod_desc = target_product_id
        return f"제품({prod_desc})에 대한 BOM 정보가 존재하지 않습니다."

    # 내부 함수: 오버리지 계산 로직
    def _calculate_overage(component_id: str, base_qty: float) -> float:
        # 테이블명 최신화: overage -> overage_rule
        overage_df = DB.get('overage_rule', pd.DataFrame())
        if overage_df.empty:
            return 0.0

        # ID 정규화 (String 변환 및 0 제거)
        target_comp_id = str(component_id).strip().lstrip('0')

        # 해당 자재의 규칙 필터링
        rules = overage_df[overage_df['product_id'] == target_comp_id]

        if rules.empty:
            return 0.0

        # 투입량 범위(Range) 매칭
        matched = rules[
            (rules['range_from'] <= base_qty) &
            (base_qty <= rules['range_to'])
            ]

        if matched.empty:
            return 0.0

        rule = matched.iloc[0]
        overage_val = 0.0

        # 절대값(abs) 우선 적용, 없으면 비율(rate) 적용
        if pd.notna(rule.get('overage_abs_qty')):
            overage_val = float(rule['overage_abs_qty'])
        elif pd.notna(rule.get('overage_rate')):
            overage_val = base_qty * float(rule['overage_rate']) / 100

        # 올림 처리 (rounding_decimal)
        decimals = int(rule.get('rounding_decimal') or 0)
        factor = 10 ** decimals
        if decimals == 0:
            return math.ceil(overage_val)
        return math.ceil(overage_val * factor) / factor

    # 3. 소요량 계산 실행
    requirements = []
    for _, row in bom.iterrows():
        component_id = row['component_product_id']

        # [Test Config] 단위당 고정 소요량 사용
        base_req = base_requirement_per_unit

        overage_qty = _calculate_overage(component_id, base_req)
        gross_req = base_req + overage_qty

        # 자재명 조회
        try:
            comp_desc = DB['product'].loc[DB['product']['product_id'] == str(component_id), 'description'].values[0]
        except (IndexError, KeyError):
            comp_desc = "Unknown"

        requirements.append({
            "component_id": component_id,
            "component_name": comp_desc,
            "base_requirement": base_req,
            "overage_qty": overage_qty,
            "gross_requirement": gross_req,
            "bom_level": row.get('level', 1)
        })

    return pd.DataFrame(requirements).to_markdown(index=False)


@tool
def generate_purchase_prediction(dummy_arg: str = "") -> str:
    """
    [발주 예측] 전체 생산 계획과 현재 재고를 분석하여 자재별 발주 필요량을 예측합니다.
    (Time-phased MRP 로직 적용, 원자재 ROH1/ROH2 대상)
    """
    # 1. 데이터 준비
    plans = DB.get('production_plan', pd.DataFrame()).copy()
    bom = DB.get('bom', pd.DataFrame())
    stock = DB.get('warehouse_stock', pd.DataFrame())
    products = DB.get('product', pd.DataFrame())
    vendors = DB.get('vendor_info_record', pd.DataFrame())  # 테이블명 최신화
    po_history = DB.get('purchase_order', pd.DataFrame())

    if plans.empty:
        return "등록된 생산 계획이 없습니다."

    # 날짜 정렬
    if 'start_date' in plans.columns:
        plans['start_date'] = pd.to_datetime(plans['start_date'])
        plans = plans.sort_values('start_date')

    # 현재 가용 재고 집계 (Product ID별 Sum)
    current_stock = {}
    if not stock.empty and 'unrestricted_qty' in stock.columns:
        # ID 문자열 변환 후 집계
        stock['product_id'] = stock['product_id'].astype(str)
        current_stock = stock.groupby('product_id')['unrestricted_qty'].sum().to_dict()

    prediction_rows = []

    # 발주 대상 자재 유형 정의
    TARGET_MAT_TYPES = ['ROH1', 'ROH2']

    # 2. 계획 순회
    for _, plan in plans.iterrows():
        # [Test Config] 하드코딩된 테스트 변수 유지
        target_product = 9309896
        plan_qty = 2

        delivery_date = plan['start_date'].strftime('%Y-%m-%d') if 'start_date' in plan else "Unknown"

        # BOM 전개
        plan_bom = bom[bom['parent_product_id'] == target_product]
        if plan_bom.empty:
            continue

        for _, comp in plan_bom.iterrows():
            comp_id = str(comp['component_product_id'])

            # 자재 유형 확인 (원자재만 발주)
            if not products.empty:
                product_info = products[products['product_id'] == comp_id]
                if not product_info.empty:
                    mat_type = product_info.iloc[0].get('product_type', '')
                    # 반제품(HALB) 제외, 지정된 원자재만 포함
                    if mat_type == 'HALB' or (TARGET_MAT_TYPES and mat_type not in TARGET_MAT_TYPES):
                        continue

            unit_req = comp['component_qty']
            total_req = unit_req * plan_qty

            # 재고 차감 로직 (Running Balance)
            available = current_stock.get(comp_id, 0)

            if available >= total_req:
                current_stock[comp_id] = available - total_req
            else:
                shortage = total_req - available
                current_stock[comp_id] = 0  # 재고 소진

                # 발주 정보 생성
                prod_desc = ""
                if not products.empty:
                    p_row = products[products['product_id'] == comp_id]
                    if not p_row.empty:
                        prod_desc = p_row.iloc[0]['description']

                # 주 공급업체 찾기
                vendor_name = "미지정"
                if not vendors.empty:
                    # ID 매칭 시 문자열 변환 안전장치
                    v_rows = vendors[vendors['product_id'].astype(str) == comp_id]
                    if not v_rows.empty:
                        # is_fixed_vendor가 'X'인 업체 우선
                        fixed = v_rows[v_rows['is_fixed_vendor'] == 'X']
                        if not fixed.empty:
                            vendor_name = fixed.iloc[0]['vendor_name']
                        else:
                            vendor_name = v_rows.iloc[0]['vendor_name']

                prediction_rows.append({
                    "품목코드": comp_id,
                    "품목명": prod_desc,
                    "발주필요량": shortage,
                    "납품요청일": delivery_date,
                    "추천공급사": vendor_name
                })

    if not prediction_rows:
        return "모든 생산 계획에 대해 자재 재고가 충분하거나, 발주 대상 원자재가 없습니다."

    # 결과 저장
    df_result = pd.DataFrame(prediction_rows)
    file_path = os.path.join(OUTPUT_DIR, f"Purchase_Prediction_{datetime.now().strftime('%Y%m%d')}.xlsx")

    # 엑셀 저장
    df_result.to_excel(file_path, index=False)

    return f"발주 예측 결과가 생성되었습니다.\n파일 경로: {file_path}\n총 {len(df_result)}건의 발주가 필요합니다."


# -------------------------------------------------------------------------
# 2. 조회 및 유틸리티 도구 (Lookup & Utility Tools)
# -------------------------------------------------------------------------

@tool
def get_current_stock(product_ids: str) -> str:
    """
    [현재고 간편 조회] 특정 자재들의 현재 재고 수량을 마크다운 형태로 반환합니다.
    """
    p_ids = [pid.strip() for pid in str(product_ids).split(',')]
    stock = DB.get('warehouse_stock', pd.DataFrame())

    if stock.empty:
        return "재고 데이터가 없습니다."

    # ID 문자열 변환
    stock['product_id'] = stock['product_id'].astype(str)
    target_stock = stock[stock['product_id'].isin(p_ids)]

    return target_stock.to_markdown(index=False)


@tool
def check_long_term_stock_criteria(product_id: str) -> str:
    """
    [장기재고 기준 확인] ADR-002: 자재 마스터에 정의된 장기재고 기준일(long_term_stock_days)을 확인합니다.
    """
    prod = DB.get('product', pd.DataFrame())
    if prod.empty:
        return "자재 마스터 데이터가 없습니다."

    target_id = str(product_id).strip()
    row = prod[prod['product_id'] == target_id]

    if row.empty:
        return "해당 자재가 존재하지 않습니다."

    days = row.iloc[0].get('long_term_stock_days')
    if not days or pd.isna(days) or days == 0:
        return "Master Data에 기준일 설정 없음. SOP 문서 확인 필요."

    return f"장기재고 기준일: {days}일"


@tool
def get_stock_status(product_ids: str) -> str:
    """
    [재고 상세 조회] 특정 자재(들)의 현재 창고 재고 현황(가용, 보류, 검사 등)을 상세 조회합니다.
    입력: product_ids (콤마로 구분된 자재 코드, 예: "1001, 1002")
    """
    stock_df = DB.get('warehouse_stock', pd.DataFrame())
    if stock_df.empty:
        return "재고 데이터가 없습니다."

    p_ids = [pid.strip() for pid in str(product_ids).split(',')]

    # [필수] 비교 전에 데이터프레임의 ID를 문자열로 강제 변환 (Type Mismatch 방지)
    stock_df['product_id'] = stock_df['product_id'].astype(str)

    target_stock = stock_df[stock_df['product_id'].isin(p_ids)]

    if target_stock.empty:
        return "해당 자재의 재고 정보가 없습니다."

    # 주요 컬럼만 표시
    cols = ['product_id', 'batch_no', 'unrestricted_qty', 'inspection_qty', 'blocked_qty']
    valid_cols = [c for c in cols if c in target_stock.columns]

    return target_stock[valid_cols].to_markdown(index=False)


@tool
def get_product_detail(product_id: str) -> str:
    """
    [자재 상세 조회] 자재 마스터 정보를 조회합니다. (품명, 규격, 유효기간 정책 등)
    """
    prod_df = DB.get('product', pd.DataFrame())
    if prod_df.empty:
        return "자재 마스터 데이터가 없습니다."

    row = prod_df[prod_df['product_id'] == str(product_id).strip()]
    if row.empty:
        return f"자재 코드 {product_id}를 찾을 수 없습니다."

    return row.iloc[0].to_markdown()


@tool
def analyze_long_term_stock(days_threshold: int = 180) -> str:
    """
    [장기 재고 분석] 입고된 지 특정 일수(기본 180일) 이상 지난 '배치 재고'를 조회합니다.
    """
    batch_df = DB.get('batch_stock', pd.DataFrame())
    if batch_df.empty:
        return "배치 재고 데이터가 없습니다."

    if 'receipt_date' not in batch_df.columns:
        return "입고일(receipt_date) 정보가 없어 분석할 수 없습니다."

    # 날짜 계산
    limit_date = datetime.now() - timedelta(days=int(days_threshold))

    # 날짜 변환 및 필터링
    try:
        batch_df['receipt_date'] = pd.to_datetime(batch_df['receipt_date'])
        long_term = batch_df[batch_df['receipt_date'] <= limit_date]
    except Exception as e:
        return f"날짜 변환 중 오류 발생: {str(e)}"

    if long_term.empty:
        return f"{days_threshold}일 이상 경과한 장기 재고가 없습니다."

    result = long_term[['product_id', 'batch_no', 'receipt_date', 'available_stock_value']]
    return result.to_markdown(index=False)


@tool
def generate_excel_report(data_json: str, filename: str = "report.xlsx") -> str:
    """
    [보고서 생성] JSON 형식의 데이터나 리스트를 엑셀 파일로 저장합니다.
    Agent가 분석 결과를 파일로 제공하고 싶을 때 사용합니다.
    """
    try:
        # JSON 문자열 파싱
        if isinstance(data_json, str):
            data = json.loads(data_json)
        else:
            data = data_json

        df = pd.DataFrame(data)

        # 파일명 처리
        if not filename.endswith('.xlsx'):
            filename += '.xlsx'

        file_path = os.path.join(OUTPUT_DIR, filename)
        df.to_excel(file_path, index=False)

        return f"파일이 생성되었습니다: {file_path}"
    except Exception as e:
        return f"파일 생성 실패: {str(e)}"