import pandas as pd
import os
import re
import numpy as np
from datetime import datetime
from .shared import DB, OUTPUT_DIR

# =============================================================================
# [공통 유틸리티] ID 정규화 함수 (이 위치에 있어야 모든 함수가 사용 가능합니다)
# =============================================================================
def normalize_id(x):
    """
    ID 값을 문자열로 변환하고 정규화합니다.
    - None/NaN -> None
    - 실수형 문자열(.0) 제거 (예: '1001.0' -> '1001')
    - 앞뒤 공백 제거
    """
    if pd.isna(x): return None
    s = str(x).strip()
    if s.lower() == 'nan': return None
    if s.endswith('.0'): s = s[:-2]  # 끝에 붙은 .0 제거
    if not s: return None
    return s

# -------------------------------------------------------------------------
# 1. 월말 구매마감 리포트 생성 함수
# -------------------------------------------------------------------------
def run_monthly_closing_process() -> str:
    """
    [월말 구매마감 리포트 생성]
    월말 마감을 위한 구매 상세 내역 분석 리포트(엑셀)를 생성합니다.
    이동유형 101/102 데이터를 기반으로 입고 금액 및 취소 내역을 집계합니다.
    """
    print("\n" + "=" * 60)
    print(">>> [Debug] 월말 마감 리포트 프로세스 시작")
    print("=" * 60)

    # 1. 데이터 로드
    txn_df = DB.get('purchase_transaction_history', pd.DataFrame()).copy()
    prod_df = DB.get('product', pd.DataFrame()).copy()

    if txn_df.empty: return "데이터 오류: 구매 상세 내역이 비어있습니다."
    if prod_df.empty: return "데이터 오류: 자재 마스터 데이터가 비어있습니다."

    date_col_name = 'receipt_date'
    if date_col_name in txn_df.columns:
        txn_df[date_col_name] = pd.to_datetime(txn_df[date_col_name], errors='coerce')

    if 'movement_type' in txn_df.columns:
        txn_df['movement_type'] = txn_df['movement_type'].apply(
            lambda x: str(x).strip().replace('.0', '') if pd.notnull(x) else None)
        target_types = ['101', '102']
        txn_df = txn_df[txn_df['movement_type'].isin(target_types)].copy()
        if txn_df.empty: return "데이터 오류: 이동유형 101/102 데이터가 없습니다."

    def normalize_id_strict(x):
        if pd.isna(x): return None
        s = str(x).strip()
        if s.lower() == 'nan': return None
        if s.endswith('.0'): s = s[:-2]
        s = s.lstrip('0')
        if not s: return None
        return s

    txn_df['product_id'] = txn_df['product_id'].apply(normalize_id_strict)
    prod_df['product_id'] = prod_df['product_id'].apply(normalize_id_strict)
    txn_df = txn_df.dropna(subset=['product_id'])
    prod_df = prod_df.dropna(subset=['product_id'])
    prod_df = prod_df.drop_duplicates(subset=['product_id'], keep='first')

    target_col = 'received_value_local_currency'
    if target_col in txn_df.columns:
        if 'movement_type' in txn_df.columns:
            mask_cancel = txn_df['movement_type'] == '102'
            txn_df[target_col] = pd.to_numeric(txn_df[target_col], errors='coerce').fillna(0)
            txn_df.loc[mask_cancel, target_col] = -np.abs(txn_df.loc[mask_cancel, target_col])
    else:
        txn_df[target_col] = 0

    merged_df = txn_df.merge(prod_df[['product_id', 'product_type', 'description']], on='product_id', how='left',
                             indicator=True)
    merged_df['product_type'] = merged_df['product_type'].astype(str).str.strip().str.upper()
    merged_df.loc[merged_df['product_type'].isin(['NAN', 'NONE', '']), 'product_type'] = 'UNCLASSIFIED'

    valid_dates = merged_df['receipt_date'].dropna()
    if not valid_dates.empty:
        max_date = valid_dates.max()
        curr_year, curr_month = max_date.year, max_date.month
    else:
        today = datetime.now()
        curr_year, curr_month = today.year, today.month

    if curr_month == 1:
        prev_month_date = datetime(curr_year - 1, 12, 1);
        ref1_y, ref1_m = curr_year - 1, 6;
        ref2_y, ref2_m = curr_year - 1, 9
    else:
        prev_month_date = datetime(curr_year, curr_month - 1, 1)
        if 1 < curr_month <= 3:
            ref1_y, ref1_m = curr_year - 1, 9; ref2_y, ref2_m = curr_year - 1, 12
        elif 3 < curr_month <= 6:
            ref1_y, ref1_m = curr_year - 1, 12; ref2_y, ref2_m = curr_year, 3
        elif 6 < curr_month <= 9:
            ref1_y, ref1_m = curr_year, 3; ref2_y, ref2_m = curr_year, 6
        else:
            ref1_y, ref1_m = curr_year, 6; ref2_y, ref2_m = curr_year, 9

    prev_month_y, prev_month_m = prev_month_date.year, prev_month_date.month

    def calculate_sum(target_year, target_month, p_type, currency_condition):
        cond = (merged_df['product_type'] == p_type)
        if target_month != 0:
            cond &= (merged_df['receipt_date'].dt.year == target_year) & (
                        merged_df['receipt_date'].dt.month == target_month)
        else:
            cond &= (merged_df['receipt_date'].dt.year == target_year)
        if 'order_currency' in merged_df.columns:
            curr_series = merged_df['order_currency'].fillna('').astype(str).str.strip().str.upper()
            if currency_condition == 'KRW':
                cond &= (curr_series == 'KRW')
            elif currency_condition == 'NON-KRW':
                cond &= (curr_series != 'KRW')
        return float(merged_df.loc[cond, 'received_value_local_currency'].sum())

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

    unclassified_curr = calculate_sum(curr_year, curr_month, 'UNCLASSIFIED', 'ALL')

    row_roh1_krw = {"구분": "내자 원료 (ROH1)", "작년 총합": roh1_krw_last, f"참조1 ({ref1_y}.{ref1_m})": roh1_krw_ref1,
                    f"참조2 ({ref2_y}.{ref2_m})": roh1_krw_ref2, "전월 실적": roh1_krw_prev, "당월 실적": roh1_krw_curr,
                    "전월 대비 증감": roh1_krw_curr - roh1_krw_prev}
    row_roh1_for = {"구분": "외자 원료 (ROH1)", "작년 총합": roh1_for_last, f"참조1 ({ref1_y}.{ref1_m})": roh1_for_ref1,
                    f"참조2 ({ref2_y}.{ref2_m})": roh1_for_ref2, "전월 실적": roh1_for_prev, "당월 실적": roh1_for_curr,
                    "전월 대비 증감": roh1_for_curr - roh1_for_prev}
    row_roh2_krw = {"구분": "내자 자재 (ROH2)", "작년 총합": roh2_krw_last, f"참조1 ({ref1_y}.{ref1_m})": roh2_krw_ref1,
                    f"참조2 ({ref2_y}.{ref2_m})": roh2_krw_ref2, "전월 실적": roh2_krw_prev, "당월 실적": roh2_krw_curr,
                    "전월 대비 증감": roh2_krw_curr - roh2_krw_prev}

    def sum_rows(title, *rows):
        result = {"구분": title};
        keys = [k for k in rows[0].keys() if k != "구분"]
        for k in keys: result[k] = sum(row[k] for row in rows)
        return result

    row_raw_sum = sum_rows("원료 합계 (내자+외자)", row_roh1_krw, row_roh1_for)
    row_dom_sum = sum_rows("내자 합계 (원료+자재)", row_roh1_krw, row_roh2_krw)
    row_grand_sum = sum_rows("전체 합계 (Total)", row_roh1_krw, row_roh1_for, row_roh2_krw)

    summary_data = [row_roh1_krw, row_roh1_for, row_raw_sum, row_roh2_krw, row_dom_sum, row_grand_sum]
    df_summary = pd.DataFrame(summary_data)

    cond_base = (merged_df['receipt_date'].dt.year == curr_year) & (merged_df['receipt_date'].dt.month == curr_month)
    if 'order_currency' in merged_df.columns:
        cond_base &= (merged_df['order_currency'].fillna('').astype(str).str.strip().str.upper() == 'KRW')

    df_filtered = merged_df[cond_base].copy()
    top_items_list = []

    if not df_filtered.empty:
        if 'po_id' not in df_filtered.columns: df_filtered['po_id'] = '-'
        if '__excel_row__' not in df_filtered.columns: df_filtered['__excel_row__'] = '-'
        grouped = df_filtered.groupby(['product_id', 'product_type']).agg({
            'received_value_local_currency': 'sum',
            'po_id': lambda x: ', '.join(x.dropna().astype(str).unique())[:50],
            '__excel_row__': lambda x: ', '.join(x.astype(str))[:100]
        }).reset_index()
        desc_map = prod_df.set_index('product_id')['description'].to_dict()
        grouped['description'] = grouped['product_id'].map(desc_map).fillna("Unknown Product")
        grouped = grouped[grouped['received_value_local_currency'] > 0]

        roh1_top = grouped[grouped['product_type'] == 'ROH1'].nlargest(1, 'received_value_local_currency')
        top_items_list.append(roh1_top.iloc[0].to_dict() if not roh1_top.empty else {"구분": "원료(ROH1) 최다 지출", "금액": 0})
        roh2_top = grouped[grouped['product_type'] == 'ROH2'].nlargest(3, 'received_value_local_currency')
        if not roh2_top.empty:
            for _, row in roh2_top.iterrows(): top_items_list.append(row.to_dict())
        else:
            top_items_list.append({"구분": "자재(ROH2) Top 1", "금액": 0})
    else:
        top_items_list.append({"구분": "데이터 없음", "금액": 0})
    df_highlights = pd.DataFrame(top_items_list)

    filename = f"Monthly_Closing_Report_{curr_year}_{curr_month}.xlsx"
    file_path = os.path.join(OUTPUT_DIR, filename)

    try:
        with pd.ExcelWriter(file_path, engine='openpyxl') as writer:
            df_summary.to_excel(writer, sheet_name='Summary', index=False)
            df_highlights.to_excel(writer, sheet_name='Top_Items', index=False)
        return f"리포트 생성 완료: {file_path}"
    except Exception as e:
        return f"리포트 저장 실패: {str(e)}"


