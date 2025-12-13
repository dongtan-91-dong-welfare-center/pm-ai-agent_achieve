import unittest
from unittest.mock import patch
import pandas as pd
import os
import sys

# 프로젝트 루트 경로를 sys.path에 추가하여 모듈 import 가능하게 설정
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 테스트할 도구 모듈 import
# (주의: tools.py가 루트 혹은 적절한 경로에 있어야 함)
from tools import generate_purchase_prediction


class TestPurchasePredictionTool(unittest.TestCase):

    def setUp(self):
        """테스트 실행 전 가상 데이터(DB) 준비"""
        # 1. 자재 마스터 (Product)
        self.df_product = pd.DataFrame([
            {'product_id': 'RM-001', 'description': '테스트자재A', 'product_type': 'ROH'},
            {'product_id': 'FG-001', 'description': '완제품A', 'product_type': 'FERT'}
        ])

        # 2. 창고 재고 (Warehouse Stock) - RM-001 50개 보유
        self.df_stock = pd.DataFrame([
            {'product_id': 'RM-001', 'unrestricted_qty': 50, 'batch_no': 'B001'}
        ])

        # 3. BOM (Parent: FG-001 -> Child: RM-001, 소요량 1)
        self.df_bom = pd.DataFrame([
            {'parent_product_id': 'FG-001', 'component_product_id': 'RM-001', 'component_qty': 1}
        ])

        # 4. 생산 계획 (Production Plan) - 2건의 계획
        # 계획1: 1월 1일, 30개 생산 (RM-001 30개 소요 -> 재고 50개로 충분)
        # 계획2: 1월 5일, 40개 생산 (RM-001 40개 소요 -> 재고 20개 남음 -> 20개 부족 -> 발주 필요)
        self.df_plan = pd.DataFrame([
            {
                'material_type': 'FG-001',  # 제품코드 역할로 가정
                'packing_unit': 30,
                'start_date': '2025-01-01',
                'serial_no': 'PLAN-01'
            },
            {
                'material_type': 'FG-001',
                'packing_unit': 40,
                'start_date': '2025-01-05',
                'serial_no': 'PLAN-02'
            }
        ])

        # 5. 공급업체 (Vendor)
        self.df_vendor = pd.DataFrame([
            {'vendor_id': 'V001', 'vendor_name': '한국공급사'}
        ])

        # 6. 구매 이력 (Purchase Order) - 공급업체 매핑용
        self.df_po = pd.DataFrame([
            {'product_id': 'RM-001', 'vendor_id': 'V001'}
        ])

        # 가상의 DB 딕셔너리 생성
        self.mock_db = {
            'product': self.df_product,
            'warehouse_stock': self.df_stock,
            'bom': self.df_bom,
            'production_plan': self.df_plan,
            'vendor': self.df_vendor,
            'purchase_order': self.df_po
        }

    @patch('tools.DB')  # tools.py의 전역변수 DB를 가로챔(Mocking)
    def test_running_balance_logic(self, mock_db_ref):
        """시나리오: Running Balance가 정상 작동하여 2번째 계획에서만 발주가 나가는지 검증"""

        # Mock DB 연결
        mock_db_ref.__getitem__.side_effect = self.mock_db.__getitem__
        mock_db_ref.get.side_effect = self.mock_db.get
        mock_db_ref.copy.return_value = self.mock_db  # copy() 호출 대응

        print("\n>>> 테스트 시작: 자재 발주 예측 도구 (Running Balance 검증)")

        # 도구 실행
        result_msg = generate_purchase_prediction.invoke("")

        print(f"도구 실행 결과 메시지: {result_msg}")

        # 1. 파일 생성 확인
        expected_file = "output/Purchase_Order_Prediction.xlsx"
        self.assertTrue(os.path.exists(expected_file), "결과 파일이 생성되지 않았습니다.")

        # 2. 엑셀 내용 검증
        df_result = pd.read_excel(expected_file)
        print("\n[생성된 엑셀 데이터 미리보기]")
        print(df_result.to_markdown(index=False))

        # 검증 포인트 A: 행 개수 (1건이어야 함. 1월 1일건은 재고로 충당됨)
        self.assertEqual(len(df_result), 1, "발주 데이터는 1건이어야 합니다 (1/1일자는 재고 충당).")

        # 검증 포인트 B: 발주 수량 (필요 40 - 잔여 20 = 20)
        actual_qty = df_result.iloc[0]['수량']
        self.assertEqual(actual_qty, 20, f"발주 수량은 20개여야 합니다. (실제: {actual_qty})")

        # 검증 포인트 C: 납품 일자 (1월 5일)
        actual_date = str(df_result.iloc[0]['납품일자'])
        self.assertIn("2025-01-05", actual_date, "납품 일자는 2025-01-05여야 합니다.")

        # 검증 포인트 D: 컬럼 순서 및 이름 (A~E열 요구사항 준수)
        expected_cols = ["품목코드", "품목명", "수량", "납품일자", "공급업체"]
        self.assertListEqual(list(df_result.columns), expected_cols, "컬럼 순서나 이름이 요구사항과 다릅니다.")

        print(">>> 테스트 성공: 로직이 정상적으로 작동합니다.")

    def tearDown(self):
        """테스트 후 생성된 파일 정리"""
        if os.path.exists("output/Purchase_Order_Prediction.xlsx"):
            # 디버깅을 위해 파일을 남겨두고 싶으면 아래 줄 주석 처리
            os.remove("output/Purchase_Order_Prediction.xlsx")
            pass


if __name__ == '__main__':
    unittest.main()