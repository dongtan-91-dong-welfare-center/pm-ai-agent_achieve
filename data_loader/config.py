import os

# 데이터 저장 경로
DATA_DIR = "data"

# 테이블 스키마 정의
TABLE_SCHEMA = {

    # 자재
    "product": [
        "product_id",
        "product_type",
        "plant_code",
        # "description",
        "base_unit",
        "plant_status",
        "prod_storage_loc",
        "ep_storage_loc",
        "remaining_shelf_life",
        "total_shelf_life",
        "inspection_setting",
        "product_group",
        # "product_group_description",
        "edition_no",
        "is_attachment",
    ],

    # 공급업체
    "vendor": [
        "vendor_id",
        # "vendor_name",
        "purchase_org",
        "order_currency",
    ],

    # BOM
    "bom": [
        "product_id",
        "standard_qty",
        "level",
        "parent_product_id",
        "component_product_id",
        "component_qty",
    ],

    # 생산 계획
    "production_plan": [
        "serial_no",
        "material_type",
        "country",
        "quantity",
        "remark",
        "start_date",
        "end_date",
        "batch_no",
    ],

    # 자재수불부
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

    # 입고 이력
    "good_receipt": [
        "work_datetime",
        "po_id",
        "item_no",
        "product_id",
        "batch_no",
        "manufacturing_no",
        "manufacturing_date",
        "expiration_date",
        "receipt_qty",
        "inspection_lot_no",
    ],

    # 구매 오더
    "purchase_order": [
        "po_id",
        "vendor_id",
        "product_id",
        "posting_date",
        "order_qty",
        "order_price",
    ],

    # 유효 기한
    "batch_stock": [
        "product_id",
        "manufacture_date",
        "expiration_date",
        "batch_no",
        "available_qty",
        "quality_inspection_qty",
        "blocked_stock",
        "available_stock_value",
        "quality_inspection_stock_value",
        "blocked_stock_value",
        "receipt_date",
    ],

    # 창고 재고
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
}