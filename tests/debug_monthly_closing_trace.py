import sys
import os
import pandas as pd
import numpy as np

# 프로젝트 루트 경로 설정
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
sys.path.append(parent_dir)

# 🛠️ [Fix] 절대 경로 설정을 사용하는 로더 Import
from data_loader.core import load_master_data


def debug_foreign_material_aggregation():
    print("\n" + "=" * 80)
    print("🕵️‍♂️ 외자 원료(ROH1 + Non-KRW) 연도별/월별 상세 분석")
    print("=" * 80)

    # 1. 데이터 로드 (수정된 로더 사용)
    db = load_master_data()
    txn_df = db.get('purchase_transaction_history').copy()
    prod_df = db.get('product').copy()

    if txn_df.empty:
        print("❌ 구매 이력 데이터가 없습니다. (Data Loader 경로 확인 필요)")
        return

    # 2. 전처리 (날짜, 이동유형, 금액)
    txn_df['receipt_date'] = pd.to_datetime(txn_df['receipt_date'], errors='coerce')
    txn_df['movement_type'] = txn_df['movement_type'].astype(str).str.replace(r'\.0$', '', regex=True).str.strip()

    # 101(입고), 102(취소)만 필터링
    target_txn = txn_df[txn_df['movement_type'].isin(['101', '102'])].copy()

    col_amt = 'received_value_local_currency'
    target_txn[col_amt] = pd.to_numeric(target_txn[col_amt], errors='coerce').fillna(0)
    # 취소(102)는 마이너스 처리
    target_txn.loc[target_txn['movement_type'] == '102', col_amt] *= -1

    # 3. ID 정규화 및 매칭
    def normalize_id(x):
        if pd.isna(x): return None
        s = str(x).strip().lstrip('0')
        return s if s else None

    target_txn['product_id_norm'] = target_txn['product_id'].apply(normalize_id)
    prod_df['product_id_norm'] = prod_df['product_id'].apply(normalize_id)

    # 4. 데이터 병합
    merged_df = target_txn.merge(
        prod_df[['product_id_norm', 'product_type', 'description']].drop_duplicates(subset=['product_id_norm']),
        on='product_id_norm',
        how='left'
    )

    # 5. 분류 기준 정제
    merged_df['order_currency'] = merged_df['order_currency'].fillna('').astype(str).str.strip().str.upper()
    merged_df['product_type'] = merged_df['product_type'].fillna('UNCLASSIFIED').astype(str).str.strip().str.upper()

    # -------------------------------------------------------------------------
    # 📊 [E] 핵심 분석: 외자 원료의 연도별 분포 확인
    # -------------------------------------------------------------------------
    print(f"\n[E] 외자 원료(ROH1 / Non-KRW) 연도별 집계 현황:")

    # 외자 원료만 필터링
    foreign_roh1 = merged_df[
        (merged_df['product_type'] == 'ROH1') &
        (merged_df['order_currency'] != 'KRW')
        ].copy()

    if foreign_roh1.empty:
        print("  >> 외자 원료 데이터가 하나도 없습니다.")
        return

    # 연도 컬럼 생성
    foreign_roh1['Year'] = foreign_roh1['receipt_date'].dt.year.fillna(0).astype(int)

    # 연도별 그룹핑
    yearly_summary = foreign_roh1.groupby('Year')[col_amt].sum().reset_index()
    yearly_summary.columns = ['연도', '합계 금액']

    print(yearly_summary.to_markdown(index=False, floatfmt=",.0f"))

    total_sum = yearly_summary['합계 금액'].sum()
    print(f"\n  👉 전체 누적 합계 (검증용): {total_sum:,.0f}")

    # 기준일(Max Date) 확인
    max_date = merged_df['receipt_date'].max()
    curr_year = max_date.year
    last_year = curr_year - 1

    print(f"\n[F] 리포트 생성 기준 확인:")
    print(f"  - 데이터 상 가장 최근 날짜: {max_date.strftime('%Y-%m-%d')}")
    print(f"  - 기준 연도(Current Year): {curr_year}년")
    print(f"  - 작년(Last Year) 정의    : {last_year}년")

    last_year_amt = yearly_summary.loc[yearly_summary['연도'] == last_year, '합계 금액'].sum()
    print(f"  👉 따라서 '작년 총합' 컬럼에는 [{last_year_amt:,.0f}]원이 찍혀야 정상입니다.")


if __name__ == "__main__":
    debug_foreign_material_aggregation()