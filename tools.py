from langchain_core.tools import tool
import pandas as pd
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

    # BOM 조회
    bom = DB['bom'][DB['bom']['parent_product_id'] == target_product]
    if bom.empty:
        return f"{target_product}에 대한 BOM이 존재하지 않습니다."

    # 소요량 계산
    requirements = []
    for _, row in bom.iterrows():
        req_qty = row['component_quantity'] * plan_qty
        requirements.append({
            "component_product_id": row['component_product_id'],
            "gross_requirement": req_qty,
            "bom_level": row.get('bom_level', 1)  # default
        })

    return pd.DataFrame(requirements).to_markdown()


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
def mock_function():
    """
    새로 생성하겠습니다.
    :return:
    """
    pass
