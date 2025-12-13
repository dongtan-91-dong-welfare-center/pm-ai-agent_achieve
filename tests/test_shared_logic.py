import pandas as pd
from tools.shared_logic import calculate_overage, calculate_component_gross_requirement


def test_calculate_overage_rate():
    db = {}
    # create overage rule row
    overage_df = pd.DataFrame([
        {
            'product_id': '1001',
            'range_from': 0,
            'range_to': 100,
            'overage_rate': 10,
            'rounding_decimal': 0
        }
    ])
    db['overage_rule'] = overage_df

    overage = calculate_overage(db, '1001', 50)
    assert overage == 5


def test_calculate_component_gross_requirement():
    db = {}
    overage_df = pd.DataFrame([
        {
            'product_id': '2002',
            'range_from': 0,
            'range_to': 99999,
            'overage_abs_qty': 2,
            'rounding_decimal': 0
        }
    ])
    db['overage_rule'] = overage_df

    gross = calculate_component_gross_requirement(db, '2002', 10)
    # base 10 + abs 2
    assert gross == 12
