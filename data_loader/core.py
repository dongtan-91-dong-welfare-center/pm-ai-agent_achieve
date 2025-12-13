"""
설명: 데이터 파일 입출력 및 전처리 핵심 로직 (FILE_NAME_MAP 적용 버전)

"""

import os
from typing import Union, IO
import pandas as pd
from . import config as dl_conf
from . import processors

# FILE_PROCESSORS 매핑 정보 (유지)
FILE_PROCESSORS = {
    # 1. 마스터 데이터
    "자재 마스터(product)": ("product", processors.process_product_info, "UPSERT_ROWS", "product_id"),
    "착인 여부(product)": ("product", processors.process_attachment_info, "EXTEND_COLUMNS", "product_id"),
    "에디션(product)": ("product", processors.process_edition_info, "EXTEND_COLUMNS", "product_id"),
    "BOM": ("bom", processors.process_bom_info, "REPLACE_ALL", None),
    "공급업체/구매정보(vendor_info_record)": ("vendor_info_record", processors.process_vendor_info, "REPLACE_ALL", None),
    "오버리지 기준(overage_rule)": ("overage_rule", processors.process_overage_rule_info, "REPLACE_ALL", None),

    # 2. 계획 및 오더
    "생산 계획(production_plan)": ("production_plan", processors.process_production_plan, "REPLACE_ALL", None),
    "구매오더(purchase_order)": ("purchase_order", processors.process_purchase_order_info, "REPLACE_ALL", None),
    "생산품목코드 매핑(prod_plan_code_map)": ("prod_plan_code_map", processors.process_prod_plan_code_map_info, "REPLACE_ALL",
                                      None),

    # 3. 이력 데이터
    "구매/재무 내역(purchase_transaction_history)": ("purchase_transaction_history",
                                               processors.process_purchase_transaction_history_info, "REPLACE_ALL",
                                               None),
    "입고이력(good_receipt)": ("good_receipt", processors.process_good_receipt_info, "REPLACE_ALL", None),
    "자재수불부(material_ledger)": ("material_ledger", processors.process_material_ledger_info, "REPLACE_ALL", None),
    "부적합 이력 (non_conformance)": ("non_conformance", processors.process_non_conformance_info, "UPSERT_ROWS", "batch_no"),

    # 4. 재고 데이터
    "배치재고(batch_stock)": ("batch_stock", processors.process_batch_stock_info, "REPLACE_ALL", None),
    "창고재고(warehouse_stock)": ("warehouse_stock", processors.process_warehouse_stock_info, "REPLACE_ALL", None),
}


# -------------------------------------------------------------------------
# Helper: 파일 경로 결정 함수 (New)
# -------------------------------------------------------------------------
def _get_file_path(table_key: str) -> str:
    """
    config.py의 FILE_NAME_MAP을 참조하여 정확한 파일 경로를 반환합니다.
    매핑이 없으면 기본값(key + .csv)을 사용합니다.
    """
    # 1. 매핑 정보 확인 (있으면 사용)
    if hasattr(dl_conf, 'FILE_NAME_MAP'):
        filename = dl_conf.FILE_NAME_MAP.get(table_key)
        if filename:
            return os.path.join(dl_conf.DATA_DIR, filename)

    # 2. Fallback (기존 로직)
    return os.path.join(dl_conf.DATA_DIR, f"{table_key}.csv")


