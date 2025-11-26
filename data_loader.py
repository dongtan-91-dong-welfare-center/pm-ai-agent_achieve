import pandas as pd
import os

# 데이터 파일 경로 설정
# 추후 DB 연결 시 삭제
DATA_DIR = "data"

# 파일 종류별 전처리 로직
def _process_product_info(df):
    """
    자재 정보의 뼈대를 잡는 파일을 처리
    """
    # 컬럼 매핑
    mapping = {
        "자재 유형": "product_type",
        "플랜트": "plant_code",
        "자재": "product_id",
        "자재 내역": "description",
        "기본 단위": "base_unit",
        "플랜트별 자재 상태": "plant_status",
        "생산 저장 위치": "prod_storage_loc",
        "EP 저장 위치": "ep_storage_loc",
        "잔여 유효 기간": "remaining_shelf_life_days",
        "총 셀프 라이프": "total_shelf_life_days",
    }
    df.rename(columns=mapping, inplace=True)

    # 필수 컬럼 확인(필요 시 추가)
    # if "product_id" not in df.columns or "delivering_plant" not in df.columns:
    #     raise ValueError("필수 컬럼(자재, 플랜트)이 누락되었습니다.")

    # 필수 PK가 없으면 드랍
    df.dropna(subset=["product_id"], inplace=True)

    # 중복 제거 (Product ID 기준)
    df.drop_duplicates(subset=["product_id"], keep="last", inplace=True)

    # 필수 컬럼만 남기기 (데이터 제거)
    valid_cols = [c for c in mapping.values() if c in df.columns]
    return df[valid_cols]


def _process_attachment_info(df):
    """
    기존 product 테이블에 외부 착인 정보를 추가함
    """
    mapping = {
        "자재": "product_id",
        "외부착인": "is_attachment",
    }
    df.rename(columns=mapping, inplace=True)

    # 로직 적용(필요 시 추가)
    # df['is_attachment'] = df['is_attachment'].map({'X': "No", None: "Yes"})

    # 필수 컬럼만 남기기
    return df[mapping.values()]  # 필요한 컬럼만 리턴


def _process_edition_info(df):
    """
    기존 product 테이블에 에디션 정보를 추가함
    """
    mapping = {
        "자재": "product_id",
        "Edition No.": "edition_no",
    }
    df.rename(columns=mapping, inplace=True)
    return df[mapping.values()]  # 필요한 컬럼만 리턴

def _process_vendor_info(df):
    """
    공급업체 정보 추가
    """
    mapping = {
        "공급업체": "vendor_id",
        "공급업체 이름": "vendor_name",
        "구매 조직": "purchase_organization",
        "오더 통화": "order_currency"
    }
    df.rename(columns=mapping, inplace=True)
    return df[mapping.values()]  # 필요한 컬럼만 리턴


def _process_bom_info(df):
    """[BOM] 자재 명세서 (PK 없음 / 단순 리스트)"""
    mapping = {
        "자재번호(Root)": "product_id",
        "기준 수량": "standard_quantity",
        "레벨": "level",
        "상위자재": "parent_product_id",
        "구성요소": "component_product_id",
        "구성부품수량": "component_quantity",
    }
    df.rename(columns=mapping, inplace=True)

    # 데이터 타입 보정 (Agent가 Join할 때 중요)
    # 외래키(FK) 역할을 하는 컬럼들은 문자열로 통일해줘야 나중에 Join이 잘 됨
    for col in ["product_id", "parent_product_id", "component_product_id"]:
        if col in df.columns:
            df[col] = df[col].astype(str).str.strip()

    return df[mapping.values()]


# 프로세서 등록 (Registry)

FILE_PROCESSORS = {
    # (UI표시 이름) : (타겟 테이블, 처리 함수, 병합 전략)
    "자재 정보": ("product", _process_product_info, "UPSERT_ROWS"),
    "자재 외부 착인 여부": ("product", _process_attachment_info, "EXTEND_COLUMNS"),
    "자재 에디션 숫자": ("product", _process_edition_info, "EXTEND_COLUMNS"),
    "공급업체 목록": ("vendor",_process_vendor_info,"UPSERT_ROWS"),
    "BOM": ("bom", _process_bom_info, "REPLACE_ALL"),
}


