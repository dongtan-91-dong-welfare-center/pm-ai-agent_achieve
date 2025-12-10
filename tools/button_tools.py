import pandas as pd
import os
import re
from datetime import datetime
from .shared import DB, OUTPUT_DIR


# -------------------------------------------------------------------------
# UI 이벤트용 함수 (버튼 클릭 시 직접 호출)
# -------------------------------------------------------------------------

def run_monthly_closing_process() -> str:
    """
    [월말 구매마감 리포트 생성 프로세스]
    - 데이터 재로딩 기능 제거 (기존 DB 사용)
    - ID 정규화 및 전체 데이터 전수 검사 로그 추가
    """
    print("\n" + "=" * 60)
    print(">>> [Debug] 월말 마감 리포트 프로세스 시작")
    print("=" * 60)

    # 1. 데이터 로드 (캐싱된 DB 사용)
    txn_df = DB.get('purchase_transaction_history', pd.DataFrame()).copy()
    prod_df = DB.get('product', pd.DataFrame()).copy()

    if txn_df.empty:
        return "데이터 오류: 구매 상세 내역이 비어있습니다."
    if prod_df.empty:
        return "데이터 오류: 자재 마스터 데이터가 비어있습니다."

    print(f">>> [Debug] 로드된 데이터 건수: 구매내역 {len(txn_df)}건, 자재마스터 {len(prod_df)}건")

    # -------------------------------------------------------------------------
    # 2. 데이터 전처리
    # -------------------------------------------------------------------------

    # (1) ID 정규화 함수 (강력한 공백/0 제거)
    def normalize_id(x):
        if pd.isna(x): return None
        s = str(x).strip()  # 앞뒤 공백 제거
        if s.lower() == 'nan': return None
        if s.endswith('.0'): s = s[:-2]  # 소수점 제거
        s = s.lstrip('0')  # 앞쪽 0 제거
        if not s: return None
        return s

    # ID 정규화 적용
    txn_df['product_id'] = txn_df['product_id'].apply(normalize_id)
    prod_df['product_id'] = prod_df['product_id'].apply(normalize_id)

    # 유효하지 않은 ID 제거
    txn_df = txn_df.dropna(subset=['product_id'])
    prod_df = prod_df.dropna(subset=['product_id'])

    # [중요] 전체 ID 로그 출력 (데이터가 적으므로 전수 확인)
    txn_ids = sorted(txn_df['product_id'].unique())
    prod_ids = sorted(prod_df['product_id'].unique())

    print(f"\n>>> [Check] 구매내역 ID 목록 ({len(txn_ids)}개): {txn_ids}")
    # print(f">>> [Check] 자재마스터 ID 목록 ({len(prod_ids)}개): {prod_ids}") # 필요시 주석 해제

    # (2) 날짜 변환
    if 'receipt_date' in txn_df.columns:
        txn_df['receipt_date'] = pd.to_datetime(txn_df['receipt_date'], errors='coerce')

    # (3) 금액 컬럼 숫자 변환
    target_col = 'received_value_local_currency'
    if target_col in txn_df.columns:
        txn_df[target_col] = (
            txn_df[target_col].astype(str).str.replace(',', '', regex=False)
        )
        txn_df[target_col] = pd.to_numeric(txn_df[target_col], errors='coerce').fillna(0)
    else:
        txn_df[target_col] = 0

    print(f">>> [Debug] 금액 변환 완료. 총합: {txn_df[target_col].sum():,.0f}")

    # -------------------------------------------------------------------------
    # 3. 데이터 병합 및 매칭 검증
    # -------------------------------------------------------------------------

    # indicator=True를 사용하여 매칭 결과를 명확히 확인
    merged_df = txn_df.merge(
        prod_df[['product_id', 'product_type', 'description']],
        on='product_id',
        how='left',
        indicator=True
    )

    # 매칭 실패(Left Only) 확인
    failed_match = merged_df[merged_df['_merge'] == 'left_only']
    if not failed_match.empty:
        failed_ids = failed_match['product_id'].unique()
        print(f"\n>>> [Critical] 매칭 실패 ID 목록 ({len(failed_ids)}개): {failed_ids}")
        print(">>> [Tip] 위 ID들이 자재 마스터에 정확히 존재하는지 확인해주세요.")
    else:
        print("\n>>> [Success] 모든 구매 내역 ID가 자재 마스터와 정상 매칭되었습니다.")

    # 자재 유형 정제
    merged_df['product_type'] = merged_df['product_type'].astype(str).str.strip().str.upper()
    merged_df.loc[merged_df['product_type'].isin(['NAN', 'NONE', '']), 'product_type'] = 'UNCLASSIFIED'

    # [Debug] 자재 유형별 분포
    print(f">>> [Debug] 자재 유형 분포:\n{merged_df['product_type'].value_counts()}")

    # -------------------------------------------------------------------------
    # 4. 날짜 및 참조 시점 계산
    # -------------------------------------------------------------------------
    today = datetime.now()
    curr_year, curr_month = today.year, today.month

    print(f">>> [Debug] 리포트 기준: {curr_year}년 {curr_month}월")

    # 전월
    if curr_month == 1:
        prev_month_date = datetime(curr_year - 1, 12, 1)
    else:
        prev_month_date = datetime(curr_year, curr_month - 1, 1)
    prev_month_y, prev_month_m = prev_month_date.year, prev_month_date.month

    # 동적 비교 시점
    if curr_month == 1:
        ref1_y, ref1_m = curr_year - 1, 6
        ref2_y, ref2_m = curr_year - 1, 9
    elif 1 < curr_month <= 3:
        ref1_y, ref1_m = curr_year - 1, 9
        ref2_y, ref2_m = curr_year - 1, 12
    elif 3 < curr_month <= 6:
        ref1_y, ref1_m = curr_year - 1, 12
        ref2_y, ref2_m = curr_year, 3
    elif 6 < curr_month <= 9:
        ref1_y, ref1_m = curr_year, 3
        ref2_y, ref2_m = curr_year, 6
    else:
        ref1_y, ref1_m = curr_year, 6
        ref2_y, ref2_m = curr_year, 9

    # -------------------------------------------------------------------------
    # 5. 집계 로직
    # -------------------------------------------------------------------------

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

    # 상세 계산
    roh1_krw_curr = calculate_sum(curr_year, curr_month, 'ROH1', 'KRW')
    roh1_krw_prev = calculate_sum(prev_month_y, prev_month_m, 'ROH1', 'KRW')
    roh1_krw_diff = roh1_krw_curr - roh1_krw_prev

    roh1_krw_last = calculate_sum(curr_year - 1, 0, 'ROH1', 'KRW')
    roh1_krw_ref1 = calculate_sum(ref1_y, ref1_m, 'ROH1', 'KRW')
    roh1_krw_ref2 = calculate_sum(ref2_y, ref2_m, 'ROH1', 'KRW')

    roh1_for_curr = calculate_sum(curr_year, curr_month, 'ROH1', 'NON-KRW')
    roh1_for_prev = calculate_sum(prev_month_y, prev_month_m, 'ROH1', 'NON-KRW')
    roh1_for_diff = roh1_for_curr - roh1_for_prev
    roh1_for_last = calculate_sum(curr_year - 1, 0, 'ROH1', 'NON-KRW')
    roh1_for_ref1 = calculate_sum(ref1_y, ref1_m, 'ROH1', 'NON-KRW')
    roh1_for_ref2 = calculate_sum(ref2_y, ref2_m, 'ROH1', 'NON-KRW')

    roh2_krw_curr = calculate_sum(curr_year, curr_month, 'ROH2', 'KRW')
    roh2_krw_prev = calculate_sum(prev_month_y, prev_month_m, 'ROH2', 'KRW')
    roh2_krw_diff = roh2_krw_curr - roh2_krw_prev
    roh2_krw_last = calculate_sum(curr_year - 1, 0, 'ROH2', 'KRW')
    roh2_krw_ref1 = calculate_sum(ref1_y, ref1_m, 'ROH2', 'KRW')
    roh2_krw_ref2 = calculate_sum(ref2_y, ref2_m, 'ROH2', 'KRW')

    total_raw = roh1_krw_curr + roh1_for_curr
    total_domestic = roh1_krw_curr + roh2_krw_curr
    grand_total = total_raw + roh2_krw_curr

    # 미분류 확인
    unclassified_curr = calculate_sum(curr_year, curr_month, 'UNCLASSIFIED', 'ALL')

    print(f">>> [Debug] 최종 결과: ROH1내자={roh1_krw_curr:,.0f}, ROH2내자={roh2_krw_curr:,.0f}, 총합={grand_total:,.0f}")

    # 6. 보고서 데이터 생성
    summary_data = [
        {"구분": "내자 원료 (ROH1)", "작년 총합": roh1_krw_last, f"참조1 ({ref1_y}.{ref1_m})": roh1_krw_ref1,
         f"참조2 ({ref2_y}.{ref2_m})": roh1_krw_ref2, "전월 실적": roh1_krw_prev, "당월 실적": roh1_krw_curr,
         "전월 대비 증감": roh1_krw_diff},
        {"구분": "외자 원료 (ROH1)", "작년 총합": roh1_for_last, f"참조1 ({ref1_y}.{ref1_m})": roh1_for_ref1,
         f"참조2 ({ref2_y}.{ref2_m})": roh1_for_ref2, "전월 실적": roh1_for_prev, "당월 실적": roh1_for_curr,
         "전월 대비 증감": roh1_for_diff},
        {"구분": "내자 자재 (ROH2)", "작년 총합": roh2_krw_last, f"참조1 ({ref1_y}.{ref1_m})": roh2_krw_ref1,
         f"참조2 ({ref2_y}.{ref2_m})": roh2_krw_ref2, "전월 실적": roh2_krw_prev, "당월 실적": roh2_krw_curr,
         "전월 대비 증감": roh2_krw_diff}
    ]
    df_summary = pd.DataFrame(summary_data)

    agg_data = [
        {"항목": "원료 합계 (내자+외자)", "당월 금액": total_raw},
        {"항목": "내자 합계 (원료+자재)", "당월 금액": total_domestic},
        {"항목": "총 매입 합계", "당월 금액": grand_total},
        {"항목": "⚠️ 미분류(매칭실패)", "당월 금액": unclassified_curr}
    ]
    df_agg = pd.DataFrame(agg_data)

    # Highlights
    top_cond = (merged_df['product_type'] == 'ROH2') & \
               (merged_df['receipt_date'].dt.year == curr_year) & \
               (merged_df['receipt_date'].dt.month == curr_month)
    if 'order_currency' in merged_df.columns:
        top_cond &= (merged_df['order_currency'].fillna('').astype(str).str.strip().str.upper() == 'KRW')

    target_items = merged_df[top_cond]

    if not target_items.empty:
        max_idx = target_items['received_value_local_currency'].idxmax()
        max_row = target_items.loc[max_idx]
        max_item_info = {"구분": "최대 지출 품목", "자재코드": max_row['product_id'], "자재명": max_row['description'],
                         "금액": max_row['received_value_local_currency']}
        top3_list = []
        rank = 1
        for _, row in target_items.nlargest(3, 'received_value_local_currency').iterrows():
            top3_list.append({"구분": f"Top {rank}", "자재코드": row['product_id'], "자재명": row['description'],
                              "금액": row['received_value_local_currency']})
            rank += 1
    else:
        max_item_info = {"구분": "최대 지출 품목", "자재코드": "-", "자재명": "-", "금액": 0}
        top3_list = []

    highlights_data = [max_item_info] + top3_list
    df_highlights = pd.DataFrame(highlights_data)

    # Missing ID Report
    failed_match = merged_df[merged_df['_merge'] == 'left_only']
    df_missing = pd.DataFrame(failed_match['product_id'].unique(), columns=['Missing_Product_ID'])

    # 파일 저장
    filename = f"Monthly_Closing_Report_{curr_year}_{curr_month}.xlsx"
    file_path = os.path.join(OUTPUT_DIR, filename)

    try:
        with pd.ExcelWriter(file_path, engine='openpyxl') as writer:
            df_summary.to_excel(writer, sheet_name='Summary', index=False)
            df_agg.to_excel(writer, sheet_name='Summary', startrow=len(df_summary) + 4, index=False)
            df_highlights.to_excel(writer, sheet_name='Top_Items', index=False)
            if not df_missing.empty:
                df_missing.to_excel(writer, sheet_name='Error_Log', index=False)

        msg = f"리포트 생성 완료: {file_path}"
        if not df_missing.empty:
            msg += f"\n⚠️ [경고] {len(df_missing)}개의 자재 ID가 마스터에 없어 제외되었습니다. 'Error_Log' 시트를 확인하세요."
        return msg

    except Exception as e:
        return f"리포트 저장 실패: {str(e)}"