def save_uploaded_file_by_type(uploaded_file: Union[pd.DataFrame, IO], source_type: str) -> tuple[bool, str]:
    """xlsx 데이터 통합 저장 로직 (Merge & Load)"""

    id_col_mapping = {
        "자재 마스터(product)": ["자재"],
        "착인 여부(product)": ["자재"],
        "에디션(product)": ["자재"],
        "공급업체/구매정보(vendor_info_record)": ["공급업체", "자재번호", "제조자"],
        "오버리지 기준(overage_rule)": ["자재", "포장재코드"],
        "생산 계획(production_plan)": [],
        "구매오더(purchase_order)": ["구매 문서", "공급업체", "자재"],
        "구매/재무 내역(purchase_transaction_history)": ["구매문서번호", "자재코드", "구매업체"],
        "입고이력(good_receipt)": ["구매 문서 번호", "자재 번호", "배치번호"],
        "자재수불부(material_ledger)": ["자재"],
        "배치재고(batch_stock)": ["자재", "배치"],
        "창고재고(warehouse_stock)": ["자재", "배치"],
        "생산품목코드 매핑(prod_plan_code_map)": ["자재"]
    }

    if source_type not in FILE_PROCESSORS:
        return False, f"지원하지 않는 파일 형식입니다."

    target_table, processor_func, strategy, pk_col = FILE_PROCESSORS[source_type]

    # 파일 경로 결정 (FILE_NAME_MAP 사용)
    file_path = _get_file_path(target_table)

    try:
        # 엑셀 파일 로드 및 전처리
        if target_table == "production_plan":
            if hasattr(uploaded_file, 'seek'):
                uploaded_file.seek(0)
            new_df = processor_func(uploaded_file)
        else:
            if isinstance(uploaded_file, pd.DataFrame):
                raw_df = uploaded_file
            else:
                if hasattr(uploaded_file, 'seek'):
                    uploaded_file.seek(0)

                dtype_map = {}
                target_headers = id_col_mapping.get(source_type, [])
                for header in target_headers:
                    dtype_map[header] = str

                raw_df = pd.read_excel(uploaded_file, dtype=dtype_map)

            new_df = processor_func(raw_df)

        if strategy == "REPLACE_ALL":
            if not os.path.exists(dl_conf.DATA_DIR):
                os.makedirs(dl_conf.DATA_DIR)
            new_df.to_csv(file_path, index=False)
            return True, f"[{source_type}] 저장 완료. {len(new_df)}건)"

        if strategy in ["UPSERT_ROWS", "EXTEND_COLUMNS"] and not pk_col:
            return False, "설정 오류: 해당 전략은 식별자(PK)가 필요합니다."

        if pk_col not in new_df.columns:
            return False, f"업로드된 파일에 PK 컬럼({pk_col})이 없습니다."
        try:
            new_df.loc[:, pk_col] = new_df[pk_col].astype(str).str.strip()
        except Exception as e:
            return False, f"PK 컬럼 처리 중 오류: {e}"

        if os.path.exists(file_path):
            current_df = pd.read_csv(file_path, dtype={pk_col: str})
            current_df[pk_col] = current_df[pk_col].astype(str).str.strip()
        else:
            current_df = pd.DataFrame()

        if current_df.empty:
            final_df = new_df
        else:
            current_df.set_index(pk_col, inplace=True)
            new_df.set_index(pk_col, inplace=True)

            if strategy == "UPSERT_ROWS":
                final_df = current_df.combine_first(new_df)
                final_df.update(new_df)

            elif strategy == "EXTEND_COLUMNS":
                for col in new_df.columns:
                    if col not in current_df.columns:
                        current_df[col] = pd.NA
                current_df.update(new_df)
                final_df = current_df
            else:
                final_df = pd.DataFrame()

            final_df.reset_index(inplace=True)

        if not os.path.exists(dl_conf.DATA_DIR):
            os.makedirs(dl_conf.DATA_DIR)
        final_df.to_csv(file_path, index=False)

        return True, f"[{source_type}] 처리 완료. (전략: {strategy}, 총 {len(final_df)}건)"

    except Exception as e:
        return False, f"오류 발생: {str(e)}"


def load_master_data():
    """모든 마스터 데이터 로드 (FILE_NAME_MAP 적용)"""
    db = {}
    try:
        # TABLE_SCHEMA에 정의된 키를 순회
        for table_name in dl_conf.TABLE_SCHEMA.keys():

            # 파일 경로 결정 (FILE_NAME_MAP 사용)
            file_path = _get_file_path(table_name)

            if os.path.exists(file_path):
                # ID 컬럼 강제 문자열 지정
                # (파일이 커서 전체를 다 읽지 않고 헤더만 읽어서 컬럼 확인)
                temp_df = pd.read_csv(file_path, nrows=1)

                # ID로 추정되는 컬럼들 식별
                id_like_cols = [
                    c for c in temp_df.columns
                    if c in ('product_id', 'vendor_id', 'po_id', 'batch_no', 'manufacturing_no')
                       or c.endswith('_id')
                ]
                dtype_map = {col: str for col in id_like_cols}

                # 전체 로드
                df = pd.read_csv(file_path, dtype=dtype_map)

                # 공백 제거 등 정규화
                for col in id_like_cols:
                    if col in df.columns:
                        df[col] = df[col].astype(str).str.strip()

                db[table_name] = df
            else:
                # 파일 없음: 빈 DataFrame 생성
                db[table_name] = pd.DataFrame(columns=dl_conf.TABLE_SCHEMA.get(table_name, []))

        return db
    except Exception as e:
        print(f"데이터 로드 중 오류: {e}")
        return {}


