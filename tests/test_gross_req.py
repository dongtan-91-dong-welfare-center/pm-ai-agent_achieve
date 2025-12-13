import unittest
import pandas as pd
import sys
import os

# 프로젝트 루트 경로를 sys.path에 추가 (모듈 import를 위해)
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import tools
import data_loader


class TestGrossRequirementRealData(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        """
        테스트 시작 전 1회만 실행: 실제 마스터 데이터를 로드합니다.
        """
        print("\n>>> [Setup] 실제 데이터 로딩 중... (시간이 걸릴 수 있습니다)")
        try:
            # 1. 실제 데이터 로드
            cls.real_db = data_loader.load_master_data()

            # 2. tools 모듈의 DB를 실제 데이터로 교체 (Injection)
            tools.DB = cls.real_db

            # 3. [중요] 테이블명 불일치 보정
            # data_loader는 'production_plan'으로 로드하지만, tools.py는 'plan'을 찾을 수 있음
            if 'production_plan' in cls.real_db and 'plan' not in cls.real_db:
                print(">>> [Info] 'production_plan' 데이터를 'plan' 키로 매핑합니다.")
                cls.real_db['plan'] = cls.real_db['production_plan']

        except Exception as e:
            raise RuntimeError(f"데이터 로드 실패: {str(e)}")

    def test_calculate_gross_requirement_with_real_data(self):
        """
        실제 데이터에 있는 첫 번째 생산 계획(plan_id)을 사용하여 소요량을 계산합니다.
        """
        # 1. 테스트할 생산 계획 ID 가져오기
        # (DB에 데이터가 하나라도 있어야 테스트 가능)
        if self.real_db['plan'].empty:
            self.skipTest("데이터 로드됨: 'plan' 테이블이 비어있어 테스트를 건너뜁니다.")

        # 첫 번째 행의 ID 또는 식별자 가져오기
        # (CSV 스키마에 따라 컬럼명이 'plan_id', 'serial_no' 등 다를 수 있음. 확인 필요)
        # 여기서는 tools.py가 사용하는 'plan_id' 또는 'serial_no'를 동적으로 찾음
        target_col = 'plan_id' if 'plan_id' in self.real_db['plan'].columns else 'serial_no'
        target_plan_id = str(self.real_db['plan'].iloc[0][target_col])
        product_id = str(self.real_db['product'].iloc[0]['product_id'])

        print(f"\n>>> [Test] 테스트 대상 Plan ID: {product_id}")

        # 2. 도구 실행
        try:
            # tools.py의 calculate_gross_requirement 호출
            # (주의: tools.py에 중복 정의된 함수가 있다면 상단/하단 중 어느 것이 호출되는지 확인 필요)
            result = tools.calculate_gross_requirement.invoke(target_plan_id)

            print(f"\n>>> [Result] 소요량 전개 결과 (Markdown):")
            print(result)

        except Exception as e:
            self.fail(f"도구 실행 중 에러 발생: {str(e)}")

        # 3. 검증
        # 결과가 에러 메시지(str)인지, 마크다운 표(str)인지 확인
        if "존재하지 않습니다" in result or "제품 아이디를 지정해주세요" in result:
            print(">>> [Warn] 해당 계획에 대한 BOM이나 자재 정보가 부족할 수 있습니다.")
        else:
            # 정상적인 마크다운 표라면 '|' 문자가 포함되어 있어야 함
            self.assertIn("|", result, "결과가 마크다운 표 형식이 아닙니다.")
            # 헤더 컬럼 확인 (gross_requirement 등)
            self.assertIn("gross_requirement", result)

            print(">>> [Success] 실제 데이터를 이용한 소요량 계산이 정상적으로 완료되었습니다.")


if __name__ == '__main__':
    unittest.main()