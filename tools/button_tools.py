import pandas as pd
import os
import re
import numpy as np
from datetime import datetime
from .shared import DB, OUTPUT_DIR

# -------------------------------------------------------------------------
# UI 이벤트용 함수 (버튼 클릭 시 직접 호출)
# -------------------------------------------------------------------------

def run_monthly_closing_process() -> str:
    """
    [월말 구매마감 리포트 생성 프로세스]
    - 원본 데이터 기반 정밀 매칭
    - 날짜 포맷 변환 로직 추가 (Fix: AttributeError 해결)
    """
    print("\n" + "=" * 60)
    print(">>> [Debug] 월말 마감 리포트 프로세스 시작 (날짜 변환 적용)")
    print("=" * 60)

    # 1. 데이터 로드
    txn_df = DB.get('purchase_transaction_history', pd.DataFrame()).copy()
    prod_df = DB.get('product', pd.DataFrame()).copy()

    if txn_df.empty: return "데이터 오류: 구매 상세 내역이 비어있습니다."
    if prod_df.empty: return "데이터 오류: 자재 마스터 데이터가 비어있습니다."

    # =========================================================================
    # [핵심 수정] 날짜 컬럼 타입 변환 (String -> Datetime)
    # =========================================================================
    # 데이터베이스 컬럼명이 'receipt_date'인지 확인
    date_col_name = 'receipt_date'

    if date_col_name in txn_df.columns:
        txn_df[date_col_name] = pd.to_datetime(txn_df[date_col_name], errors='coerce')
    else:
        print(f">>> [Warning] '{date_col_name}' 컬럼이 데이터에 없습니다. 날짜 집계 시 에러가 발생할 수 있습니다.")

    # -------------------------------------------------------------------------
    # 2. 이동유형(Movement Type) 필터링
    # -------------------------------------------------------------------------
    if 'movement_type' in txn_df.columns:
        txn_df['movement_type'] = txn_df['movement_type'].apply(
            lambda x: str(x).strip().replace('.0', '') if pd.notnull(x) else None
        )
        target_types = ['101', '102']
        txn_df = txn_df[txn_df['movement_type'].isin(target_types)].copy()

        if txn_df.empty: return "데이터 오류: 이동유형 101/102 데이터가 없습니다."

    # -------------------------------------------------------------------------
    # 3. 데이터 전처리 (ID 정규화)
    # -------------------------------------------------------------------------
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

    # -------------------------------------------------------------------------
    # 4. 금액 변환 및 취소(102) 반영
    # -------------------------------------------------------------------------
    target_col = 'received_value_local_currency'
    if target_col in txn_df.columns:
        if 'movement_type' in txn_df.columns:
            mask_cancel = txn_df['movement_type'] == '102'
            # 숫자로 확실히 변환 (안전을 위해 추가)
            txn_df[target_col] = pd.to_numeric(txn_df[target_col], errors='coerce').fillna(0)
            txn_df.loc[mask_cancel, target_col] = -np.abs(txn_df.loc[mask_cancel, target_col])
    else:
        txn_df[target_col] = 0

    # -------------------------------------------------------------------------
    # 5. 데이터 병합
    # -------------------------------------------------------------------------
    merged_df = txn_df.merge(
        prod_df[['product_id', 'product_type', 'description']],
        on='product_id',
        how='left',
        indicator=True
    )

    merged_df['product_type'] = merged_df['product_type'].astype(str).str.strip().str.upper()
    merged_df.loc[merged_df['product_type'].isin(['NAN', 'NONE', '']), 'product_type'] = 'UNCLASSIFIED'

    # -------------------------------------------------------------------------
    # 6. 집계 로직 (날짜 기반)
    # -------------------------------------------------------------------------
    valid_dates = merged_df['receipt_date'].dropna()

    if not valid_dates.empty:
        max_date = valid_dates.max()
        curr_year, curr_month = max_date.year, max_date.month
    else:
        today = datetime.now()
        curr_year, curr_month = today.year, today.month

    print(f">>> [Setting] 리포트 기준월: {curr_year}년 {curr_month}월")

    # 기준 날짜 계산
    if curr_month == 1:
        prev_month_date = datetime(curr_year - 1, 12, 1)
        ref1_y, ref1_m = curr_year - 1, 6
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
            cond &= (merged_df['receipt_date'].dt.year == target_year) & \
                    (merged_df['receipt_date'].dt.month == target_month)
        else:
            cond &= (merged_df['receipt_date'].dt.year == target_year)

        if 'order_currency' in merged_df.columns:
            curr_series = merged_df['order_currency'].fillna('').astype(str).str.strip().str.upper()
            if currency_condition == 'KRW':
                cond &= (curr_series == 'KRW')
            elif currency_condition == 'NON-KRW':
                cond &= (curr_series != 'KRW')

        return float(merged_df.loc[cond, 'received_value_local_currency'].sum())

    # --- 지표 계산 ---
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

    # 보고서 데이터 구성
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
        result = {"구분": title}
        keys = [k for k in rows[0].keys() if k != "구분"]
        for k in keys:
            result[k] = sum(row[k] for row in rows)
        return result

    row_raw_sum = sum_rows("원료 합계 (내자+외자)", row_roh1_krw, row_roh1_for)
    row_dom_sum = sum_rows("내자 합계 (원료+자재)", row_roh1_krw, row_roh2_krw)
    row_grand_sum = sum_rows("전체 합계 (Total)", row_roh1_krw, row_roh1_for, row_roh2_krw)

    summary_data = [row_roh1_krw, row_roh1_for, row_raw_sum, row_roh2_krw, row_dom_sum, row_grand_sum]
    df_summary = pd.DataFrame(summary_data)

    # 7. Highlights (Top Items)
    cond_base = (merged_df['receipt_date'].dt.year == curr_year) & \
                (merged_df['receipt_date'].dt.month == curr_month)

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
        if not roh1_top.empty:
            row = roh1_top.iloc[0]
            top_items_list.append({
                "구분": "원료(ROH1) 최다 지출",
                "자재코드": row['product_id'], "자재명": row['description'],
                "금액": row['received_value_local_currency'], "관련 PO": row['po_id'], "엑셀 행": row['__excel_row__']
            })
        else:
            top_items_list.append({"구분": "원료(ROH1) 최다 지출", "자재코드": "-", "자재명": "-", "금액": 0})

        roh2_top = grouped[grouped['product_type'] == 'ROH2'].nlargest(3, 'received_value_local_currency')
        if not roh2_top.empty:
            rank = 1
            for _, row in roh2_top.iterrows():
                top_items_list.append({
                    "구분": f"자재(ROH2) Top {rank}",
                    "자재코드": row['product_id'], "자재명": row['description'],
                    "금액": row['received_value_local_currency'], "관련 PO": row['po_id'], "엑셀 행": row['__excel_row__']
                })
                rank += 1
        else:
            top_items_list.append({"구분": "자재(ROH2) Top 1", "자재코드": "-", "자재명": "-", "금액": 0})
    else:
        top_items_list.append({"구분": "원료(ROH1) 최다 지출", "자재코드": "-", "자재명": "-", "금액": 0})
        top_items_list.append({"구분": "자재(ROH2) Top 1", "자재코드": "-", "자재명": "-", "금액": 0})

    df_highlights = pd.DataFrame(top_items_list)

    # Missing Log
    failed_match = merged_df[merged_df['_merge'] == 'left_only']
    df_missing = pd.DataFrame()
    if not failed_match.empty:
        df_missing = pd.DataFrame(failed_match['product_id'].unique(), columns=['Missing_Product_ID'])

    filename = f"Monthly_Closing_Report_{curr_year}_{curr_month}.xlsx"
    file_path = os.path.join(OUTPUT_DIR, filename)

    try:
        with pd.ExcelWriter(file_path, engine='openpyxl') as writer:
            df_summary.to_excel(writer, sheet_name='Summary', index=False)
            df_highlights.to_excel(writer, sheet_name='Top_Items', index=False)
            if not df_missing.empty:
                df_missing.to_excel(writer, sheet_name='Error_Log', index=False)

        msg = f"리포트 생성 완료: {file_path}"
        if unclassified_curr > 0:
            msg += f"\n⚠️ [참고] 미분류 금액 {unclassified_curr:,.0f}원은 합계에서 제외되었습니다. Error_Log를 확인하세요."
        return msg

    except Exception as e:
        return f"리포트 저장 실패: {str(e)}"