def append_purchase_order_row(row: dict) -> tuple[bool, str]:
    """Append a single purchase order row."""
    # 파일 경로 결정
    file_path = _get_file_path("purchase_order")

    try:
        raw_df = pd.DataFrame([row])
        from .processors import process_purchase_order_info
        proc_df = process_purchase_order_info(raw_df)

        if os.path.exists(file_path):
            current_df = pd.read_csv(file_path, dtype={'po_id': str, 'product_id': str, 'vendor_id': str})
            for col in ['po_id', 'product_id', 'vendor_id']:
                if col in current_df.columns:
                    current_df[col] = current_df[col].astype(str).str.strip()
        else:
            current_df = pd.DataFrame(columns=proc_df.columns)

        final_df = pd.concat([current_df, proc_df], ignore_index=True, sort=False)

        if not os.path.exists(dl_conf.DATA_DIR):
            os.makedirs(dl_conf.DATA_DIR)
        final_df.to_csv(file_path, index=False)
        return True, f"구매오더가 정상적으로 저장되었습니다. (총 {len(final_df)}건)"
    except Exception as e:
        return False, f"오류 발생: {str(e)}"


def append_purchase_order_rows(rows: list) -> tuple[bool, str]:
    """Append multiple purchase order rows."""
    try:
        raw_df = pd.DataFrame(rows)
        from .processors import process_purchase_order_info
        proc_df = process_purchase_order_info(raw_df)

        # 파일 경로 결정
        file_path = _get_file_path("purchase_order")

        if os.path.exists(file_path):
            current_df = pd.read_csv(file_path, dtype={'po_id': str, 'product_id': str, 'vendor_id': str})
        else:
            current_df = pd.DataFrame(columns=proc_df.columns)

        final_df = pd.concat([current_df, proc_df], ignore_index=True, sort=False)

        if not os.path.exists(dl_conf.DATA_DIR):
            os.makedirs(dl_conf.DATA_DIR)
        final_df.to_csv(file_path, index=False)
        return True, f"구매오더가 정상적으로 저장되었습니다. (총 {len(final_df)}건)"
    except Exception as e:
        return False, f"오류 발생: {str(e)}"


def get_database_schema_string(meta_file_path="data/Datas.csv"):
    """(기존 로직 유지)"""
    if not os.path.exists(meta_file_path):
        return "Schema metadata file not found. Please verify 'Datas.csv' path."

    try:
        df_meta = pd.read_csv(meta_file_path)
        df_meta.columns = [c.strip() for c in df_meta.columns]
    except Exception as e:
        return f"Error loading schema metadata: {str(e)}"

    schema_str = "### Database Schema Information (Security Level: Schema-Only)\n"
    schema_str += "NOTE: Use these exact variable names and understand column meanings.\n\n"

    if df_meta.empty:
        return "Schema metadata is empty."

    tables = df_meta['개체(영문)'].dropna().unique()

    for table_name in tables:
        table_info = df_meta[df_meta['개체(영문)'] == table_name]
        var_name = f"df_{table_name.lower()}"
        schema_str += f"#### Table: {table_name} (Variable: `{var_name}`)\n"

        for _, row in table_info.iterrows():
            col_name = row.get('속성(영문)', 'N/A')
            col_type = row.get('데이터 타입', 'Unknown')
            col_desc = row.get('속성 설명', '')
            if isinstance(col_desc, str):
                col_desc = col_desc.replace('\n', ' ').strip()
            schema_str += f"  - `{col_name}` ({col_type}): {col_desc}\n"
        schema_str += "\n"

    return schema_str