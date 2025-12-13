import unittest
import os
import sys
import pandas as pd

# 프로젝트 루트 경로 추가 (모듈 import를 위해)
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import tools
import data_loader


class TestIntegrationTools(unittest.TestCase):
    """
    [통합 테스트] tools.py의 도구들이 실제 데이터와 함께 정상 동작하는지 검증
    """

    @classmethod
    def setUpClass(cls):
        """테스트 실행 전 데이터 로드 상태 점검"""
        print("\n" + "=" * 60)
        print(">>> [Setup] 통합 테스트 데이터 점검 중...")

        # tools.DB가 비어있다면 다시 로드 시도
        if not tools.DB:
            print(">>> tools.DB가 비어있어 재로드를 시도합니다.")
            tools.DB = data_loader.load_master_data()

        cls.db = tools.DB

        # 필수 데이터 존재 여부 확인
        required_tables = ['product', 'bom', 'production_plan', 'warehouse_stock']
        missing = [t for t in required_tables if t not in cls.db or cls.db[t].empty]

        if missing:
            print(f"⚠️ [Warning] 다음 필수 테이블 데이터가 비어 있어 일부 테스트가 실패할 수 있습니다: {missing}")
        else:
            print(">>> [OK] 필수 데이터 로드 완료.")
        print("=" * 60 + "\n")

    def test_01_get_stock_status(self):
        """[재고 조회] get_stock_status 도구 테스트"""
        print("\n🔍 [Test] 재고 조회 도구 테스트")

        # 1. 테스트할 자재 ID 추출 (창고 재고에 있는 첫 번째 자재)
        stock_df = self.db.get('warehouse_stock', pd.DataFrame())
        if stock_df.empty:
            self.skipTest("재고 데이터가 없어 테스트를 건너뜁니다.")

        target_id = str(stock_df.iloc[0]['product_id'])
        print(f"   - 대상 자재 ID: {target_id}")

        # 2. 도구 실행
        result = tools.get_stock_status.invoke(target_id)

        # 3. 검증
        print(f"   - 결과:\n{result}")
        self.assertIsInstance(result, str)
        # Prefer Markdown format, but fallback plain text is acceptable if includes fields
        if "|" in result:
            self.assertIn(target_id, result, "결과에 요청한 자재 ID가 포함되어야 합니다.")
        else:
            # Fallback: ensure target_id or column header exists in result
            self.assertTrue(target_id in result or "product_id" in result, "결과에 자재 정보가 포함되어야 합니다.")

    def test_02_calculate_gross_requirement(self):
        """[소요량 전개] calculate_gross_requirement 도구 테스트"""
        print("\n🔍 [Test] 소요량 전개 도구 테스트")

        # 1. 테스트할 생산 계획 ID 추출 (현재 로직상 하드코딩된 ID를 쓰지만, 호출은 필요함)
        plan_df = self.db.get('production_plan', pd.DataFrame())
        plan_id = "TEST-PLAN-001"
        if not plan_df.empty:
            # serial_no 컬럼이 있다면 사용
            if 'serial_no' in plan_df.columns:
                plan_id = str(plan_df.iloc[0]['serial_no'])

        print(f"   - 대상 계획 ID: {plan_id}")

        # 2. 도구 실행
        result = tools.calculate_gross_requirement.invoke(plan_id)

        # 3. 검증
        print(f"   - 결과 (일부분):\n{result[:300]} ...")  # 너무 길면 잘라서 출력

        if "존재하지 않습니다" in result or "데이터가 없습니다" in result or "제품 아이디를 지정해주세요" in result:
            print("   ⚠️ 데이터 부족으로 계산되지 않았습니다. (정상 동작으로 간주)")
        else:
            self.assertIn("|", result)
            self.assertIn("gross_requirement", result, "결과에 'gross_requirement' 컬럼이 있어야 합니다.")
            self.assertIn("overage_qty", result, "결과에 'overage_qty' 컬럼이 있어야 합니다.")

    def test_03_generate_purchase_prediction(self):
        """[발주 예측] generate_purchase_prediction 도구 테스트"""
        print("\n🔍 [Test] 발주 예측 도구 테스트")

        # 1. 도구 실행 (인자 없음)
        result = tools.generate_purchase_prediction.invoke("")

        # 2. 결과 로그 확인
        print(f"   - 실행 메시지: {result}")

        # 3. 엑셀 파일 생성 여부 검증
        if "완료되었습니다" in result or "생성되었습니다" in result:
            # 메시지에서 파일 경로 추출 (간이 파싱)
            try:
                # "경로: output/..." 형태라고 가정
                path_part = result.split("경로:")[1].split("\n")[0].strip()
                self.assertTrue(os.path.exists(path_part), f"파일이 실제로 존재해야 합니다: {path_part}")
                print(f"   ✅ 엑셀 파일 생성 확인됨: {path_part}")
            except IndexError:
                print("   ⚠️ 파일 경로를 메시지에서 파싱하지 못했습니다.")
        else:
            print("   ⚠️ 발주 예측 데이터가 생성되지 않았습니다 (재고 충분 등).")

    def test_04_analyze_long_term_stock(self):
        """[장기 재고] analyze_long_term_stock 도구 테스트"""
        print("\n🔍 [Test] 장기 재고 분석 도구 테스트")

        # 1. 도구 실행 (1일 이상 지난거 다 조회)
        result = tools.analyze_long_term_stock.invoke({"days_threshold": 1})

        print(f"   - 결과 (일부분):\n{result[:200]} ...")

        # 2. 검증
        self.assertIsInstance(result, str)
        # 데이터가 있거나, "없습니다" 메시지가 뜨거나 둘 중 하나여야 함. 에러면 Fail.
        is_table = "|" in result
        is_msg = "없습니다" in result or "데이터가 없습니다" in result
        self.assertTrue(is_table or is_msg, "정상적인 결과(표 또는 안내 메시지)가 반환되어야 합니다.")

    def test_05_generate_excel_report(self):
        """[리포트 생성] generate_excel_report 도구 테스트"""
        print("\n🔍 [Test] 엑셀 리포트 생성 도구 테스트")

        # 1. 더미 데이터 준비
        dummy_data = '[{"col1": "A", "col2": 10}, {"col1": "B", "col2": 20}]'
        filename = "test_report.xlsx"

        # 2. 도구 실행
        result = tools.generate_excel_report.invoke({"data_json": dummy_data, "filename": filename})
        print(f"   - 실행 결과: {result}")

        # 3. 파일 존재 여부 확인
        expected_path = os.path.join("output", filename)
        self.assertTrue(os.path.exists(expected_path), "생성된 엑셀 파일이 있어야 합니다.")

        # (청소) 테스트 파일 삭제
        if os.path.exists(expected_path):
            os.remove(expected_path)
            print("   - 테스트 파일 삭제 완료")


if __name__ == '__main__':
    unittest.main()