def run_po_status_report() -> str:
    """
    [발주 현황 공유 파일 생성] - Final Filtering Ver.
    - 목적: 최근 2년 내 발주 내역을 자재 유형별로 시트를 나누어 엑셀로 추출
    - 변경사항: 자재 마스터(Product)에 없는 자재는 결과 파일에서 '제외'합니다.
    """
    print("\n" + "=" * 60)
    print(">>> [Debug] 발주 현황 공유 파일 생성 (No Master 제외 모드)")
    print("=" * 60)

    # 1. 데이터 로드
    po_df = DB.get('purchase_order', pd.DataFrame()).copy()
    vendor_df = DB.get('vendor_info_record', pd.DataFrame()).copy()
    prod_df = DB.get('product', pd.DataFrame()).copy()

    if po_df.empty: return "데이터 오류: 구매오더(Purchase_Order) 데이터가 없습니다."
    if vendor_df.empty: return "데이터 오류: 공급업체(Vendor) 마스터 데이터가 없습니다."
    if prod_df.empty: return "데이터 오류: 자재(Product) 마스터 데이터가 없습니다."

    # 2. 데이터 전처리 (ID 정규화 및 날짜 변환)
    def normalize_id(x):
        if pd.isna(x): return None
        s = str(x).strip()
        if s.lower() == 'nan': return None
        if s.endswith('.0'): s = s[:-2]
        return s

    po_df['vendor_id'] = po_df['vendor_id'].apply(normalize_id)
    po_df['product_id'] = po_df['product_id'].apply(normalize_id)
    vendor_df['vendor_id'] = vendor_df['vendor_id'].apply(normalize_id)
    prod_df['product_id'] = prod_df['product_id'].apply(normalize_id)

    if 'po_date' in po_df.columns:
        po_df['po_date'] = pd.to_datetime(po_df['po_date'], errors='coerce')
    if 'delivery_date' in po_df.columns:
        po_df['delivery_date'] = pd.to_datetime(po_df['delivery_date'], errors='coerce')

    # 3. 날짜 필터링 (오늘 기준 2년 이내)
    today = datetime.now()
    two_years_ago = today - pd.DateOffset(years=2)

    mask_date = (po_df['po_date'] >= two_years_ago) & (po_df['po_date'] <= today)
    filtered_po = po_df[mask_date].copy()

    if filtered_po.empty:
        return "알림: 최근 2년 내의 발주 내역이 존재하지 않습니다."

    # 4. 데이터 병합
    vendor_master = vendor_df[['vendor_id', 'vendor_name']].drop_duplicates(subset=['vendor_id'])
    merged_df = filtered_po.merge(vendor_master, on='vendor_id', how='left')

    prod_master = prod_df[['product_id', 'description', 'product_type']].drop_duplicates(subset=['product_id'])
    merged_df = merged_df.merge(prod_master, on='product_id', how='left', indicator=True)

    # 5. No Master 데이터 제외 처리
    logs = []
    missing_mask = merged_df['_merge'] == 'left_only'
    missing_count = missing_mask.sum()

    if missing_count > 0:
        dropped_ids = merged_df.loc[missing_mask, 'product_id'].unique()[:5]
        logs.append(f"ℹ️ [알림] 마스터 미등록 자재 {missing_count}건이 결과에서 제외되었습니다.")
        merged_df = merged_df[merged_df['_merge'] == 'both'].copy()

    if merged_df.empty:
        return "알림: 조건에 맞는 데이터가 없습니다."

    # 6. 유형 누락(Unclassified) 처리
    cond_empty_type = (merged_df['product_type'].isna() | (merged_df['product_type'].astype(str).str.strip() == ''))
    if cond_empty_type.sum() > 0:
        missing_type_cnt = cond_empty_type.sum()
        logs.append(f"⚠️ [주의] 유형(Type) 누락 자재 {missing_type_cnt}건은 'Unclassified' 시트에 저장되었습니다.")
        merged_df.loc[cond_empty_type, 'product_type'] = 'Unclassified'

    # 7. 컬럼 정리 및 엑셀 생성
    target_columns = [
        'product_id', 'description', 'product_type', 'schedule_qty',
        'received_qty', 'po_date', 'delivery_date', 'vendor_id', 'vendor_name'
    ]
    final_cols = [c for c in target_columns if c in merged_df.columns]
    final_df = merged_df[final_cols].copy()

    for date_col in ['po_date', 'delivery_date']:
        if date_col in final_df.columns:
            final_df[date_col] = final_df[date_col].dt.strftime('%Y-%m-%d')

    file_date = today.strftime("%Y%m%d")
    filename = f"PO_Status_Share_{file_date}.xlsx"
    file_path = os.path.join(OUTPUT_DIR, filename)

    try:
        with pd.ExcelWriter(file_path, engine='openpyxl') as writer:
            unique_types = final_df['product_type'].unique()
            for p_type in unique_types:
                sheet_name = str(p_type)
                sheet_name = re.sub(r'[\\/*?:\[\]]', '', sheet_name)[:30]
                if not sheet_name.strip(): sheet_name = "Etc"
                sheet_data = final_df[final_df['product_type'] == p_type]
                sheet_data.to_excel(writer, sheet_name=sheet_name, index=False)

        success_msg = f"파일 생성 완료: {file_path}"
        if logs:
            return success_msg + "\n\n" + "\n".join(logs)
        else:
            return success_msg

    except Exception as e:
        return f"파일 저장 실패: {str(e)}"