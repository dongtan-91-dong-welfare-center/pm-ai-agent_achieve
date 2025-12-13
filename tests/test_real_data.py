# test_real_data.py
import data_loader
from tools import generate_purchase_prediction
import pandas as pd

# 1. 실제 데이터 로드 테스트
print("1. 실제 데이터 로딩 중...")
try:
    # tools.py가 사용하는 전역 DB 변수 강제 리로드 (확인용)
    import tools

    tools.DB = data_loader.load_master_data()

    print("   - 생산계획 건수:", len(tools.DB['production_plan']))
    print("   - BOM 건수:", len(tools.DB['bom']))
    print("   - 창고재고 건수:", len(tools.DB['warehouse_stock']))
except Exception as e:
    print(f"   [Error] 데이터 로드 실패: {e}")
    exit()

# 2. 도구 실행
print("\n2. 발주 예측 도구 실행 중...")
try:
    result = generate_purchase_prediction.invoke("")
    print("\n[실행 결과]")
    print(result)
except Exception as e:
    print(f"\n[Error] 도구 실행 중 오류: {e}")

# 3. 데이터 검증 (옵션)
# 실제 데이터의 생산계획 상위 5개만 출력해보기
print("\n[참고] 로드된 생산계획 데이터 샘플:")
try:
     # Pandas to_markdown requires optional 'tabulate' dependency
     print(tools.DB['production_plan'].head().to_markdown())
except Exception:
     print(tools.DB['production_plan'].head().to_string())