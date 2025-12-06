from .core import save_uploaded_file_by_type, load_master_data, FILE_PROCESSORS, get_database_schema_string
from .config import TABLE_SCHEMA, DATA_DIR

import pandas as pd
from io import StringIO


def load_mock_data_for_test():
    """테스트용 샘플 데이터 로드 (Schema V2 적용)"""

    # 1. Product (자재 마스터)
    csv_product = """product_id,product_type,plant_code,base_unit,plant_status,prod_storage_loc,ep_storage_loc,remaining_shelf_life,total_shelf_life,inspection_setting,product_group,edition_no,is_attachment
M-1001,ROH1,1220,EA,Z1,1001,2001,365,730,Y,PG-01,1,N
M-1002,ROH1,1220,KG,Z1,1001,2001,180,360,N,PG-02,2,N
P-2001,HALB,1220,L,Z1,1002,2002,90,180,Y,PG-03,1,N
P-2002,HALB,1220,L,Z1,1002,2002,60,120,Y,PG-03,1,N
F-3001,FERT,1220,BOX,Z1,1003,2003,30,365,Y,PG-04,3,Y"""

    # 2. Material Ledger (자재수불부 - 단가 정보 포함)
    csv_material_ledger = """product_id,currency,standard_price,opening_qty,opening_amount,receipt_purchase_qty,receipt_purchase_price,receipt_purchase_price_diff,production_receipt_qty,production_receipt_price,production_receipt_price_diff,other_receipt_qty,other_receipt_price,other_receipt_price_diff,price_diff,total_receipt_qty,total_receipt_amount,total_receipt_price_diff,production_issue_qty,production_issue_price,production_issue_price_diff,cost_center_issue_qty,cost_center_issue_price,cost_center_issue_price_diff,other_issue_qty,other_issue_price,other_issue_price_diff,total_issue_qty,total_issue_amount,total_issue_price_diff,total_price_diff,closing_qty,closing_amount
M-1001,KRW,50000,100,5000000,50,2500000,0,0,0,0,0,0,0,0,50,2500000,0,20,1000000,0,0,0,0,0,0,0,20,1000000,0,0,130,6500000
M-1002,KRW,1500,1000,1500000,200,300000,0,0,0,0,0,0,0,0,200,300000,0,500,750000,0,10,15000,0,0,0,0,510,765000,0,0,690,1035000
P-2001,KRW,25000,50,1250000,0,0,0,30,750000,0,0,0,0,0,30,750000,0,10,250000,0,0,0,0,0,0,0,10,250000,0,0,70,1750000
P-2002,KRW,12000,0,0,0,0,0,100,1200000,0,0,0,0,0,100,1200000,0,0,0,0,0,0,0,0,0,0,0,0,0,0,100,1200000
F-3001,KRW,85000,10,850000,0,0,0,50,4250000,0,0,0,0,0,50,4250000,0,30,2550000,0,0,0,0,5,425000,0,35,2975000,0,0,25,2125000"""

    # 3. Batch Stock (배치 재고 - 가치 포함)
    csv_batch_stock = """product_id,manufacture_date,expiration_date,batch_no,available_qty,quality_inspection_qty,blocked_stock,available_stock_value,quality_inspection_stock_value,blocked_stock_value,receipt_date
M-1001,2024-01-01,2026-01-01,BATCH-001,100,0,0,5000000,0,0,2024-01-05
M-1001,2024-02-01,2026-02-01,BATCH-002,30,0,0,1500000,0,0,2024-02-05
M-1002,2024-03-01,2025-03-01,BATCH-101,690,10,0,1035000,15000,0,2024-03-10
P-2001,2024-04-01,2024-10-01,BATCH-201,70,0,5,1750000,0,125000,2024-04-15
P-2002,2024-04-10,2024-08-10,BATCH-202,100,0,0,1200000,0,0,2024-04-20
F-3001,2024-05-01,2025-05-01,BATCH-301,25,0,0,2125000,0,0,2024-05-05"""

    # CSV 읽기
    df_product = pd.read_csv(StringIO(csv_product))
    df_ledger = pd.read_csv(StringIO(csv_material_ledger))
    df_batch = pd.read_csv(StringIO(csv_batch_stock))

    # 데이터 타입 보정 (Data Cleaning)
    # 금액/수량 컬럼이 문자열로 인식될 경우를 대비해 콤마 제거 후 숫자 변환
    numeric_cols = ['standard_price', 'opening_amount', 'available_stock_value', 'available_qty']

    for df in [df_ledger, df_batch]:
        for col in df.columns:
            if col in numeric_cols:
                # 콤마 제거 및 숫자로 변환 (에러 시 NaN 처리)
                if df[col].dtype == 'object':
                    df[col] = df[col].astype(str).str.replace(',', '').apply(pd.to_numeric, errors='coerce')

    return {
        "product": df_product,
        "material_ledger": df_ledger,
        "batch_stock": df_batch
    }