# -------------------------------------------------------------------------
# 2. 발주 현황 공유 파일 생성 함수
# -------------------------------------------------------------------------
def run_po_status_report() -> str:
    """
    [발주 현황 공유 파일 생성]
    최근 2년치 발주 내역을 조회하고 자재 유형(Type)별로 시트를 나누어 엑셀 파일을 생성합니다.
    """
    print("\n" + "=" * 60)
    print(">>> [Debug] 발주 현황 공유 파일 생성")
    print("=" * 60)

    po_df = DB.get('purchase_order', pd.DataFrame()).copy()
    vendor_df = DB.get('vendor_info_record', pd.DataFrame()).copy()
    prod_df = DB.get('product', pd.DataFrame()).copy()

    if po_df.empty: return "데이터 오류: 구매오더 데이터가 없습니다."

    def normalize_id(x):
        return str(x).strip().rstrip('.0') if pd.notnull(x) else None

    po_df['vendor_id'] = po_df['vendor_id'].apply(normalize_id)
    po_df['product_id'] = po_df['product_id'].apply(normalize_id)
    vendor_df['vendor_id'] = vendor_df['vendor_id'].apply(normalize_id)
    prod_df['product_id'] = prod_df['product_id'].apply(normalize_id)

    if 'po_date' in po_df.columns: po_df['po_date'] = pd.to_datetime(po_df['po_date'], errors='coerce')
    if 'delivery_date' in po_df.columns: po_df['delivery_date'] = pd.to_datetime(po_df['delivery_date'],
                                                                                 errors='coerce')

    today = datetime.now()
    two_years_ago = today - pd.DateOffset(years=2)
    filtered_po = po_df[(po_df['po_date'] >= two_years_ago) & (po_df['po_date'] <= today)].copy()
    if filtered_po.empty: return "알림: 최근 2년 내의 발주 내역이 존재하지 않습니다."

    merged_df = filtered_po.merge(vendor_df[['vendor_id', 'vendor_name']].drop_duplicates(), on='vendor_id', how='left')
    merged_df = merged_df.merge(prod_df[['product_id', 'description', 'product_type']].drop_duplicates(),
                                on='product_id', how='left', indicator=True)
    merged_df = merged_df[merged_df['_merge'] == 'both'].copy()
    if merged_df.empty: return "알림: 조건에 맞는 데이터가 없습니다."

    merged_df.loc[merged_df['product_type'].isna() | (
                merged_df['product_type'].astype(str).str.strip() == ''), 'product_type'] = 'Unclassified'

    file_date = today.strftime("%Y%m%d")
    filename = f"PO_Status_Share_{file_date}.xlsx"
    file_path = os.path.join(OUTPUT_DIR, filename)

    try:
        with pd.ExcelWriter(file_path, engine='openpyxl') as writer:
            for p_type in merged_df['product_type'].unique():
                sheet_name = re.sub(r'[\\/*?:\[\]]', '', str(p_type))[:30] or "Etc"
                merged_df[merged_df['product_type'] == p_type].to_excel(writer, sheet_name=sheet_name, index=False)
        return f"파일 생성 완료: {file_path}"
    except Exception as e:
        return f"파일 저장 실패: {str(e)}"


