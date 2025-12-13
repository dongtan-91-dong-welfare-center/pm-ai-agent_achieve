import sys
import os
import pandas as pd
import numpy as np

# 프로젝트 루트 경로 설정
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
sys.path.append(parent_dir)

from tools.shared import DB


def debug_foreign_material_aggregation():
    print("\n" + "=" * 80)
    print("🕵️‍♂️ 외자 원료(ROH1 + Non-KRW) 집계 누락 원인 분석")
    print("=" * 80)

    # 1. 데이터 로드
    txn_df = DB.get('purchase_transaction_history', pd.DataFrame()).copy()
    prod_df = DB.get('product', pd.DataFrame()).copy()

    if txn_df.empty:
        print("❌ 구매 이력 데이터가 없습니다.")
        return

    print(f"1. 전체 트랜잭션 수: {len(txn_df):,}건")

    # 2. 필터링 (이동유형 101, 102)
    # 정규화: .0 제거 및 공백 제거
    txn_df['movement_type'] = txn_df['movement_type'].astype(str).str.replace(r'\.0$', '', regex=True).str.strip()
    target_txn = txn_df[txn_df['movement_type'].isin(['101', '102'])].copy()
    print(f"2. 이동유형(101/102) 필터링 후: {len(target_txn):,}건")

    # 3. ID 정규화 및 매칭 준비
    def normalize_id(x):
        if pd.isna(x): return None
        s = str(x).strip().lstrip('0')
        return s if s else None

    target_txn['product_id_norm'] = target_txn['product_id'].apply(normalize_id)
    prod_df['product_id_norm'] = prod_df['product_id'].apply(normalize_id)

    # 4. 데이터 병합 (Left Join)
    merged_df = target_txn.merge(
        prod_df[['product_id_norm', 'product_type', 'description']].drop_duplicates(subset=['product_id_norm']),
        on='product_id_norm',
        how='left'
    )

    # 5. 통화 및 자재 유형 정제
    merged_df['order_currency'] = merged_df['order_currency'].fillna('').astype(str).str.strip().str.upper()
    merged_df['product_type'] = merged_df['product_type'].fillna('UNCLASSIFIED').astype(str).str.strip().str.upper()
    merged_df.loc[merged_df['product_type'] == '', 'product_type'] = 'UNCLASSIFIED'

    # 금액 컬럼 처리
    col_amt = 'received_value_local_currency'
    if col_amt not in merged_df.columns:
        print(f"❌ '{col_amt}' 컬럼이 없습니다. 분석 불가.")
        return

    merged_df[col_amt] = pd.to_numeric(merged_df[col_amt], errors='coerce').fillna(0)
    # 102(취소)는 마이너스 처리
    merged_df.loc[merged_df['movement_type'] == '102', col_amt] *= -1

    # -------------------------------------------------------------------------
    # 🔍 심층 분석 결과 출력
    # -------------------------------------------------------------------------

    # A. 통화별 분포 확인
    print("\n[A] 전체 데이터 통화(Currency) 분포:")
    print(merged_df['order_currency'].value_counts())

    # B. 외자(Non-KRW)인데 ROH1으로 집계되지 않은 건들 확인
    # 조건: 통화가 KRW가 아님 AND (자재유형이 UNCLASSIFIED 이거나 ROH1이 아님)
    print("\n[B] ⚠️ 외자(Non-KRW)이나 'ROH1' 집계에서 제외된 항목들 (누락 의심):")

    non_krw_mask = merged_df['order_currency'] != 'KRW'
    excluded_mask = merged_df['product_type'] != 'ROH1'

    missing_candidates = merged_df[non_krw_mask & excluded_mask]

    if not missing_candidates.empty:
        summary = missing_candidates.groupby(['product_type', 'order_currency']).agg(
            count=('product_id', 'count'),
            total_amount=(col_amt, 'sum')
        ).reset_index()
        print(summary.to_markdown(index=False, floatfmt=",.0f"))

        print("\n>> 상세 샘플 (상위 5개):")
        cols = ['product_id', 'product_type', 'order_currency', 'movement_type', col_amt, 'description']
        print(missing_candidates[cols].head(5).to_markdown(index=False))
    else:
        print("  >> 특이사항 없음. 모든 외자 건이 ROH1으로 분류됨.")

    # C. UNCLASSIFIED (매칭 실패) 상세 분석
    print("\n[C] ⚠️ 마스터 매칭 실패(UNCLASSIFIED) 중 금액이 큰 건들:")
    unclassified = merged_df[merged_df['product_type'] == 'UNCLASSIFIED']
    if not unclassified.empty:
        top_unclass = unclassified.groupby('product_id')[col_amt].sum().sort_values(ascending=False).head(10)
        print(top_unclass)
        print("\n  >> 위 자재 코드들이 'product.csv'에 존재하는지, 앞자리 0 처리가 맞는지 확인하세요.")
    else:
        print("  >> 매칭 실패 건 없음.")

    # D. 정상 집계 결과 (검증용)
    print("\n[D] 최종 집계 결과 (로직 검증):")
    roh1_foreign = merged_df[
        (merged_df['product_type'] == 'ROH1') &
        (merged_df['order_currency'] != 'KRW')
        ][col_amt].sum()

    print(f"  👉 현재 로직상 외자 원료(ROH1 + Non-KRW) 합계: {roh1_foreign:,.0f}")


if __name__ == "__main__":
    debug_foreign_material_aggregation()