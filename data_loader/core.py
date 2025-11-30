import os
import pandas as pd
from .config import DATA_DIR, TABLE_SCHEMA
from . import processors


# 프로세서 매핑 (파일명: (Target Table, Func, Strategy, PK))
FILE_PROCESSORS = {
    "자재 정보": ("product", processors.process_product_info, "UPSERT_ROWS", "product_id", ),
    "자재 외부 착인 여부": ("product", processors.process_attachment_info, "EXTEND_COLUMNS", "product_id", ),
    "자재 에디션": ("product", processors.process_edition_info, "EXTEND_COLUMNS", "product_id", ),
    "공급업체 목록": ("vendor",processors.process_vendor_info,"UPSERT_ROWS", "vendor_id", ),
    "BOM": ("bom", processors.process_bom_info, "REPLACE_ALL", None),
    "생산 계획": ("production_plan", processors.process_production_plan, "REPLACE_ALL", None),
    "자재수불부": ("material_ledger", processors.process_material_ledger_info, "REPLACE_ALL", None),
}


def save_uploaded_file_by_type(uploaded_file, source_type):
    """xlsx 데이터 통합 저장 로직 (Merge & Load)"""
    if source_type not in FILE_PROCESSORS:
        return False, f"지원하지 않는 파일 형식입니다."

    target_table, processor_func, strategy, pk_col = FILE_PROCESSORS[source_type]
    # 기존 데이터를 불러오기 위한 경로 설정
    file_path = os.path.join(DATA_DIR, f"{target_table}.csv")

    try:
        # 엑셀 파일 로드 및 전처리
        if source_type == "생산 계획":
            new_df = processor_func(uploaded_file)  # openpyxl은 파일 객체를 직접 필요로 함
        else:
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