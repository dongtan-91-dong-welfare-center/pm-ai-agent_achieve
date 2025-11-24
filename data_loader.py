import pandas as pd
import os

# 데이터 파일 경로 설정
# 추후 DB 연결 시 삭제
DATA_DIR = "data"

# 테이블별 필요한 컬럼 정의 (Parsing Logic)
# 아래 리스트에 정의된 컬럼만 추출하여 저장
# 필요하다면 {'Excel_Col_Name': 'DB_Col_Name'} 형태의 매핑 딕셔너리로 확장 가능
TABLE_SCHEMA = {
    "product": [
        "product_id", "plant_code", "product_type", "description",
        "base_unit", "stock_available"
    ],
    "bom": [
        "parent_product_id", "component_product_id", "component_quantity", "bom_level"
    ],
    "plan": [
        "plan_id", "product_id", "planned_qty", "due_date"
    ],
    "inventory": [
        "product_id", "plant_code", "storage_loc", "current_stock"
    ]
}


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

        # BOM 컬럼명 통일 작업 (기존 로직 유지)
        if not db["bom"].empty and "child_product_id" in db["bom"].columns:
            db["bom"].rename(columns={"child_product_id": "component_product_id"}, inplace=True)

        return db

    except Exception as e:
        print(f"데이터 로드 중 오류: {e}")
        return {}


    # try:
    #     df_product = pd.read_csv(os.path.join(DATA_DIR, "product.csv"))
    #
    #     df_inventory = pd.read_csv(os.path.join(DATA_DIR, "inventory.csv"))
    #
    #     df_bom = pd.read_csv(os.path.join(DATA_DIR, "bom.csv"))
    #     df_bom.rename(columns={"child_product_id": "component_product_id"}, inplace=True)
    #
    #     df_plan = pd.read_csv(os.path.join(DATA_DIR, "plan.csv"))
    #
    #     print("모든 데이터 파일 로드 성공")
    #
    #     return {
    #         "product": df_product,
    #         "inventory": df_inventory,
    #         "bom": df_bom,
    #         "plan": df_plan
    #     }
    #
    # except FileNotFoundError as e:
    #     print(f"파일 로드 실패: {e}")
    #     # 파일이 없을 경우를 대비한 빈 데이터프레임 반환 (에러 방지용)
    #     return {
    #         "product": pd.DataFrame(),
    #         "inventory": pd.DataFrame(),
    #         "bom": pd.DataFrame(),
    #         "plan": pd.DataFrame()
    #     }


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

        # 컬럼 파싱 (필요한 컬럼만 남기기)
        required_cols = TABLE_SCHEMA[table_type]

        # 엑셀 헤더와 우리 DB 스키마 간의 교집합 컬럼만 선택
        # TO-DO: 여기서 'Excel컬럼명' -> 'DB컬럼명' rename 로직을 추가
        available_cols = [c for c in required_cols if c in df.columns]

        if not available_cols:
            return False, f"업로드한 파일에 필요한 컬럼이 없습니다. (필요: {required_cols})"

        filtered_df = df[available_cols]

        # 3. 데이터 정제 (결측치 처리 등 - 필요 시 추가)
        filtered_df = filtered_df.fillna(0)

        # 4. CSV로 저장 (기존 파일 덮어쓰기)
        if not os.path.exists(DATA_DIR):
            os.makedirs(DATA_DIR)

        save_path = os.path.join(DATA_DIR, f"{table_type}.csv")
        filtered_df.to_csv(save_path, index=False)

        return True, f"{table_type} 데이터 {len(filtered_df)}건 적재 완료 (저장 경로: {save_path})"

    except Exception as e:
        return False, f"파싱 실패: {str(e)}"