"""
설명: UI 버튼 클릭 시 실행되는 즉시 실행 도구 (Top_Items, Error_Log 시트 복구 버전)

[Role & Responsibility]
- Legacy Logic Restoration: 현업 요구사항인 4개 시트(Summary, Top_Items, Detail, Error_Log)를 모두 생성합니다.
- Top Items Rule: ROH1은 금액 기준 상위 1개, ROH2는 상위 3개를 추출합니다.
- Error Logging: 마스터 데이터 매핑 실패나 유형 미분류 건을 별도 시트에 기록합니다.
"""

import pandas as pd
import os
import re
from datetime import datetime
from .shared import DB, OUTPUT_DIR

# =============================================================================
# 2. 발주 현황 공유 파일 생성 (Original Format)
# =============================================================================
def run_po_status_report() -> str:
    """
    [발주 현황 공유 파일 생성]
    최근 2년 데이터를 조회하고, '제품 유형'별로 시트를 분할하여 저장합니다.
    시트 이름 생성 시 특수문자 제거 로직을 포함합니다.
    """
    print("\n" + "=" * 60)
    print(">>> [Process] 발주 현황 리포트 (Original Format) 생성 시작")
    print("=" * 60)

    try:
        po_df = DB.get('purchase_order', pd.DataFrame()).copy()
        vendor_df = DB.get('vendor_info_record', pd.DataFrame()).copy()
        prod_df = DB.get('product', pd.DataFrame()).copy()

        if po_df.empty: return "데이터 오류: 구매오더 데이터가 없습니다."

        # 정규화
        po_df['vendor_id'] = po_df['vendor_id'].apply(normalize_id)
        po_df['product_id'] = po_df['product_id'].apply(normalize_id)
        vendor_df['vendor_id'] = vendor_df['vendor_id'].apply(normalize_id)
        prod_df['product_id'] = prod_df['product_id'].apply(normalize_id)

        # 날짜 필터링
        if 'po_date' in po_df.columns:
            po_df['po_date'] = pd.to_datetime(po_df['po_date'], errors='coerce')

        today = datetime.now()
        two_years_ago = today - pd.DateOffset(years=2)
        filtered_po = po_df[(po_df['po_date'] >= two_years_ago) & (po_df['po_date'] <= today)].copy()

        if filtered_po.empty: return "알림: 최근 2년 내의 발주 내역이 존재하지 않습니다."

        # 병합
        merged_df = filtered_po.merge(vendor_df[['vendor_id', 'vendor_name']].drop_duplicates(), on='vendor_id', how='left')
        merged_df = merged_df.merge(prod_df[['product_id', 'description', 'product_type']].drop_duplicates(), on='product_id', how='left')

        # Product Type 결측치 처리
        merged_df.loc[merged_df['product_type'].isna() | (merged_df['product_type'].astype(str).str.strip() == ''), 'product_type'] = 'Unclassified'

        # 엑셀 저장 (시트 분할)
        file_date = today.strftime("%Y%m%d")
        filename = f"PO_Status_Share_{file_date}.xlsx"
        file_path = os.path.join(OUTPUT_DIR, filename)

        with pd.ExcelWriter(file_path, engine='openpyxl') as writer:
            for p_type in merged_df['product_type'].unique():
                # 시트명 특수문자 제거
                sheet_name = re.sub(r'[\\/*?:\[\]]', '', str(p_type))[:30] or "Etc"
                merged_df[merged_df['product_type'] == p_type].to_excel(writer, sheet_name=sheet_name, index=False)

        return f"파일 생성 완료: {file_path}"

    except Exception as e:
        return f"파일 저장 실패: {str(e)}"


