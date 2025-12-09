import os
import pandas as pd
from .config import DATA_DIR, TABLE_SCHEMA
from . import processors


# 프로세서 매핑 (파일명: (Target Table, Func, Strategy, PK))
FILE_PROCESSORS = {
    # 1. 마스터 데이터 (Master Data)
    "자재 마스터(product)": ("product", processors.process_product_info, "UPSERT_ROWS", "product_id"),
    "착인 여부(product)": ("product", processors.process_attachment_info, "EXTEND_COLUMNS", "product_id"),
    "에디션(product)": ("product", processors.process_edition_info, "EXTEND_COLUMNS", "product_id"),
    "BOM": ("bom", processors.process_bom_info, "REPLACE_ALL", None),
    "공급업체/구매정보(vendor_info_record)": ("vendor_info_record", processors.process_vendor_info, "REPLACE_ALL", None),
    "오버리지 기준(overage_rule)": ("overage_rule", processors.process_overage_rule_info, "REPLACE_ALL", None),

    # 2. 계획 및 오더 (Planning & Order)
    "생산 계획(production_plan)": ("production_plan", processors.process_production_plan, "REPLACE_ALL", None),
    "구매오더(purchase_order)": ("purchase_order", processors.process_purchase_order_info, "REPLACE_ALL", None),
    "생산품목코드 매핑(prod_plan_code_map)": ("prod_plan_code_map", processors.process_prod_plan_code_map_info, "REPLACE_ALL", None),

    # 3. 이력 데이터 (History) - [신규 추가됨]
    "구매/재무 내역(purchase_transaction_history)": ("purchase_transaction_history", processors.process_purchase_transaction_history_info, "REPLACE_ALL", None),
    "입고이력(good_receipt)": ("good_receipt", processors.process_good_receipt_info, "REPLACE_ALL", None),
    "자재수불부(material_ledger)": ("material_ledger", processors.process_material_ledger_info, "REPLACE_ALL", None),

    # 4. 재고 데이터 (Stock)
    "배치재고(batch_stock)": ("batch_stock", processors.process_batch_stock_info, "REPLACE_ALL", None), # 오타 수정됨
    "창고재고(warehouse_stock)": ("warehouse_stock", processors.process_warehouse_stock_info, "REPLACE_ALL", None),
}


def save_uploaded_file_by_type(uploaded_file, source_type):
    """xlsx 데이터 통합 저장 로직 (Merge & Load)"""
    if source_type not in FILE_PROCESSORS:
        return False, f"지원하지 않는 파일 형식입니다."

    # 설정값 가져오기
    target_table, processor_func, strategy, pk_col = FILE_PROCESSORS[source_type]
    # 기존 데이터를 불러오기 위한 경로 설정
    file_path = os.path.join(DATA_DIR, f"{target_table}.csv")

    try:
        # 엑셀 파일 로드 및 전처리
        if target_table == "production_plan":
            uploaded_file.seek(0)
            new_df = processor_func(uploaded_file)  # openpyxl은 파일 객체를 직접 필요로 함
        else:
            uploaded_file.seek(0)
            raw_df = pd.read_excel(uploaded_file)
            new_df = processor_func(raw_df)

        # 단순 교체 전략 (BOM 등 PK가 없는 경우)
        if strategy == "REPLACE_ALL":
            # 병합 로직 없이 바로 저장 (덮어쓰기)
            if not os.path.exists(DATA_DIR):
                os.makedirs(DATA_DIR)
            new_df.to_csv(file_path, index=False)
            return True, f"[{source_type}] 저장 완료. {len(new_df)}건)"

        # PK가 필요한 전략인데 PK가 None이면 에러 처리
        if strategy in ["UPSERT_ROWS", "EXTEND_COLUMNS"] and not pk_col:
            return False, "설정 오류: 해당 전략은 식별자(PK)가 필요합니다."

        # 새로운 데이터에 대해 숫자로 들어오든 문자로 들어오든 무조건 str로 맞추고 공백을 날립니다.
        new_df.loc[:, pk_col] = new_df[pk_col].astype(str).str.strip()

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


def load_master_data():
    """모든 마스터 데이터 로드"""
    db = {}
    try:
        # TABLE_SCHEMA에 정의된 테이블들을 순회하며 로드
        for table_name in TABLE_SCHEMA.keys():
            file_path = os.path.join(DATA_DIR, f"{table_name}.csv")
            if os.path.exists(file_path):
                # 원본 데이터 그대로 로드 (Description 포함)
                db[table_name] = pd.read_csv(file_path)
            else:
                # 파일이 없으면 빈 DataFrame 생성
                db[table_name] = pd.DataFrame(columns=TABLE_SCHEMA.get(table_name, []))
        return db
    except Exception as e:
        print(f"데이터 로드 중 오류: {e}")
        return {}


def get_database_schema_string(meta_file_path="data/Datas.csv"):
    """
    실제 데이터(Row)는 절대 조회하지 않음.
    대신 'Datas.csv' (메타 데이터)를 읽어 테이블/컬럼의 의미와 타입을 상세히 기술한 문자열을 생성함.
    """

    # 1. 메타 데이터 파일 로드 (없으면 기본 스키마 반환)
    if not os.path.exists(meta_file_path):
        return "Schema metadata file not found. Please verify 'Datas.csv' path."

    try:
        # CSV 로드 (인코딩 주의: 한글이 포함되어 있으므로 euc-kr 또는 utf-8 확인 필요)
        # 업로드된 파일 내용을 보니 헤더가 '개체(영문)', '속성(영문)', '데이터 타입', '속성 설명' 등으로 되어 있음
        df_meta = pd.read_csv(meta_file_path)

        # 컬럼명 정규화 (공백 제거 등)
        df_meta.columns = [c.strip() for c in df_meta.columns]

    except Exception as e:
        return f"Error loading schema metadata: {str(e)}"

    schema_str = "### Database Schema Information (Security Level: Schema-Only)\n"
    schema_str += "NOTE: Use these exact variable names and understand column meanings.\n\n"

    # 2. 테이블 별로 그룹화하여 정보 추출
    # Datas.csv의 컬럼명: '개체(영문)', '속성(영문)', '데이터 타입', '속성 설명' 기준
    # 실제 파일 헤더에 맞춰 조정이 필요할 수 있음

    # 데이터프레임이 비어있지 않은지 확인
    if df_meta.empty:
        return "Schema metadata is empty."

    # 테이블 단위로 반복
    # '개체(영문)' 컬럼을 기준으로 그룹핑
    tables = df_meta['개체(영문)'].dropna().unique()

    for table_name in tables:
        # 해당 테이블의 데이터만 필터링
        table_info = df_meta[df_meta['개체(영문)'] == table_name]

        # 변수명 제안 (예: Product -> df_product)
        var_name = f"df_{table_name.lower()}"

        schema_str += f"#### Table: {table_name} (Variable: `{var_name}`)\n"

        # 컬럼 정보 반복
        for _, row in table_info.iterrows():
            col_name = row.get('속성(영문)', 'N/A')
            col_type = row.get('데이터 타입', 'Unknown')
            col_desc = row.get('속성 설명', '')

            # 설명에 줄바꿈이 있으면 제거
            if isinstance(col_desc, str):
                col_desc = col_desc.replace('\n', ' ').strip()

            # 포맷팅: - column_name (TYPE): Description
            schema_str += f"  - `{col_name}` ({col_type}): {col_desc}\n"

        schema_str += "\n"

    return schema_str