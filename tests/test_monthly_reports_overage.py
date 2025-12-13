import pandas as pd
from monthly_reports import calculate_material_requirement


def test_monthly_material_requirement_applies_overage(tmp_path):
    # Prepare fake database
    db = {}
    prod_plan = pd.DataFrame([
        {'plan_id': 'P1', 'product_id': 'PROD1', 'start_date': '2025-11-01', 'standard_qty': 10}
    ])
    db['production_plan'] = prod_plan

    bom = pd.DataFrame([
        {'root_product_id': 'PROD1', 'component_product_id': 'C1', 'component_qty': 2}
    ])
    db['bom'] = bom

    overage_df = pd.DataFrame([
        {'product_id': 'C1', 'range_from': 0, 'range_to': 99999, 'overage_rate': 10, 'rounding_decimal': 0}
    ])
    db['overage_rule'] = overage_df

    result = calculate_material_requirement(db, 2025, 11)
    # requirement should be: plan_qty(10) * comp_qty(2) = 20, overage 10% => +2 => 22
    assert not result['total_requirement'].empty
    row = result['total_requirement'].loc[result['total_requirement']['product_id'] == 'C1'].iloc[0]
    assert int(row['requirement_qty']) == 22
