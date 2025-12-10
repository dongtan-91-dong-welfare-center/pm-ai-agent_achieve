import os
import sys
import pandas as pd

# 1. 상위 폴더(프로젝트 루트) 경로 설정
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
sys.path.append(parent_dir)

# 2. 데이터 로더 모듈 가져오기
try:
    import data_loader
except ImportError:
    data_loader = None
    print("Warning: data_loader module not found.")


# -------------------------------------------------------------------------
# 공통 변수 정의 및 데이터 정제 (Data Cleaning Layer)
# -------------------------------------------------------------------------

def reload_critical_data_as_string(existing_db):
    """
    [핵심 수정] Data Loader가 숫자로 잘못 읽어 유실된 ID를 복구하기 위해,
    핵심 파일만 '문자열(String)'로 강제하여 다시 로드합니다.
    """
    print(">>> [System] Reloading critical files with dtype=str to prevent data loss...")

    # 다시 읽을 파일 목록 (파일명이 프로젝트 루트에 있다고 가정)
    # 실제 파일명이 다르면 이곳을 수정해야 합니다.
    files_to_reload = {
        'purchase_transaction_history': '구매내역.xlsx',
        'product': '자재.xlsx'
    }

    for key, filename in files_to_reload.items():
        file_path = os.path.join(parent_dir, filename)

        if os.path.exists(file_path):
            try:
                # [핵심] dtype=str : 모든 데이터를 텍스트로 읽어옴 (000 유지, 정밀도 손실 방지)
                df = pd.read_excel(file_path, dtype=str)

                # 공백 제거
                df = df.apply(lambda x: x.str.strip() if x.dtype == "object" else x)

                # DB 갱신
                existing_db[key] = df
                print(f"   -> Reloaded '{filename}' successfully (Row count: {len(df)})")
            except Exception as e:
                print(f"   -> Failed to reload '{filename}': {e}. Keeping original data.")
        else:
            print(f"   -> File '{filename}' not found in root. Keeping original data.")

    return existing_db


def clean_master_data(raw_db):
    """
    데이터 타입 보정 및 전처리
    """
    # 1. 핵심 데이터 재로딩 (String 강제)
    db = reload_critical_data_as_string(raw_db)

    # 2. 전처리
    for key, df in db.items():
        if isinstance(df, pd.DataFrame) and not df.empty:

            # 날짜 변환
            for col in ['receipt_date', 'start_date', 'info_rec_date']:
                if col in df.columns:
                    df[col] = pd.to_datetime(df[col], errors='coerce')

            # 숫자(금액/수량) 변환 (문자열 -> 숫자)
            num_cols = ['received_value_local_currency', 'order_qty', 'received_quantity', 'unrestricted_qty']
            for col in num_cols:
                if col in df.columns:
                    if df[col].dtype == 'object':
                        df[col] = df[col].astype(str).str.replace(',', '', regex=False)
                    df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)

            # 통화 컬럼 정제
            if 'order_currency' in df.columns:
                df['order_currency'] = df['order_currency'].fillna('').astype(str).str.strip().str.upper()

            db[key] = df

    return db


# 3. 데이터 로드 실행
print("Loading Master Data...")
if data_loader:
    # 1차 로드 (data_loader 이용)
    _raw_db = data_loader.load_master_data()
    # 2차 정제 (재로딩 포함)
    DB = clean_master_data(_raw_db)
else:
    DB = {}

# 4. 결과 저장 경로 설정
OUTPUT_DIR = os.path.join(parent_dir, "output")
if not os.path.exists(OUTPUT_DIR):
    os.makedirs(OUTPUT_DIR)

print(f"Shared setup complete. Output Dir: {OUTPUT_DIR}")