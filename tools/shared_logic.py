"""
설명: 도구(Tool) 간 공유되는 순수 비즈니스 로직(Pure Business Logic) 라이브러리

[Key Logic]
1. Overage Lookup: 투입량(Base Qty) 구간에 맞는 Loss 규칙을 찾습니다.
2. Calculation Priority: 절대값(Fixed Loss) > 비율(Rate Loss) 순으로 적용합니다.
3. Safe Rounding: 자재 부족을 방지하기 위해 반드시 올림(Ceiling) 처리합니다.
"""

import math
import pandas as pd


def calculate_overage(db: dict, component_id: str, base_qty: float) -> float:
    """
    [핵심 로직] 특정 자재(Component)의 투입량(Base Qty)에 따른 추가 소요량(Overage)을 계산합니다.

    Args:
        db (dict): 'overage_rule' DataFrame을 포함한 전역 데이터 저장소
        component_id (str): 자재 코드 (Product ID)
        base_qty (float): 기준 소요량 (생산량 * BOM 정미 수량)

    Returns:
        float: 계산된 오버리지 수량 (Note: 총 소요량이 아닌, '추가분'만 반환합니다)

    Logic Details:
        1. ID Normalization: 입력된 ID의 앞쪽 '0'을 제거하여 매칭합니다 (예: '00100' -> '100').
        2. Range Check: `range_from` <= 투입량 <= `range_to` 조건을 만족하는 규칙을 찾습니다.
        3. Priority: `overage_abs_qty`(절대값)이 있으면 이를 사용하고, 없으면 `overage_rate`(비율)를 사용합니다.
        4. Rounding: `rounding_decimal` 자릿수 기준으로 올림(Ceiling) 처리하여 재고 부족을 방지합니다.
    """
    # 1. 데이터 유효성 검사
    overage_df = db.get('overage_rule', pd.DataFrame())
    if overage_df.empty or base_qty is None:
        return 0.0

    # 2. ID 정규화 (Normalization)
    # [주의] 마스터 데이터의 ID가 '000100' 형태라면, 이 로직('100')으로 인해 매칭 실패할 수 있음. 데이터 표준화 필요.
    target_comp_id = str(component_id).strip().lstrip('0')

    # 해당 자재의 규칙 필터링
    rules = overage_df[overage_df['product_id'] == target_comp_id]
    if rules.empty:
        return 0.0

    # 3. 투입량 구간(Range) 매칭
    matched = rules[(rules['range_from'] <= base_qty) & (base_qty <= rules['range_to'])]
    if matched.empty:
        return 0.0

    # 첫 번째 매칭된 규칙 적용 (중복 구간이 없다고 가정)
    rule = matched.iloc[0]
    overage_val = 0.0

    # 4. 계산 우선순위 적용 (절대값 > 비율)
    if pd.notna(rule.get('overage_abs_qty')):
        # 절대값 적용 (예: 무조건 10개 Loss)
        overage_val = float(rule['overage_abs_qty'])
    elif pd.notna(rule.get('overage_rate')):
        # 비율 적용 (예: 투입량의 5% Loss)
        overage_val = base_qty * float(rule['overage_rate']) / 100

    # 5. 올림(Ceiling) 처리
    # 소수점 처리는 자재 관리에서 매우 중요함 (1.1개 필요 시 2개 불출)
    decimals = int(rule.get('rounding_decimal') or 0)
    factor = 10 ** decimals

    if decimals == 0:
        return math.ceil(overage_val)

    # 지정된 소수점 자릿수까지 남기고 올림 처리
    return math.ceil(overage_val * factor) / factor


def calculate_component_gross_requirement(db: dict, component_id: str, base_qty: float) -> float:
    """
    [Wrapper] 기준 소요량에 오버리지를 합산하여 최종 총 소요량(Gross Requirement)을 반환합니다.

    Formula:
        Gross Requirement = Base Quantity + Overage Quantity

    Args:
        db (dict): 데이터 저장소
        component_id (str): 자재 코드
        base_qty (float): 기준 소요량

    Returns:
        float: 최종 필요 수량
    """
    overage = calculate_overage(db, component_id, base_qty)
    return base_qty + overage