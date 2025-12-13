"""
설명: 데이터 로딩을 위한 스키마 정의 및 파일 매핑 설정

[Role & Responsibility]
- Schema Definition: 각 데이터 테이블의 컬럼 순서와 이름을 정의합니다.
- File Mapping: 내부 변수명(Key)과 실제 파일명(Value)을 매핑하여, 파일명이 바뀌어도 코드 수정 없이 설정만 변경하면 되도록 합니다.
"""

import os

# 데이터 저장 경로 (프로젝트 루트 기준)
DATA_DIR = "data"

# 내부 Key와 실제 파일명 매핑 (대소문자 이슈 해결)
# 코드는 왼쪽의 Key를 사용하고, 로더는 오른쪽의 파일명을 찾습니다.
FILE_NAME_MAP = {
    "product": "product.csv",
    "bom": "bom.csv",
    "vendor_info_record": "vendor_info_record.csv",
    "overage_rule": "overage_rule.csv",
    "production_plan": "production_plan.csv",
    "purchase_order": "purchase_order.csv",
    "purchase_transaction_history": "purchase_transaction_history.csv",
    "good_receipt": "good_receipt.csv",
    "material_ledger": "material_ledger.csv",
    "warehouse_stock": "warehouse_stock.csv",
    "batch_stock": "batch_stock.csv",
    "prod_plan_code_map": "prod_plan_code_map.csv",
    "non_conformance": "non_conformance.csv"
}

# 데이터 스키마 정의 (LLM에게 제공되는 정보이자, 데이터 검증 기준)
TABLE_SCHEMA = {

    # 1. 자재 마스터 (Product)
    "product": [
        "product_id",
        "product_type",
        "plant_code",
        "description",
        "base_unit",
        "plant_status",
        "prod_storage_loc",
        "ep_storage_loc",
        "remaining_shelf_life",
        "total_shelf_life",
        "inspection_setting",
        "product_group",
        "product_group_name",
        "edition_no",
        "is_attachment",
    ],

    # 2. 자재명세서 (BOM)
    "bom": [
        "root_product_id",
        "standard_qty",
        "level",
        "parent_product_id",
        "component_product_id",
        "component_qty",
    ],

    # 3. 구매정보레코드 (Vendor Info Record)
    "vendor_info_record": [
        "is_fixed_vendor",
        "vendor_id",
        "vendor_name",
        "product_id",
        "valid_from",
        "valid_to",
        "manufacturer_id",
        "manufacturer_name",
        "purchasing_group",
        "purchasing_group_name",
        "order_unit",
        "unit_price",
        "currency",
        "price_unit",
    ],

    # 4. 오버리지 기준 (Overage Rule)
    "overage_rule": [
        "product_id",
        "packing_code",
        "range_from",
        "range_to",
        "overage_abs_qty",
        "overage_rate",
        "rounding_decimal",
    ],

    # 5. 생산 계획 (Production Plan)
    "production_plan": [
        "serial_no",
        "material_type",
        "country",
        "packing_unit",
        "remark",
        "start_date",
        "end_date",
        "batch_no",
    ],

    # 6. 구매 오더 (Purchase Order - Header/Item)
    "purchase_order": [
        "po_id",
        "po_item_no",
        "vendor_id",
        "product_id",
        "po_date",
        "schedule_qty",
        "received_qty",
        "delivery_date",
    ],

    # 7. 구매/재무 상세 내역 (Purchase Transaction History)
    "purchase_transaction_history": [
        "po_id",
        "po_item_no",
        "receipt_date",
        "movement_type",
        "product_id",
        "order_qty",
        "info_rec_date",
        "old_price",
        "new_price",
        "master_price",
        "master_price_currency",
        "order_price",
        "order_currency",
        "price_unit",
        "received_quantity",
        "received_value_local_currency",
        "printing_plate_cost",
        "copper_plate_cost",
        "total_received_value_local_currency",
        "total_received_value_krw",
        "vendor_id",
    ],

    # 8. 입고 이력 (Good Receipt Log)
    "good_receipt": [
        "work_datetime",
        "po_id",
        "po_item_no",
        "product_id",
        "batch_no",
        "manufacturing_no",
        "manufacturing_date",
        "expiration_date",
        "receipt_qty",
        "inspection_lot_no",
    ],

    # 9. 자재수불부 (Material Ledger)
    "material_ledger": [
        "product_id",
        "currency",
        "standard_price",
        "opening_qty",
        "opening_amount",
        "receipt_purchase_qty",
        "receipt_purchase_price",
        "receipt_purchase_price_diff",
        "production_receipt_qty",
        "production_receipt_price",
        "production_receipt_price_diff",
        "other_receipt_qty",
        "other_receipt_price",
        "other_receipt_price_diff",
        "price_diff",
        "total_receipt_qty",
        "total_receipt_amount",
        "total_receipt_price_diff",
        "production_issue_qty",
        "production_issue_price",
        "production_issue_price_diff",
        "cost_center_issue_qty",
        "cost_center_issue_price",
        "cost_center_issue_price_diff",
        "cost_center_issue_adjustment",
        "other_issue_qty",
        "other_issue_price",
        "other_issue_price_diff",
        "total_issue_qty",
        "total_issue_amount",
        "total_issue_price_diff",
        "total_price_diff",
        "closing_qty",
        "closing_amount",
    ],

    # 10. 창고 재고 (Warehouse Stock)
    "warehouse_stock": [
        "product_id",
        "batch_no",
        "unrestricted_qty",
        "inspection_qty",
        "restricted_stock",
        "blocked_qty",
        "return_qty",
        "valuated_blocked_stock",
        "issued_container",
        "in_transit_stock",
        "shipment_and_transfer",
        "stock_segment",
        "plant_transfer_in_progress",
    ],

    # 11. 배치 재고 (Batch Stock)
    "batch_stock": [
        "product_id",
        "manufacture_date",
        "expiration_date",
        "batch_no",
        "material_group",
        "available_stock_value",
        "quality_inspection_stock_value",
        "blocked_stock_value",
        "receipt_date",
    ],

    # 12. 생산품목코드 매핑 (Prod Plan Map)
    "prod_plan_code_map": [
        "product_id",
        "description",
        "country",
        "packing_unit",
    ],

    # 13. 부적합 이력 (Non Conformance)
    "non_conformance": [
        "material_id",
        "material_description",
        "plant_code",
        "storage_location",
        "movement_type_text",
        "movement_type",
        "special_stock",
        "material_document",
        "material_document_item",
        "posting_date",
        "document_date",
        "batch_no",
        "entry_quantity",
        "entry_unit",
        "entry_date",
        "entry_time",
        "user_name",
        "order_id",
        "purchase_order",
        "sales_order",
        "sales_order_item",
        "header_text",
        "movement_indicator",
        "goods_recipient",
        "amount_local_currency"
    ]
}