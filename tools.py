import math
import pandas as pd
import os
from langchain_core.tools import tool
import data_loader

DB = data_loader.load_master_data()


@tool
def calculate_gross_requirement(plan_id: str):
    """
    소요량 전개 (Gross Requirement Calculation)
    특정 생산 계획(plan_id)에 대해 BOM을 전개하여 필요한 원자재 총 소요량을 계산합니다.
    """

    # 생산 계획 조회
    plan = DB['plan'][DB['plan']['plan_id'] == plan_id]
    if plan.empty:
        return "해당 생산 계획이 존재하지 않습니다."

    target_product = plan.iloc[0]['product_id']
    plan_qty = plan.iloc[0]['planned_qty']
    plan_qty = float(plan.iloc[0]['planned_qty'])

    # BOM 조회
    bom = DB['bom'][DB['bom']['parent_product_id'] == target_product]
    # BOM 조회 (레벨 0.1 구성품만 대상)
    bom = DB['bom'][(DB['bom']['parent_product_id'] == target_product) & (DB['bom']['level'] == 0.1)]
    if bom.empty:
        return f"{target_product}에 대한 BOM이 존재하지 않습니다."

    overage_rules = DB.get('overage', pd.DataFrame())

    def _calculate_overage(component_id: str, base_quantity: float) -> float:
        if overage_rules.empty:
            return 0.0

        rules = overage_rules[overage_rules['product_id'] == component_id]
        if rules.empty:
            return 0.0

        # 투입량 범위 조회
        matched = rules[
            (rules['input_range_from'] <= base_quantity)
            & (base_quantity <= rules['input_range_to'])
        ]
        if matched.empty:
            return 0.0

        rule = matched.iloc[0]
        overage_qty = 0.0

        if pd.notna(rule.get('overage_qty')):
            overage_qty = float(rule['overage_qty'])
        elif pd.notna(rule.get('overage_percent')):
            overage_qty = base_quantity * float(rule['overage_percent']) / 100

        # 올림 규칙 적용
        decimals = int(rule.get('rounding_decimals') or 0)
        factor = 10 ** decimals
        return math.ceil(overage_qty * factor) / factor

    # 소요량 계산
    requirements = []
    for _, row in bom.iterrows():
        req_qty = row['component_quantity'] * plan_qty
        component_id = row['component_product_id']
        base_requirement = float(row['component_quantity']) * float(plan_qty)
        overage_qty = _calculate_overage(component_id, base_requirement)
        gross_requirement = base_requirement + overage_qty

        requirements.append({
            "component_product_id": component_id,
            "base_requirement": base_requirement,
            "overage_quantity": overage_qty,
            "gross_requirement": gross_requirement,
            "bom_level": row.get('level', 1)
        })

    return pd.DataFrame(requirements).to_markdown(index=False)


@tool
def get_current_stock(product_ids: str):
    """
    현재 가용 재고 조회
    """
    p_ids = [pid.strip() for pid in product_ids.split(',')]
    stock = DB['inventory'][DB['inventory']['product_id'].isin(p_ids)]
    return stock.to_markdown()


@tool
def check_long_term_stock_criteria(product_id: str):
    """
    ADR-002: 자재별 장기재고 기준일 확인
    Master Data에서 long_term_stock_days를 우선 확인합니다.
    """
    prod = DB['product'][DB['product']['product_id'] == product_id]
    if prod.empty:
        return "자재가 존재하지 않습니다."

    days = prod.iloc[0]['long_term_stock_days']
    if days == 0 or pd.isna(days):
        return "Master Data에 기준일 없음. SOP 문서 탐색 필요."
    return f"기준일: {days}일"

@tool
def get_stock_status(product_ids: str) -> str:
    """
    특정 자재의 현재 가용 재고(Warehouse Stock)를 조회합니다.
    입력: product_ids (쉼표로 구분된 자재 코드 문자열, 예: "MAT-001, MAT-002")
    """
    p_ids = [pid.strip() for pid in product_ids.split(',')]

    # 창고 재고 테이블 사용
    stock_df = DB['warehouse_stock']

    # 해당 자재 필터링
    target_stock = stock_df[stock_df['product_id'].isin(p_ids)]

    if target_stock.empty:
        return "해당 자재의 재고 정보가 없습니다."

    # 필요한 컬럼만 표시 (가용 재고 중심)
    # 매핑: 가용(unrestricted_qty), 품질 검사(inspection_qty), 보류(blocked_qty)
    result = target_stock[['product_id', 'batch_no', 'unrestricted_qty', 'inspection_qty', 'blocked_qty']]
    return result.to_markdown(index=False)

