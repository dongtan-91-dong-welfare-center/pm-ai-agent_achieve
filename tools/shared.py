import os
import sys

# 1. 상위 폴더(프로젝트 루트)를 파이썬 경로에 추가 (data_loader.py를 찾기 위함)
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
sys.path.append(parent_dir)

# 2. 데이터 로더 모듈 가져오기
try:
    import data_loader
except ImportError:
    # 경로 문제 발생 시 예외 처리 (IDE 경고 방지용 더미 데이터)
    data_loader = None
    print("Warning: data_loader module not found.")

# -------------------------------------------------------------------------
# 공통 변수 정의 (DB, OUTPUT_DIR)
# -------------------------------------------------------------------------

# 3. 마스터 데이터 로드 (DB 변수 생성)
print("Loading Master Data in shared.py...")
if data_loader:
    DB = data_loader.load_master_data()
else:
    DB = {} # 로드 실패 시 빈 딕셔너리로 초기화하여 import 에러 방지

# 4. 결과 저장 경로 설정 (OUTPUT_DIR 변수 생성)
OUTPUT_DIR = os.path.join(parent_dir, "output")

if not os.path.exists(OUTPUT_DIR):
    os.makedirs(OUTPUT_DIR)

print(f"Shared setup complete. Output Dir: {OUTPUT_DIR}")
