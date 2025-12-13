import pytest
import pandas as pd
import os
import sys

# 프로젝트 루트 경로를 sys.path에 추가 (모듈 import 문제 해결)
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import data_loader
from tools import generate_purchase_prediction
import tools


class TestRealDataIntegration:

    @pytest.fixture(autouse=True)
    def setup_real_data(self):
        """
        테스트 실행 전 실제 데이터를 로드합니다.
        데이터가 없으면 테스트를 건너뜁니다(Skip).
        """
        try:
            # 실제 데이터 로드
            print("\n[Setup] 실제 마스터 데이터 로딩 중...")
            tools.DB = data_loader.load_master_data()

            # 필수 데이터 존재 여부 체크
            required_tables = ['production_plan', 'bom', 'warehouse_stock']
            for table in required_tables:
                if tools.DB.get(table) is None or tools.DB[table].empty:
                    pytest.skip(f"필수 데이터 테이블({table})이 비어있어 통합 테스트를 수행할 수 없습니다.")

        except Exception as e:
            pytest.fail(f"데이터 로드 중 에러 발생: {str(e)}")

    def test_generate_prediction_with_real_data(self):
        """
        실제 데이터를 사용하여 발주 예측 도구가 정상 동작하는지 테스트합니다.
        """
        print("\n>>> [Test] 발주 예측 도구 실행 (Real Data)")

        # 1. 도구 실행
        try:
            result_msg = generate_purchase_prediction.invoke("")
            print(f"\n[Result Message]\n{result_msg}")
        except Exception as e:
            pytest.fail(f"도구 실행 중 예외 발생: {str(e)}")

        # 2. 결과 검증
        # 케이스 A: 발주할 것이 없는 경우
        if any(k in result_msg for k in ["발주 필요 없음", "발주 대상이 없습니다", "발주 대상 없음"]):
            print(">> 결과: 모든 재고가 충분하여 발주 파일이 생성되지 않음.")
            return

        # 케이스 B: 발주 파일이 생성된 경우
        expected_path = "output/Purchase_Order_Prediction.xlsx"

        # 파일 생성 확인
        assert os.path.exists(expected_path), "결과 메시지는 성공했으나, 실제 엑셀 파일이 존재하지 않습니다."

        # 엑셀 내용 읽기 및 검증
        df = pd.read_excel(expected_path)
        print(f"\n>> 생성된 파일 데이터 ({len(df)}건):")
        print(df.head().to_markdown(index=False))

        # 필수 컬럼 존재 여부 확인 (A~E열)
        required_cols = ["품목코드", "품목명", "수량", "납품일자", "공급업체"]
        for col in required_cols:
            assert col in df.columns, f"결과 파일에 필수 컬럼 '{col}'이 누락되었습니다."

        print("\n>>> 통합 테스트 성공!")


if __name__ == "__main__":
    # 이 파일 자체를 python으로 실행할 경우를 대비해 pytest 호출
    sys.exit(pytest.main(["-v", __file__]))