def save_uploaded_file_by_type(uploaded_file, source_type):
    """
    # xlsx 데이터 통합 저장 로직 (Merge & Load)
    """
    if source_type not in FILE_PROCESSORS:
        return False, f"지원하지 않는 파일 형식입니다."

    target_table, processor_func, strategy = FILE_PROCESSORS[source_type]
    # 기존 데이터를 불러오기 위한 경로 설정
    file_path = os.path.join(DATA_DIR, f"{target_table}.csv")

    try:
        # 엑셀 로드 및 전처리
        raw_df = pd.read_excel(uploaded_file)
        new_df = processor_func(raw_df)

        # 단순 교체 전략 (BOM 등 PK가 없는 경우)
        if strategy == "REPLACE_ALL":
            # 복잡한 병합 로직 없이 바로 저장 (덮어쓰기)
            if not os.path.exists(DATA_DIR):
                os.makedirs(DATA_DIR)

            new_df.to_csv(file_path, index=False)
            return True, f"[{source_type}] 저장 완료. {len(new_df)}건)"

        # PK 설정
        if target_table == 'product':
            pk_col = "product_id"
        elif target_table == 'vendor':
            pk_col = "vendor_id"
        # 필요 시 추가할 것
        else:
            pk_col = "" 
        
        # 필요 시 추가
        # if pk_col not in new_df.columns:
        #     return False, f"결과 데이터에 식별자({pk_col})가 없습니다."

        # 새로운 데이터에 대해 숫자로 들어오든 문자로 들어오든 무조건 str로 맞추고 공백을 날립니다.
        new_df[pk_col] = new_df[pk_col].astype(str).str.strip()

        # 기존 데이터가 존재하면, pk_col을 전처리
        if os.path.exists(file_path):
            current_df = pd.read_csv(file_path)
            current_df[pk_col] = current_df[pk_col].astype(str).str.strip()
        else:
            current_df = pd.DataFrame()

        if current_df.empty:
            final_df = new_df
        else:
            # 병합을 위해 pk_col을 인덱스로 설정
            current_df.set_index(pk_col, inplace=True)
            new_df.set_index(pk_col, inplace=True)

            # 병합 전략 실행
            if strategy == "UPSERT_ROWS":
                # 행 중심 병합: 새로운 컬럼이 있으면 추가하되, 주로 행(Row) 데이터를 최신화함

                # 컬럼 동기화 (새 파일에 없는 컬럼은 유지)
                final_df = current_df.combine_first(new_df)
                # update로 덮어쓰기 (new_df의 값이 우선)
                final_df.update(new_df)

            elif strategy == "EXTEND_COLUMNS":
                # 열 중심 병합: 기존 행은 건드리지 않고, 매칭되는 ID에 대해서만 값을 갱신/추가
                # 스키마 확장: 새 파일에 있는 컬럼이 기존에 없으면 빈 컬럼 추가
                for col in new_df.columns:
                    if col not in current_df.columns:
                        current_df[col] = pd.NA

                # 값 업데이트: 인덱스(ID)가 일치하는 곳에 값 덮어쓰기
                # update는 교집합(index가 양쪽에 모두 존재)에 대해서만 작동함
                current_df.update(new_df)
                final_df = current_df
            else:
                final_df = pd.DataFrame()
            # 병합 종료 후 인덱스를 다시 컬럼으로 변환
            final_df.reset_index(inplace=True)

        # 저장
        if not os.path.exists(DATA_DIR):
            os.makedirs(DATA_DIR)
        final_df.to_csv(file_path, index=False)

        return True, f"[{source_type}] 처리 완료. (전략: {strategy}, 총 {len(final_df)}건)"

    except Exception as e:
        return False, f"오류 발생: {str(e)}"