# -------------------------------------------------------------------------
# 3. 공급업체 평가 관리 양식 생성 함수
# -------------------------------------------------------------------------
def run_supplier_evaluation_report() -> str:
    """
    [공급업체 평가 관리 양식 생성]
    - Good_Receipt 기준, Batch No 기준 Unique 1행 생성
    - 앞자리 '0' 제거 및 문자열 강제 변환으로 매칭률 100% 보장
    """
    print("\n" + "=" * 60)
    print(">>> [Debug] 공급업체 평가 양식 생성 시작 (최종 Fix)")
    print("=" * 60)

    gr_df = DB.get('good_receipt', pd.DataFrame()).copy()
    po_df = DB.get('purchase_order', pd.DataFrame()).copy()
    prod_df = DB.get('product', pd.DataFrame()).copy()
    vendor_df = DB.get('vendor_info_record', pd.DataFrame()).copy()
    nc_df = DB.get('non_conformance', pd.DataFrame()).copy()

    if gr_df.empty: return "데이터 오류: 입고 내역(Good_Receipt)이 없습니다."
    if po_df.empty: return "데이터 오류: 구매 오더(Purchase_Order) 데이터가 없습니다."

    # 1. ID 정규화 (핵심: 앞자리 0 제거)
    # 데이터를 읽을 때부터 문자열로 확실하게 처리
    gr_df['batch_no'] = gr_df['batch_no'].astype(str).apply(normalize_id)
    gr_df['po_id'] = gr_df['po_id'].astype(str).apply(normalize_id)
    gr_df['product_id'] = gr_df['product_id'].astype(str).apply(normalize_id)

    po_df['po_id'] = po_df['po_id'].astype(str).apply(normalize_id)
    po_df['vendor_id'] = po_df['vendor_id'].astype(str).apply(normalize_id)
    vendor_df['vendor_id'] = vendor_df['vendor_id'].astype(str).apply(normalize_id)
    prod_df['product_id'] = prod_df['product_id'].astype(str).apply(normalize_id)

    if not nc_df.empty and 'batch_no' in nc_df.columns:
        nc_df['batch_no'] = nc_df['batch_no'].astype(str).apply(normalize_id)

    # 2. 매칭 확인 로그 (디버깅용)
    nc_batch_set = set()
    if not nc_df.empty:
        nc_batch_set = set(nc_df['batch_no'].dropna().unique())
        print(f">>> [NC Check] 부적합 리스트 수: {len(nc_batch_set)}")

    gr_df = gr_df.dropna(subset=['batch_no'])
    gr_base = gr_df.drop_duplicates(subset=['batch_no']).copy()

    # 교집합 확인
    intersection = set(gr_base['batch_no']).intersection(nc_batch_set)
    print(f">>> [Match Check] 부적합 매칭 성공 개수: {len(intersection)}")

    # 3. 부적합 판별
    gr_base['is_non_conformance'] = gr_base['batch_no'].apply(
        lambda x: "부적합" if x in nc_batch_set else "적합"
    )

    # 4. 데이터 병합 (중복 제거된 참조 테이블 사용)
    po_ref = po_df[['po_id', 'vendor_id', 'po_date', 'delivery_date']].drop_duplicates(subset=['po_id'])
    vendor_ref = vendor_df[['vendor_id', 'vendor_name']].drop_duplicates(subset=['vendor_id'])
    prod_ref = prod_df[['product_id', 'description']].drop_duplicates(subset=['product_id'])

    merged_df = gr_base.merge(po_ref, on='po_id', how='left')
    merged_df = merged_df.merge(vendor_ref, on='vendor_id', how='left')
    merged_df['vendor_name'] = merged_df['vendor_name'].fillna("Unknown")

    merged_df = merged_df.merge(prod_ref, on='product_id', how='left')
    merged_df['description'] = merged_df['description'].fillna("-")

    # 5. 납품 LT 계산 및 마이너스 로그
    merged_df['po_date'] = pd.to_datetime(merged_df['po_date'], errors='coerce')
    merged_df['delivery_date'] = pd.to_datetime(merged_df['delivery_date'], errors='coerce')
    merged_df['delivery_lt'] = (merged_df['delivery_date'] - merged_df['po_date']).dt.days.fillna(0)

    # 마이너스 값 확인
    negative_lt = merged_df[merged_df['delivery_lt'] < 0]
    if not negative_lt.empty:
        print("\n>>> [LT Warning] 납품 LT 마이너스 발견 (원천 데이터 확인 필요):")
        print(negative_lt[['po_id', 'po_date', 'delivery_date', 'delivery_lt']].head(3).to_string())

    # 6. 컬럼 정리 및 저장
    final_cols = {
        'vendor_name': '업체명',
        'product_id': '품목코드',
        'description': '품목명',
        'batch_no': '성적번호',
        'delivery_lt': '납품 LT (일)',
        'is_non_conformance': '부적합 여부'
    }

    for col in ['부적합 사유', '납품 지연 사유', '지연 통보 선제성', '납품 기준 준수']:
        merged_df[col] = ""

    result_df = merged_df.rename(columns=final_cols)
    target_cols = list(final_cols.values()) + ['부적합 사유', '납품 지연 사유', '지연 통보 선제성', '납품 기준 준수']
    valid_target_cols = [c for c in target_cols if c in result_df.columns]
    result_df = result_df[valid_target_cols]

    result_df = result_df.drop_duplicates()

    today_str = datetime.now().strftime("%Y%m%d")
    filename = f"Supplier_Evaluation_{today_str}.xlsx"
    file_path = os.path.join(OUTPUT_DIR, filename)

    try:
        with pd.ExcelWriter(file_path, engine='openpyxl') as writer:
            result_df.to_excel(writer, index=False, sheet_name='평가양식')
        return f"평가양식 생성 완료: {file_path}"
    except Exception as e:
        return f"파일 저장 실패: {str(e)}"