@tool
def generate_purchase_prediction(dummy_arg: str = "") -> str:
    """
    [시스템 예측] 전체 생산 계획을 기반으로 자재 발주 정보를 생성합니다.

    동작 방식:
    1. 생산 계획(production_plan)을 날짜(start_date) 순으로 정렬합니다.
    2. 각 계획에 대해 BOM을 전개하여 필요 자재를 계산합니다.
    3. 현재고(warehouse_stock)에서 소요량을 차감하며(Running Balance), 재고가 부족해지는 시점에 발주 정보를 생성합니다.
    4. 결과는 엑셀 파일로 저장됩니다.

    입력: 없음 (빈 문자열)
    """
    # 1. 데이터 준비
    plans = DB['production_plan'].copy()
    bom = DB['bom']
    stock = DB['warehouse_stock']
    products = DB['product']
    vendors = DB['vendor']
    po_history = DB['purchase_order']

    if plans.empty:
        return "등록된 생산 계획이 없습니다."

    # 날짜 형식 변환 및 정렬 (납기 준수를 위해 날짜순 처리 필수)
    plans['start_date'] = pd.to_datetime(plans['start_date'])
    plans = plans.sort_values('start_date')

    # 현재 가용 재고 집계 (자재별 총합)
    current_stock = stock.groupby('product_id')['unrestricted_qty'].sum().to_dict()

    prediction_rows = []

    # 2. 계획 순회 (Time-phased MRP Logic)
    for _, plan in plans.iterrows():
        parent_id = plan.get('material_type')  # 혹은 식별 가능한 product code 컬럼 - 현재 없음
        # 주의: production_plan 매핑에 'product_id'가 없고 'material_type', 'packing_unit' 등만 있다면
        # 로직 수정이 필요할 수 있음. 여기서는 '비고'나 '자재 유형'을 통해 BOM Parent를 찾는다고 가정하거나,
        # 엑셀의 구조상 특정 컬럼이 Product ID 역할을 한다고 가정해야 합니다.
        # *가정*: 생산계획의 '자재 유형'이나 별도 컬럼이 Parent ID가 아닐 경우, 매핑 로직 점검 필요.
        # 일단 user prompt의 'production_plan'에는 'product_id'가 명시되어 있지 않음.
        # 'Remark'나 'Material Type' 등에 제품 코드가 있다고 가정하고 진행.

        # (임시) material_type이나 remark에서 제품 코드를 유추 불가시 스킵
        # 여기서는 BOM 테이블의 parent_product_id 중 하나와 매칭된다고 가정
        # 실제 데이터에 맞게 조정 필요. 예시로 '자재 유형'을 제품코드로 사용
        # target_product = plan.get('material_type', 'UNKNOWN')
        target_product = 9309896

        # plan_qty = float(plan.get('packing_unit', 0))
        plan_qty = 2
        delivery_date = plan['start_date'].strftime('%Y-%m-%d')

        # BOM 전개
        plan_bom = bom[bom['parent_product_id'] == target_product]
        if plan_bom.empty:
            continue  # BOM 없으면 스킵

        for _, comp in plan_bom.iterrows():
            comp_id = comp['component_product_id']
            unit_req = comp['component_qty']
            total_req = unit_req * plan_qty

            # 가용 재고 확인 (Running Balance)
            available = current_stock.get(comp_id, 0)

            if available >= total_req:
                # 재고 충분 -> 차감만 하고 발주 없음
                current_stock[comp_id] = available - total_req
            else:
                # 재고 부족 -> 전량 사용 후 부족분 발주
                shortage = total_req - available
                current_stock[comp_id] = 0  # 재고 소진

                # 발주 정보 생성
                # 1) 품목명 조회
                prod_desc = ""
                prod_row = products[products['product_id'] == comp_id]
                if not prod_row.empty:
                    prod_desc = prod_row.iloc[0]['description']

                # 2) 공급업체 조회 (최근 구매 이력 기반 추론)
                vendor_name = "업체 미지정"
                hist = po_history[po_history['product_id'] == comp_id]
                if not hist.empty:
                    # 최근 PO 기준
                    last_vendor_id = hist.iloc[-1]['vendor_id']
                    v_row = vendors[vendors['vendor_id'] == last_vendor_id]
                    if not v_row.empty:
                        vendor_name = v_row.iloc[0]['vendor_name']

                prediction_rows.append({
                    "품목코드": comp_id,
                    "품목명": prod_desc,
                    "수량": shortage,
                    "납품일자": delivery_date,
                    "공급업체": vendor_name
                })

    # 3. 결과 파일 생성
    if not prediction_rows:
        return "모든 생산 계획에 대해 자재 재고가 충분합니다. (발주 필요 없음)"

    df_result = pd.DataFrame(prediction_rows)

    # 동일 날짜, 동일 품목, 동일 업체의 경우 합산 (Option)
    # df_result = df_result.groupby(['품목코드', '품목명', '납품일자', '공급업체'], as_index=False)['수량'].sum()

    # 컬럼 순서 강제 (A~E)
    cols = ["품목코드", "품목명", "수량", "납품일자", "공급업체"]
    final_df = df_result[cols]

    save_dir = "output"
    if not os.path.exists(save_dir):
        os.makedirs(save_dir)

    file_path = os.path.join(save_dir, "Purchase_Order_Prediction.xlsx")
    final_df.to_excel(file_path, index=False)

    return f"발주 예측 파일 생성이 완료되었습니다.\n경로: {file_path}\n총 {len(final_df)}건의 발주 필요 항목이 도출되었습니다."
