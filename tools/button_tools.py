"""
파일명: tools/button_tools.py
설명: UI 버튼 클릭 시 실행되는 즉시 실행 도구 (Top_Items, Error_Log 시트 복구 버전)
작성자: 생산 관리 AI Agent 컨설턴트
수정일: 2025.12.13

[Role & Responsibility]
- Legacy Logic Restoration: 현업 요구사항인 4개 시트(Summary, Top_Items, Detail, Error_Log)를 모두 생성합니다.
- Top Items Rule: ROH1은 금액 기준 상위 1개, ROH2는 상위 3개를 추출합니다.
- Error Logging: 마스터 데이터 매핑 실패나 유형 미분류 건을 별도 시트에 기록합니다.
"""

import pandas as pd
import numpy as np
import os
import re
from datetime import datetime
from .shared import DB, OUTPUT_DIR

# =============================================================================
# [공통 유틸리티] ID 정규화 함수
# =============================================================================
def normalize_id(x):
    """
    ID 값을 문자열로 변환하고 정규화합니다.
    - None/NaN -> None
    - 실수형 문자열(.0) 제거
    - 앞뒤 공백 제거
    """
    if pd.isna(x): return None
    s = str(x).strip()
    if s.lower() == 'nan': return None
    if s.endswith('.0'): s = s[:-2]
    if not s: return None
    return s.lstrip('0') # 0 제거 로직 포함