# =============================================================================
# 3. 공급업체 평가 관리 양식 생성 (Original Format)
# =============================================================================
def run_supplier_evaluation_report() -> str:
    """
    [공급업체 평가 관리 양식 생성]
    입고 내역과 부적합 내역을 매칭하여 '부적합 여부' 컬럼을 생성합니다.
    """
    print("\n" + "=" * 60)
    print(">>> [Process] 공급업체 평가 양식 (Original Format) 생성 시작")
    print("=" * 60)

    try:
        gr_df = DB.get('good_receipt', pd.DataFrame()).copy()
        po_df = DB.get('purchase_order', pd.DataFrame()).copy()
        prod_df = DB.get('product', pd.DataFrame()).copy()
        vendor_df = DB.get('vendor_info_record', pd.DataFrame()).copy()
        nc_df = DB.get('non_conformance', pd.DataFrame()).copy()

        if gr_df.empty: return "데이터 오류: 입고 내역(Good_Receipt)이 없습니다."

        # 1. ID 정규화 (전체 적용)
        gr_df['batch_no'] = gr_df['batch_no'].astype(str).apply(normalize_id)
        gr_df['po_id'] = gr_df['po_id'].astype(str).apply(normalize_id)
        gr_df['product_id'] = gr_df['product_id'].astype(str).apply(normalize_id)

        po_df['po_id'] = po_df['po_id'].astype(str).apply(normalize_id)
        po_df['vendor_id'] = po_df['vendor_id'].astype(str).apply(normalize_id)
        vendor_df['vendor_id'] = vendor_df['vendor_id'].astype(str).apply(normalize_id)
        prod_df['product_id'] = prod_df['product_id'].astype(str).apply(normalize_id)

        if not nc_df.empty and 'batch_no' in nc_df.columns:
            nc_df['batch_no'] = nc_df['batch_no'].astype(str).apply(normalize_id)

        # 2. 부적합 판별
        nc_batch_set = set()
        if not nc_df.empty:
            nc_batch_set = set(nc_df['batch_no'].dropna().unique())

        gr_df = gr_df.dropna(subset=['batch_no'])
        gr_base = gr_df.drop_duplicates(subset=['batch_no']).copy()

        gr_base['is_non_conformance'] = gr_base['batch_no'].apply(
            lambda x: "부적합" if x in nc_batch_set else "적합"
        )

        # 3. 데이터 병합
        po_ref = po_df[['po_id', 'vendor_id', 'po_date', 'delivery_date']].drop_duplicates(subset=['po_id'])
        vendor_ref = vendor_df[['vendor_id', 'vendor_name']].drop_duplicates(subset=['vendor_id'])
        prod_ref = prod_df[['product_id', 'description']].drop_duplicates(subset=['product_id'])

        merged_df = gr_base.merge(po_ref, on='po_id', how='left')
        merged_df = merged_df.merge(vendor_ref, on='vendor_id', how='left')
        merged_df['vendor_name'] = merged_df['vendor_name'].fillna("Unknown")

        merged_df = merged_df.merge(prod_ref, on='product_id', how='left')
        merged_df['description'] = merged_df['description'].fillna("-")

        # 4. 납품 LT 계산
        merged_df['po_date'] = pd.to_datetime(merged_df['po_date'], errors='coerce')
        merged_df['delivery_date'] = pd.to_datetime(merged_df['delivery_date'], errors='coerce')
        merged_df['delivery_lt'] = (merged_df['delivery_date'] - merged_df['po_date']).dt.days.fillna(0)

        # 5. 컬럼 정리 (현업 양식)
        final_cols = {
            'vendor_name': '업체명',
            'product_id': '품목코드',
            'description': '품목명',
            'batch_no': '성적번호',
            'delivery_lt': '납품 LT (일)',
            'is_non_conformance': '부적합 여부'
        }

        # 평가용 공란 컬럼 추가
        for col in ['부적합 사유', '납품 지연 사유', '지연 통보 선제성', '납품 기준 준수']:
            merged_df[col] = ""

        result_df = merged_df.rename(columns=final_cols)
        target_cols = list(final_cols.values()) + ['부적합 사유', '납품 지연 사유', '지연 통보 선제성', '납품 기준 준수']
        valid_target_cols = [c for c in target_cols if c in result_df.columns]

        result_df = result_df[valid_target_cols].drop_duplicates()

        # 6. 저장
        today_str = datetime.now().strftime("%Y%m%d")
        filename = f"Supplier_Evaluation_{today_str}.xlsx"
        file_path = os.path.join(OUTPUT_DIR, filename)

        with pd.ExcelWriter(file_path, engine='openpyxl') as writer:
            result_df.to_excel(writer, index=False, sheet_name='평가양식')

        return f"평가양식 생성 완료: {file_path}"

    except Exception as e:
        return f"파일 저장 실패: {str(e)}"