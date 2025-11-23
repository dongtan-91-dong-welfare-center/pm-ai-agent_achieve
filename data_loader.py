import pandas as pd
import os

# 데이터 파일 경로 설정
# 추후 DB 연결 시 삭제
DATA_DIR = "data"

def load_master_data():
    """
    실제 CSV 파일을 로드하여 데이터프레임 딕셔너리로 반환
    """
    try:
        df_product = pd.read_csv(os.path.join(DATA_DIR, "product.csv"))

        df_inventory = pd.read_csv(os.path.join(DATA_DIR, "inventory.csv"))

        df_bom = pd.read_csv(os.path.join(DATA_DIR, "bom.csv"))
        df_bom.rename(columns={"child_product_id": "component_product_id"}, inplace=True)

        df_plan = pd.read_csv(os.path.join(DATA_DIR, "plan.csv"))

        print("모든 데이터 파일 로드 성공")

        return {
            "product": df_product,
            "inventory": df_inventory,
            "bom": df_bom,
            "plan": df_plan
        }

    except FileNotFoundError as e:
        print(f"파일 로드 실패: {e}")
        # 파일이 없을 경우를 대비한 빈 데이터프레임 반환 (에러 방지용)
        return {
            "product": pd.DataFrame(),
            "inventory": pd.DataFrame(),
            "bom": pd.DataFrame(),
            "plan": pd.DataFrame()
        }