# =============================================================================
# 1. 월말 구매마감 리포트 생성 (Full Sheets Restored)
# =============================================================================
def run_monthly_closing_process() -> str:
    """
    [월말 구매마감 리포트 생성]
    현업 요구사항에 맞춰 4개의 시트를 포함한 엑셀 파일을 생성합니다.
    1. Summary: 내자/외자, 원료/자재별 집계 및 전월 대비 증감
    2. Top_Items: 주요 지출 품목 (ROH1 Top 1, ROH2 Top 3)
    3. Detail_Data: 당월 상세 내역
    4. Error_Log: 마스터 누락 및 미분류 데이터
    """
    print("\n" + "=" * 60)
    print(">>> [Process] 월말 마감 리포트 (Full Sheets) 생성 시작")
    print("=" * 60)

    try:
        # 1. 데이터 로드
        txn_df = DB.get('purchase_transaction_history', pd.DataFrame()).copy()
        prod_df = DB.get('product', pd.DataFrame()).copy()

        if txn_df.empty: return "데이터 오류: 구매 상세 내역이 비어있습니다."
        if prod_df.empty: return "데이터 오류: 자재 마스터 데이터가 비어있습니다."

        # 2. 날짜 및 이동유형 전처리
        if 'receipt_date' in txn_df.columns:
            txn_df['receipt_date'] = pd.to_datetime(txn_df['receipt_date'], errors='coerce')

        if 'movement_type' in txn_df.columns:
            txn_df['movement_type'] = txn_df['movement_type'].apply(
                lambda x: str(x).strip().replace('.0', '') if pd.notnull(x) else None)
            target_types = ['101', '102']
            txn_df = txn_df[txn_df['movement_type'].isin(target_types)].copy()
            if txn_df.empty: return "데이터 오류: 이동유형 101/102 데이터가 없습니다."

        # 3. ID 정규화
        txn_df['product_id'] = txn_df['product_id'].apply(normalize_id)
        prod_df['product_id'] = prod_df['product_id'].apply(normalize_id)

        # 4. 데이터 병합 (Merge)
        # txn_df의 모든 행을 유지하기 위해 product_id가 없어도 일단 진행 (나중에 Error_Log로 분류)
        prod_unique = prod_df.drop_duplicates(subset=['product_id'], keep='first')
        merged_df = txn_df.merge(prod_unique[['product_id', 'product_type', 'description']], on='product_id', how='left')

        # 5. 금액 계산
        target_col = 'received_value_local_currency'
        if target_col in merged_df.columns:
            merged_df[target_col] = pd.to_numeric(merged_df[target_col], errors='coerce').fillna(0)
            if 'movement_type' in merged_df.columns:
                mask_cancel = merged_df['movement_type'] == '102'
                merged_df.loc[mask_cancel, target_col] = -np.abs(merged_df.loc[mask_cancel, target_col])
        else:
            merged_df[target_col] = 0

        # 6. 자재 유형 정제
        merged_df['product_type'] = merged_df['product_type'].astype(str).str.strip().str.upper()
        merged_df.loc[merged_df['product_type'].isin(['NAN', 'NONE', '']), 'product_type'] = 'UNCLASSIFIED'

        # 7. 기준 연월 설정
        valid_dates = merged_df['receipt_date'].dropna()
        if not valid_dates.empty:
            max_date = valid_dates.max()
            curr_year, curr_month = max_date.year, max_date.month
        else:
            now = datetime.now()
            curr_year, curr_month = now.year, now.month

        # ---------------------------------------------------------------------
        # Sheet 1: Summary (요약)
        # ---------------------------------------------------------------------

        # 참조 기간 계산
        if curr_month == 1:
            prev_month_date = datetime(curr_year - 1, 12, 1)
            ref1_y, ref1_m = curr_year - 1, 6; ref2_y, ref2_m = curr_year - 1, 9
        else:
            prev_month_date = datetime(curr_year, curr_month - 1, 1)
            if 1 < curr_month <= 3: ref1_y, ref1_m = curr_year - 1, 9; ref2_y, ref2_m = curr_year - 1, 12
            elif 3 < curr_month <= 6: ref1_y, ref1_m = curr_year - 1, 12; ref2_y, ref2_m = curr_year, 3
            elif 6 < curr_month <= 9: ref1_y, ref1_m = curr_year, 3; ref2_y, ref2_m = curr_year, 6
            else: ref1_y, ref1_m = curr_year, 6; ref2_y, ref2_m = curr_year, 9

        prev_month_y, prev_month_m = prev_month_date.year, prev_month_date.month

        # 집계 함수
        def calculate_sum(target_year, target_month, p_type, currency_condition):
            cond = (merged_df['product_type'] == p_type)
            if target_month != 0:
                cond &= (merged_df['receipt_date'].dt.year == target_year) & (merged_df['receipt_date'].dt.month == target_month)
            else:
                cond &= (merged_df['receipt_date'].dt.year == target_year)

            if 'order_currency' in merged_df.columns:
                curr_series = merged_df['order_currency'].fillna('').astype(str).str.strip().str.upper()
                if currency_condition == 'KRW': cond &= (curr_series == 'KRW')
                elif currency_condition == 'NON-KRW': cond &= (curr_series != 'KRW')
            return float(merged_df.loc[cond, target_col].sum())

        # KPI 산출
        roh1_krw_curr = calculate_sum(curr_year, curr_month, 'ROH1', 'KRW')
        roh1_krw_prev = calculate_sum(prev_month_y, prev_month_m, 'ROH1', 'KRW')
        roh1_krw_last = calculate_sum(curr_year - 1, 0, 'ROH1', 'KRW')
        roh1_krw_ref1 = calculate_sum(ref1_y, ref1_m, 'ROH1', 'KRW')
        roh1_krw_ref2 = calculate_sum(ref2_y, ref2_m, 'ROH1', 'KRW')

        roh1_for_curr = calculate_sum(curr_year, curr_month, 'ROH1', 'NON-KRW')
        roh1_for_prev = calculate_sum(prev_month_y, prev_month_m, 'ROH1', 'NON-KRW')
        roh1_for_last = calculate_sum(curr_year - 1, 0, 'ROH1', 'NON-KRW')
        roh1_for_ref1 = calculate_sum(ref1_y, ref1_m, 'ROH1', 'NON-KRW')
        roh1_for_ref2 = calculate_sum(ref2_y, ref2_m, 'ROH1', 'NON-KRW')

        roh2_krw_curr = calculate_sum(curr_year, curr_month, 'ROH2', 'KRW')
        roh2_krw_prev = calculate_sum(prev_month_y, prev_month_m, 'ROH2', 'KRW')
        roh2_krw_last = calculate_sum(curr_year - 1, 0, 'ROH2', 'KRW')
        roh2_krw_ref1 = calculate_sum(ref1_y, ref1_m, 'ROH2', 'KRW')
        roh2_krw_ref2 = calculate_sum(ref2_y, ref2_m, 'ROH2', 'KRW')

        # Summary DataFrame 구성
        summary_rows = [
            {"구분": "내자 원료 (ROH1)", "작년 총합": roh1_krw_last, f"참조1 ({ref1_y}.{ref1_m})": roh1_krw_ref1, f"참조2 ({ref2_y}.{ref2_m})": roh1_krw_ref2, "전월 실적": roh1_krw_prev, "당월 실적": roh1_krw_curr, "전월 대비 증감": roh1_krw_curr - roh1_krw_prev},
            {"구분": "외자 원료 (ROH1)", "작년 총합": roh1_for_last, f"참조1 ({ref1_y}.{ref1_m})": roh1_for_ref1, f"참조2 ({ref2_y}.{ref2_m})": roh1_for_ref2, "전월 실적": roh1_for_prev, "당월 실적": roh1_for_curr, "전월 대비 증감": roh1_for_curr - roh1_for_prev},
            {"구분": "내자 자재 (ROH2)", "작년 총합": roh2_krw_last, f"참조1 ({ref1_y}.{ref1_m})": roh2_krw_ref1, f"참조2 ({ref2_y}.{ref2_m})": roh2_krw_ref2, "전월 실적": roh2_krw_prev, "당월 실적": roh2_krw_curr, "전월 대비 증감": roh2_krw_curr - roh2_krw_prev},
        ]

        # 합계 계산
        def sum_rows(title, *rows):
            result = {"구분": title}
            keys = [k for k in rows[0].keys() if k != "구분"]
            for k in keys: result[k] = sum(row[k] for row in rows)
            return result

        summary_rows.append(sum_rows("원료 합계 (내자+외자)", summary_rows[0], summary_rows[1]))
        summary_rows.append(sum_rows("내자 합계 (원료+자재)", summary_rows[0], summary_rows[2]))
        summary_rows.append(sum_rows("전체 합계 (Total)", summary_rows[0], summary_rows[1], summary_rows[2]))

        df_summary = pd.DataFrame(summary_rows)

        # ---------------------------------------------------------------------
        # Sheet 2: Top_Items (주요 지출 품목) - [복구됨]
        # ---------------------------------------------------------------------

        # 당월 데이터 필터링
        current_month_df = merged_df[
            (merged_df['receipt_date'].dt.year == curr_year) &
            (merged_df['receipt_date'].dt.month == curr_month)
        ].copy()

        top_items_list = []
        if not current_month_df.empty:
            # 품목별 그룹화 (PO ID 집계 포함)
            if 'po_id' not in current_month_df.columns: current_month_df['po_id'] = '-'

            grouped = current_month_df.groupby(['product_id', 'product_type']).agg({
                'received_value_local_currency': 'sum',
                'description': 'first',
                'po_id': lambda x: ', '.join(sorted(x.dropna().astype(str).unique()))[:100] # PO 목록 요약
            }).reset_index()

            # ROH1 (원료) Top 1
            roh1_top = grouped[grouped['product_type'] == 'ROH1'].nlargest(1, 'received_value_local_currency')
            if not roh1_top.empty:
                row = roh1_top.iloc[0].to_dict()
                row['구분'] = '원료(ROH1) 최다 지출'
                top_items_list.append(row)

            # ROH2 (자재) Top 3
            roh2_top = grouped[grouped['product_type'] == 'ROH2'].nlargest(3, 'received_value_local_currency')
            if not roh2_top.empty:
                rank = 1
                for _, row in roh2_top.iterrows():
                    r_dict = row.to_dict()
                    r_dict['구분'] = f'자재(ROH2) Top {rank}'
                    top_items_list.append(r_dict)
                    rank += 1

            df_top_items = pd.DataFrame(top_items_list)
            # 컬럼 순서 정리
            if not df_top_items.empty:
                target_cols = ['구분', 'product_id', 'description', 'received_value_local_currency', 'po_id']
                existing_cols = [c for c in target_cols if c in df_top_items.columns]
                df_top_items = df_top_items[existing_cols]

                # 한글명으로 변경
                rename_map = {
                    'product_id': '자재 코드',
                    'description': '자재명',
                    'received_value_local_currency': '금액',
                    'po_id': '관련 PO'
                }
                df_top_items = df_top_items.rename(columns=rename_map)

        else:
            df_top_items = pd.DataFrame(columns=['구분', '메시지']) # 데이터 없음

        # ---------------------------------------------------------------------
        # Sheet 3: Detail_Data (상세 내역)
        # ---------------------------------------------------------------------
        df_detail = current_month_df.copy()

        # ---------------------------------------------------------------------
        # Sheet 4: Error_Log (오류 로그) - [복구됨]
        # ---------------------------------------------------------------------
        # 오류 조건:
        # 1. Product Type이 UNCLASSIFIED (마스터 매핑 실패 또는 유형 정보 없음)
        # 2. Description이 NaN (마스터에 없는 자재)

        error_mask = (merged_df['product_type'] == 'UNCLASSIFIED') | (merged_df['description'].isna())
        df_error = merged_df[error_mask].copy()

        # ---------------------------------------------------------------------
        # 엑셀 저장
        # ---------------------------------------------------------------------
        filename = f"Monthly_Closing_Report_{curr_year}_{curr_month:02d}.xlsx"
        file_path = os.path.join(OUTPUT_DIR, filename)

        with pd.ExcelWriter(file_path, engine='openpyxl') as writer:
            df_summary.to_excel(writer, sheet_name="Summary", index=False)

            if not df_top_items.empty:
                df_top_items.to_excel(writer, sheet_name="Top_Items", index=False)

            df_detail.to_excel(writer, sheet_name="Detail_Data", index=False)

            if not df_error.empty:
                df_error.to_excel(writer, sheet_name="Error_Log", index=False)
            else:
                # 에러가 없어도 시트는 생성하되 메시지 남김 (현업 확인용)
                pd.DataFrame({'Status': ['No Errors Found']}).to_excel(writer, sheet_name="Error_Log", index=False)

        return f"리포트 생성 완료: {file_path}"

    except Exception as e:
        return f"월말 마감 리포트 생성 실패: {str(e)}"


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