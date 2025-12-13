import pandas as pd
import numpy as np
import sys
import os

# 프로젝트 루트 경로 추가 (모듈 import를 위해)
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data_loader import load_master_data

# ==============================================================================
# 🛠️ 설정: 추적하고 싶은 자재 ID와 기준 년월을 입력하세요.
# ==============================================================================
TARGET_PRODUCT_IDS = ["2001530", ]  # 여기에 의심스러운 자재 코드를 문자열로 입력 (여러 개 가능)
TARGET_YEAR = 2025
TARGET_MONTH = 12


# ==============================================================================

def trace_monthly_closing_logic():
    print(f"\n🔍 [Debug] 자재 {TARGET_PRODUCT_IDS}에 대한 월말 마감 로직 추적 시작")
    print(f"📅 기준: {TARGET_YEAR}년 {TARGET_MONTH}월\n")

    # 1. 데이터 로드
    DB = load_master_data()
    txn_df = DB.get('purchase_transaction_history', pd.DataFrame()).copy()
    prod_df = DB.get('product', pd.DataFrame()).copy()

    # --- [Step 1] 원본 데이터 확인 ---
    # 로드 직후 데이터에서 해당 자재가 존재하는지 확인 (ID 정규화 전)
    # 엑셀의 원본 ID 형태를 모르므로, 포함된 문자열로 대략 검색
    print(f"--- [Step 1] 원본 데이터(Transaction) 검색 ---")
    for pid in TARGET_PRODUCT_IDS:
        # 문자열로 변환하여 부분 일치 검색
        mask = txn_df['product_id'].astype(str).str.contains(pid, na=False)
        found = txn_df[mask]
        print(f" > ID '{pid}' 포함된 원본 행 개수: {len(found)}건")
        if not found.empty:
            print(found[['product_id', 'receipt_date', 'movement_type', 'received_value_local_currency']].head(
                3).to_markdown(index=False))
            print("...")

    # 2. 전처리 로직 (button_tools.py와 동일하게 적용)

    # 2-1. 날짜 변환
    if 'receipt_date' in txn_df.columns:
        txn_df['receipt_date'] = pd.to_datetime(txn_df[date_col_name],
                                                errors='coerce') if 'receipt_date' in locals() else pd.to_datetime(
            txn_df['receipt_date'], errors='coerce')

    # 2-2. 이동유형 필터링 (101, 102만 남김)
    if 'movement_type' in txn_df.columns:
        txn_df['movement_type'] = txn_df['movement_type'].apply(
            lambda x: str(x).strip().replace('.0', '') if pd.notnull(x) else None
        )

    # --- [Step 2] 이동유형 필터링 후 확인 ---
    print(f"\n--- [Step 2] 이동유형(101, 102) 필터링 확인 ---")
    target_types = ['101', '102']

    # 추적 대상 자재들의 이동유형 분포 확인
    # 정규화 전이라 아직 ID 매칭이 정확하지 않을 수 있어, 대략적인 흐름만 봅니다.

    # 2-3. ID 정규화 (핵심)
    def normalize_id_strict(x):
        if pd.isna(x): return None
        s = str(x).strip()
        if s.lower() == 'nan': return None
        if s.endswith('.0'): s = s[:-2]
        s = s.lstrip('0')  # 앞자리 0 제거
        if not s: return None
        return s

    txn_df['product_id_norm'] = txn_df['product_id'].apply(normalize_id_strict)
    prod_df['product_id_norm'] = prod_df['product_id'].apply(normalize_id_strict)

    # 정규화된 ID로 타겟 필터링
    target_txn = txn_df[txn_df['product_id_norm'].isin(TARGET_PRODUCT_IDS)].copy()

    print(f"\n--- [Step 3] ID 정규화 후 타겟 자재 데이터 ({len(target_txn)}건) ---")
    if target_txn.empty:
        print("❌ [Critical] 정규화 후 해당 ID를 가진 데이터가 없습니다!")
        print(f"   (원본 ID가 {TARGET_PRODUCT_IDS}와 다르게 변환되었는지 확인 필요)")
        return

    print(target_txn[['product_id', 'product_id_norm', 'movement_type', 'receipt_date',
                      'received_value_local_currency']].to_markdown(index=False))

    # 2-4. 금액 변환 (102번 마이너스 처리)
    target_col = 'received_value_local_currency'
    target_txn[target_col] = pd.to_numeric(target_txn[target_col], errors='coerce').fillna(0)

    # 취소(102) 반영 로직
    mask_cancel = target_txn['movement_type'] == '102'
    target_txn.loc[mask_cancel, target_col] = -np.abs(target_txn.loc[mask_cancel, target_col])

    print(f"\n--- [Step 4] 금액 변환 및 반품(102) 처리 결과 ---")
    print(target_txn[['movement_type', 'received_value_local_currency']].head().to_markdown(index=False))

    # 2-5. 자재 마스터 병합 (유형 확인)
    merged_df = target_txn.merge(
        prod_df[['product_id_norm', 'product_type', 'description']],
        left_on='product_id_norm', right_on='product_id_norm',
        how='left', indicator=True
    )

    print(f"\n--- [Step 5] 자재 마스터 매칭 결과 ---")
    print(merged_df[['product_id_norm', 'product_type', 'description', '_merge']].head().to_markdown(index=False))

    if (merged_df['_merge'] == 'left_only').any():
        print("⚠️ [Warning] 일부 데이터가 자재 마스터와 매칭되지 않았습니다. (product_type 알 수 없음)")

    # 2-6. 최종 필터링 (날짜 & 통화)
    cond_date = (merged_df['receipt_date'].dt.year == TARGET_YEAR) & \
                (merged_df['receipt_date'].dt.month == TARGET_MONTH)

    cond_currency = pd.Series(True, index=merged_df.index)
    if 'order_currency' in merged_df.columns:
        cond_currency = (merged_df['order_currency'].fillna('').astype(str).str.strip().str.upper() == 'KRW')
    else:
        print("\nℹ️ [Info] 'order_currency' 컬럼이 없어 통화 필터링은 스킵합니다.")

    final_df = merged_df[cond_date & cond_currency].copy()

    print(f"\n--- [Step 6] 최종 필터링 결과 ({TARGET_YEAR}.{TARGET_MONTH}, KRW) ---")
    print(f" > 남은 행 개수: {len(final_df)}건")

    if final_df.empty:
        print("❌ [Result] 최종 조건에 맞는 데이터가 0건입니다.")
        print("   - 날짜가 다르거나, 통화가 KRW가 아니거나, 이동유형이 101/102가 아닐 수 있습니다.")
    else:
        print(
            final_df[['product_id_norm', 'receipt_date', 'movement_type', 'received_value_local_currency']].to_markdown(
                index=False))

        total_sum = final_df['received_value_local_currency'].sum()
        print(f"\n💰 [Final Result] 최종 집계 금액: {total_sum:,.0f}")


if __name__ == "__main__":
    trace_monthly_closing_logic()