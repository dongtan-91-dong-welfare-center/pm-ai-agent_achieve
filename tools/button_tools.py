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
    - 원본 데이터 기반 정밀 매칭 (근사치 복구 금지)
    - 101(입고)/102(취소) 필터링 및 취소분 차감
    """
    print("\n" + "=" * 60)
    print(">>> [Debug] 월말 마감 리포트 프로세스 시작 (원본 데이터 매칭 모드)")
    print("=" * 60)

    # 1. 데이터 로드
    txn_df = DB.get('purchase_transaction_history', pd.DataFrame()).copy()
    prod_df = DB.get('product', pd.DataFrame()).copy()

    if txn_df.empty: return "데이터 오류: 구매 상세 내역이 비어있습니다."
    if prod_df.empty: return "데이터 오류: 자재 마스터 데이터가 비어있습니다."

    # -------------------------------------------------------------------------
    # 2. 이동유형(Movement Type) 필터링
    # -------------------------------------------------------------------------
    if 'movement_type' in txn_df.columns:
        # shared.py에서 이미 문자열로 로드됨. 소수점 제거(.0)만 확인
        txn_df['movement_type'] = txn_df['movement_type'].apply(
            lambda x: str(x).strip().replace('.0', '') if pd.notnull(x) else None
        )

        target_types = ['101', '102']
        txn_df = txn_df[txn_df['movement_type'].isin(target_types)].copy()

        if txn_df.empty: return "데이터 오류: 이동유형 101/102 데이터가 없습니다."
    else:
        print(">>> [Warning] 'movement_type' 컬럼 없음. 전체 집계.")

    # -------------------------------------------------------------------------
    # 3. 데이터 전처리 (단순 정규화)
    # -------------------------------------------------------------------------
    # [중요] 근사치 추정 로직 제거됨. 오직 원본 ID의 공백/포맷만 정리.

    def normalize_id_strict(x):
        if pd.isna(x): return None
        s = str(x).strip()
        if s.lower() == 'nan': return None
        if s.endswith('.0'): s = s[:-2]  # 실수형 문자열 보정
        # 앞자리 0 제거가 필요한 경우 (SAP 표준) - 필요 없다면 이 줄 주석 처리
        s = s.lstrip('0')
        if not s: return None
        return s

    txn_df['product_id'] = txn_df['product_id'].apply(normalize_id_strict)
    prod_df['product_id'] = prod_df['product_id'].apply(normalize_id_strict)

    txn_df = txn_df.dropna(subset=['product_id'])
    prod_df = prod_df.dropna(subset=['product_id'])
    prod_df = prod_df.drop_duplicates(subset=['product_id'], keep='first')

    # [Debug] ID 샘플 확인
    print(f">>> [Check] Txn ID Sample: {txn_df['product_id'].head(3).tolist()}")
    print(f">>> [Check] Prod ID Sample: {prod_df['product_id'].head(3).tolist()}")

    # -------------------------------------------------------------------------
    # 4. 금액 변환 및 취소(102) 반영
    # -------------------------------------------------------------------------
    target_col = 'received_value_local_currency'
    # shared.py에서 이미 숫자로 변환됨
    if target_col in txn_df.columns:
        if 'movement_type' in txn_df.columns:
            mask_cancel = txn_df['movement_type'] == '102'
            txn_df.loc[mask_cancel, target_col] = -np.abs(txn_df.loc[mask_cancel, target_col])
    else:
        txn_df[target_col] = 0

    print(f">>> [Debug] 집계 대상 금액 총합: {txn_df[target_col].sum():,.0f}")

    # -------------------------------------------------------------------------
    # 5. 데이터 병합
    # -------------------------------------------------------------------------
    merged_df = txn_df.merge(
        prod_df[['product_id', 'product_type', 'description']],
        on='product_id',
        how='left',
        indicator=True
    )

    # 매칭 실패 확인 (Strict Mode)
    failed_match = merged_df[merged_df['_merge'] == 'left_only']
    if not failed_match.empty:
        print(f">>> [Critical] 매칭 실패 ID ({len(failed_match)}건): {failed_match['product_id'].unique()[:5]}")
        print(">>> [Info] 근사치 복구를 수행하지 않았으므로, 위 ID는 원본 파일 간 불일치입니다.")
    else:
        print(">>> [Success] 모든 ID가 정상 매칭되었습니다.")

    merged_df['product_type'] = merged_df['product_type'].astype(str).str.strip().str.upper()
    merged_df.loc[merged_df['product_type'].isin(['NAN', 'NONE', '']), 'product_type'] = 'UNCLASSIFIED'

    # -------------------------------------------------------------------------
    # 6. 집계 로직
    # -------------------------------------------------------------------------
    # 기준월 설정: 데이터 상의 Max Date 기준
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

    # 보고서 데이터
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