import os
import pandas as pd

DATA_DIR = "data"

# 파일이 존재하는지 테스트
def test_files_exist():
    required_files = [
        "product.csv",
        "bom.csv",
        "inventory.csv",
        "plan.csv",
        "purchase_order.csv",
        "purchase_history.csv"
    ]
    for f in required_files:
        assert os.path.exists(os.path.join(DATA_DIR, f)), f"{f} 파일이 존재하지 않습니다."

# bom에 포함된 자재가 자재 테이블에 있는지 확인
def test_bom_parent_child_references():
    df_product = pd.read_csv(os.path.join(DATA_DIR, "product.csv"))
    df_bom = pd.read_csv(os.path.join(DATA_DIR, "bom.csv"))

    product_ids = df_product["product_id"].unique()
    for _, row in df_bom.iterrows():
        assert row["parent_product_id"] in product_ids, f"{row['parent_product_id']} 제품이 product.csv에 없습니다."
        assert row["component_product_id"] in product_ids, f"{row['component_product_id']} 자재가 product.csv에 없습니다."

# 발주 자재가 자재 테이블에 있는지 확인
def test_purchase_order_product_reference():
    df_product = pd.read_csv(os.path.join(DATA_DIR, "product.csv"))
    df_po = pd.read_csv(os.path.join(DATA_DIR, "purchase_order.csv"))
    product_ids = set(df_product["product_id"])

    for _, row in df_po.iterrows():
        assert row["product_id"] in product_ids, f"발주 자재 {row['product_id']} 는 product.csv에 없습니다."

# 발주 없는 구매가 있는지 확인
def test_purchase_history_links_order():
    df_po = pd.read_csv(os.path.join(DATA_DIR, "purchase_order.csv"))
    df_history = pd.read_csv(os.path.join(DATA_DIR, "purchase_history.csv"))

    po_ids = set(df_po['po_id'])

    for _, row in df_history.iterrows():
        assert row["po_id"] in po_ids, f"{row['po_id']} 는 purchase_order.csv에 존재하지 않습니다."