# # 명시적 매핑 정의 (현업 용어 -> 시스템 변수)
# COLUMN_MAPPING = {
#     "product": {
#         # product.xlsx
#         "자재 유형": "product_type",
#         "플랜트": "plant_code",
#         "자재": "product_id",
#         "자재 내역": "description",
#         "기본 단위": "base_unit",
#         "플랜트별 자재 상태": "plant_status",
#         "생산 저장 위치": "prod_storage_loc",
#         "EP 저장 위치": "ep_storage_loc",
#         "잔여 유효 기간": "remaining_shelf_life_days",
#         "총 셀프 라이프": "total_shelf_life_days",
#         #
#         "자재그룹내역": "",
#         "Edition Seq.": "edition_seq",
#         "Edition No.": "edition_no",
#         "유효 기한": "expiration date",
#         "외부 착인": "",
#         # "가용": "stock_available",
#         # "가용재고 값": "stock_available_value",
#         # "품질 검사": "stock_quality_inspection",
#         # "품질검사재고 값": "stock_quality_inspection_value",
#         # "보류 재고": "stock_blocked",
#         # "보류 재고 값": "stock_blocked_value",
#     },
#     "vendor": {
#         "공급업체": "vendor_id",
#         "공급업체 이름": "vendor_name",
#         "구매 조직": "organization",
#         "오더 통화": "order_currency"
#     },
#     "bom": {
#         "자재번호(Root)": "parent_product_id",
#         "구성요소": "component_product_id",
#         "구성부품수량": "component_quantity",
#         "기준 수량": "standard_quantity",
#         "상위자재": "parent_product_id",
#         "레벨": "bom_level",
#     },
#     "purchase_history": {
#         # "이력ID": "purchase_history_id",    # db를 추가하면 사용
#         "구매문서번호": "po_document_id",
#         "구매품목": "po_item_id",
#         "구매업체": "vendor_id",
#         "자재코드": "product_id",
#         "입고일자": "goods_receipt_date",
#         "이동유형": "movement_type",
#         "오더수량": "order_quantity",
#         "Info.Rec.수정일": "info_record_updated_at",
#         "OLD값": "old_value",
#         "NEW값": "new_value",
#         "마스터단가": "master_price",
#         "마스터단가통화": "master_price_currency",
#         "오더단가": "order_price",
#         "통화": "order_currency",
#         "단가단위수량": "price_unit",
#         "입고수량": "received_quantity",
#         "입고금액(발주통화)": "received_value_local_currency",
#         "제판비": "printing_plate_cost",
#         "동판비": "copper_plate_cost",
#         "입고총금액(발주통화)": "total_received_value_local_currency",
#         "입고금액(원화)": "received_value_krw",
#         "입고총금액(원화)": "total_received_value_krw",
#     },
#     "expiration_date": {
#         "자재": "product_id",
#         "제조일": "",
#         "유효 기한": "",
#         "배치": "",
#         "가용": "",
#         "품질 검사": "",
#         "보류재": "",
#         "자재 그룹": "",
#         "가용재고 값": "",
#         "품질검사재고 값": "",
#         "보류재고 값": "",
#         "입고일": "",
#     },
#     "plan": {
#         "품목코드": "product_id",
#         "품목명": "description",
#         "수량": "",
#         "납품일자": "",
#         "공급업체": "vendor_name"
#     }
# }

# # 테이블별 필요한 컬럼 정의 (Parsing Logic)
# # 아래 리스트에 정의된 컬럼만 추출하여 저장
# # 추후 LLM에 로드할 때 'description'을 drop 합니다.
TABLE_SCHEMA = {
    "product": [
        "product_id", "edition_no", "is_attachment", "product_type", "plant_code",
        # 보안상 LLM에 전달하지 않음
        # "description",
        "base_unit", "plant_status", "prod_storage_loc", "ep_storage_loc", "remaining_shelf_life_days",
        # 이후 추가해야 하는 것
        # "safety_stock", "lead_time_days", "standard_price", "currency",
    ],
    "vendor": [
        "vendor_id",
        # 보안상 LLM에 전달하지 않음
        # "vendor_name",
        "purchase_organization", "order_currency",
    ],
    "bom": [
        "product_id", "standard_quantity", "parent_product_id", "component_product_id", "component_quantity", "level",
    ],
    # 아직 미구현
    # "purchase_history": [
    #     "po_document_id", "po_item_id", "vendor_id", "product_id",
    #     "po_date", "goods_receipt_date", "received_quantity",
    #     "order_price", "total_amount_krw"
    # ],
    # 아직 미구현
    # "inventory": [
    #     "product_id", "plant_code", "storage_loc",
    #     "stock_unrestricted", "stock_quality_inspection", "stock_blocked"
    # ],
    # 아직 미구현
    # "plan": [
    #     "product_id", "description", "", "", "vendor_name",
    # ],
}

def load_master_data():
    """
    실제 CSV 파일을 로드하여 데이터프레임 딕셔너리로 반환
    CSV를 로드하되, LLM용(Secure) 데이터와 UI용(Mapping) 데이터를 분리하여 반환
    """
    db = {}

    try:
        # TABLE_SCHEMA에 정의된 테이블들을 순회하며 로드
        for table_name in TABLE_SCHEMA.keys():
            file_path = os.path.join(DATA_DIR, f"{table_name}.csv")

            if os.path.exists(file_path):
                # 원본 데이터 그대로 로드 (Description 포함)
                df = pd.read_csv(file_path)

                # 데이터 타입 보정 (예: 날짜, 숫자 등)이 필요하면 여기서 수행
                db[table_name] = df
            else:
                # 파일이 없으면 빈 DataFrame 생성
                db[table_name] = pd.DataFrame(columns=TABLE_SCHEMA.get(table_name, []))

        return db

    except Exception as e:
        print(f"데이터 로드 중 오류: {e}")
        return {}