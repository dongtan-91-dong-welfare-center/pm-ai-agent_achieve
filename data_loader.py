import pandas as pd
import os

# 데이터 파일 경로 설정
# 추후 DB 연결 시 삭제
DATA_DIR = "data"

# 명시적 매핑 정의 (가독성 및 안전성 확보)
COLUMN_MAPPING = {
    "product": {
        "자재": "product_id",
        "플랜트": "plant_code",
        "자재 유형": "product_type",
        # "자재 내역": "description",
        "기본 단위": "base_unit",
        # 재고 관련 컬럼은 별도 xlsx 파일로 업로드 하되 db에는 자재 코드를 기반으로 병합
        # "가용재고": "stock_available"
    },
    "bom": {
        "자재번호(Root)": "parent_product_id",
        "기준 수량": "standard_quantity",
        "레벨": "bom_level",
        "상위자재": "parent_product_id",
        "구성요소": "component_product_id",
        "구성부품수량": "component_quantity",
    },
    "purchase_history": {
        # "이력ID": "purchase_history_id",
        "구매문서번호": "po_document_id",
        "구매품목": "po_item_id",
        "입고일자": "goods_receipt_date",
        "이동유형": "movement_type",
        "자재코드": "product_id",
        "오더수량": "order_quantity",
        "Info.Rec.수정일": "info_record_updated_at",
        "OLD값": "old_value",
        "NEW값": "new_value",
        "마스터단가": "master_price",
        "마스터단가통화": "master_price_currency",
        "오더단가": "order_price",
        "통화": "order_currency",
        "단가단위수량": "price_unit",
        "입고수량": "received_quantity",
        "입고금액(발주통화)": "received_value_local_currency",
        "제판비": "printing_plate_cost",
        "동판비": "copper_plate_cost",
        "입고총금액(발주통화)": "total_received_value_local_currency",
        "입고금액(원화)": "received_value_krw",
        "입고총금액(원화)": "total_received_value_krw",
        "구매업체": "vendor_id"
    },
}

# 테이블별 필요한 컬럼 정의 (Parsing Logic)
# 아래 리스트에 정의된 컬럼만 추출하여 저장
TABLE_SCHEMA = {
    "product": [
        "product_id", "plant_code", "product_type",
        # "description",
        "base_unit",
        # "stock_available"
    ],
    "bom": [
        "parent_product_id", "component_product_id", "component_quantity",
        "standard_quantity", "bom_level"
    ],
    "purchase_history": [
        # "purchase_history_id",
        "po_document_id", "po_item_id", "goods_receipt_date",
        "movement_type", "product_id", "order_quantity", "info_record_updated_at",
        "old_value", "new_value", "master_price", "master_price_currency",
        "order_price", "order_currency", "price_unit", "received_quantity",
        "received_value_local_currency", "printing_plate_cost", "copper_plate_cost",
        "total_received_value_local_currency", "received_value_krw",
        "total_received_value_krw", "vendor_id"
    ],
    "plan": [
        "plan_id", "product_id", "planned_qty", "due_date"
    ],
    "inventory": [
        "product_id", "plant_code", "storage_loc", "current_stock"
    ]
}

def save_uploaded_excel(uploaded_file, table_type):
    """
    [Func-112] 사용자가 업로드한 엑셀 파일을 파싱하여 CSV로 저장
    Args:
        uploaded_file: Streamlit UploadedFile 객체
        table_type: 'product', 'bom' 등 테이블 유형
    """
    if table_type not in TABLE_SCHEMA:
        return False, f"정의되지 않은 테이블 유형입니다: {table_type}"

    try:
        # 엑셀 읽기
        df = pd.read_excel(uploaded_file, engine="openpyxl")

        # 한글 컬럼 -> 영문 컬럼 Rename
        if table_type in COLUMN_MAPPING:
            df.rename(columns=COLUMN_MAPPING[table_type], inplace=True)

        # 컬럼 파싱 (필요한 컬럼만 남기기)
        required_cols = TABLE_SCHEMA[table_type]

        # 엑셀 헤더와 우리 DB 스키마 간의 교집합 컬럼만 선택
        available_cols = [c for c in required_cols if c in df.columns]

        if available_cols != required_cols:
            return False, f"업로드한 파일에 필요한 컬럼이 없습니다. (필요: {set(required_cols)- set(available_cols)})"

        filtered_df = df[available_cols]

        # 데이터 정제 (결측치 처리 등 - 필요 시 로직 추가)
        filtered_df = filtered_df.fillna(0)

        # CSV로 저장 (기존 파일 덮어쓰기)
        if not os.path.exists(DATA_DIR):
            os.makedirs(DATA_DIR)

        save_path = os.path.join(DATA_DIR, f"{table_type}.csv")
        filtered_df.to_csv(save_path, index=False)

        return True, f"{table_type} 데이터 {len(filtered_df)}건 적재 완료 (저장 경로: {save_path})"

    except Exception as e:
        return False, f"파싱 실패: {str(e)}"

def load_master_data():
    """
    실제 CSV 파일을 로드하여 데이터프레임 딕셔너리로 반환
    """
    db = {}
    try:
        # 스키마에 정의된 키를 기반으로 로드 시도
        for table_name in TABLE_SCHEMA.keys():
            file_path = os.path.join(DATA_DIR, f"{table_name}.csv")
            if os.path.exists(file_path):
                db[table_name] = pd.read_csv(file_path)
            else:
                db[table_name] = pd.DataFrame(columns=TABLE_SCHEMA[table_name])

        # BOM 컬럼명 통일 작업
        if not db["bom"].empty and "child_product_id" in db["bom"].columns:
            db["bom"].rename(columns={"child_product_id": "component_product_id"}, inplace=True)

        return db

    except Exception as e:
        print(f"데이터 로드 중 오류: {e}")
        return {}