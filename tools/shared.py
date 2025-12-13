"""
설명: 프로젝트 전역에서 공유되는 자원(데이터베이스, 경로)을 초기화하고 노출하는 모듈

[Role & Responsibility]
- Infrastructure: 애플리케이션 실행 시 1회 초기화되는 전역 변수(DB, OUTPUT_DIR)를 관리합니다.
- Dependency Injection: `data_loader` 모듈을 통해 엑셀/CSV 데이터를 메모리(Dictionary)로 로드합니다.
- Path Management: 모듈 간 임포트 경로 문제를 해결하기 위해 시스템 경로(sys.path)를 보정합니다.

[Key Architecture Note]
- 이 모듈이 임포트되는 순간 데이터 로딩이 시작됩니다(Import Side Effect).
- 로드된 `DB` 객체는 `old_nodes.py` 등에서 참조만 할 뿐, 원본을 변형해서는 안 됩니다(Immutable 지향).
"""

import os
import sys

# -------------------------------------------------------------------------
# 1. 시스템 경로 설정 (Module Resolution)
# -------------------------------------------------------------------------
# tools 패키지 내부에서 프로젝트 루트(parent_dir)에 있는 data_loader.py를 import 하기 위한 설정입니다.
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)

if parent_dir not in sys.path:
    sys.path.append(parent_dir)


# -------------------------------------------------------------------------
# 2. 데이터 로더 모듈 가져오기 (Lazy Import & Error Handling)
# -------------------------------------------------------------------------
try:
    # 프로젝트 루트의 data_loader.py 모듈
    # 실제 데이터 파싱 및 전처리는 이 모듈이 담당합니다.
    import data_loader
except ImportError:
    # IDE 환경이나 테스트 환경에서 경로 문제로 로드 실패 시 방어 로직
    # 배포 환경에서는 이 분기를 타면 안 되므로 로그 확인이 필요합니다.
    data_loader = None
    print("[Warning] tools/shared.py: 'data_loader' module not found. DB will be empty.")


# -------------------------------------------------------------------------
# 3. 마스터 데이터 로드 (In-Memory Database Initialization)
# -------------------------------------------------------------------------
# 애플리케이션 수명 주기 동안 유지되는 전역 데이터베이스 변수입니다.
# LLM에게는 이 데이터의 스키마만 전달되고, 실제 값은 이 변수에 보관됩니다.

print("Loading Master Data in shared.py... (One-time Execution)")

if data_loader:
    # load_master_data() 함수는 { "product": df_product, "bom": df_bom, ... } 형태의 딕셔너리를 반환합니다.
    DB = data_loader.load_master_data()
else:
    # 로드 실패 시 빈 딕셔너리로 초기화하여, 이후 코드에서 AttributeError가 아닌 KeyError가 발생하도록 유도
    DB = {}

# -------------------------------------------------------------------------
# 4. 결과물 저장 경로 설정 (Output Directory)
# -------------------------------------------------------------------------
# 엑셀 보고서, 그래프 이미지 등 생성된 파일이 저장될 물리적 경로입니다.
# 컨테이너 환경이나 클라우드 배포 시 볼륨 마운트 포인트가 될 수 있습니다.
OUTPUT_DIR = os.path.join(parent_dir, "output")

if not os.path.exists(OUTPUT_DIR):
    try:
        os.makedirs(OUTPUT_DIR)
        print(f"Created output directory: {OUTPUT_DIR}")
    except OSError as e:
        print(f"[Error] Failed to create output directory: {e}")

# 초기화 완료 로그
print(f"Shared setup complete. | DB Keys: {list(DB.keys())} | Output Dir: {OUTPUT_DIR}")