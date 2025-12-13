"""
설명: 분석 결과를 바탕으로 엑셀/CSV 리포트를 생성하거나, 월말 마감 보고서를 작성하는 도구 모음

[Role & Responsibility]
- Fallback Strategy: 엑셀 생성 라이브러리(openpyxl) 오류 시 CSV로 자동 전환하여 데이터 손실을 막습니다.
"""

from datetime import datetime
import os
import json
import pandas as pd
import numpy as np
from langchain_core.tools import tool
from .shared import DB, OUTPUT_DIR


# -------------------------------------------------------------------------
# Internal Helper Functions
# -------------------------------------------------------------------------

def _normalize_id(x):
    """[내부용] ID 정규화: None 처리, 소수점 제거, 앞쪽 0 제거"""
    if pd.isna(x) or x == "":
        return None
    s = str(x).strip()
    if s.endswith('.0'):
        s = s[:-2]
    return s.lstrip('0')

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

def _safe_save_excel(df: pd.DataFrame, file_path: str) -> str:
    """[내부용] 엑셀 저장 시도 후 실패 시 CSV로 저장하는 안전한 저장 함수"""
    try:
        # 1. 엑셀 저장 시도
        with pd.ExcelWriter(file_path, engine='openpyxl') as writer:
            # 시트 이름이 31자를 넘으면 엑셀 에러 발생하므로 Truncate
            sheet_name = "Report"
            df.to_excel(writer, index=False, sheet_name=sheet_name)
        return f"파일이 생성되었습니다: {file_path}"
    except Exception as e:
        # 2. 실패 시 CSV로 대체 저장
        csv_path = file_path.replace('.xlsx', '.csv')
        df.to_csv(csv_path, index=False)
        return f"엑셀 생성 실패({str(e)})로 인해 CSV로 저장되었습니다: {csv_path}"


# -------------------------------------------------------------------------
# Report Generation Tools
# -------------------------------------------------------------------------

@tool
def generate_excel_report(data_json: str, filename: str = "report.xlsx") -> str:
    """
    [범용 리포트 생성] 
    AI가 분석한 JSON 데이터(List of Dicts)를 엑셀 파일로 저장합니다.
    """
    try:
        data = json.loads(data_json) if isinstance(data_json, str) else data_json
        df = pd.DataFrame(data)

        if not filename.endswith('.xlsx'):
            filename += '.xlsx'

        file_path = os.path.join(OUTPUT_DIR, filename)
        return _safe_save_excel(df, file_path)

    except Exception as e:
        return f"파일 생성 실패: {str(e)}"


@tool
def generate_monthly_purchase_closing_report(year: int, month: int) -> str:
    """
    [월말 구매 마감 리포트] 
    지정된 연/월의 구매 마감 현황을 조회하여 마크다운 리포트로 반환합니다.
    (엑셀 파일 생성은 button_tools에서 별도로 수행됨)
    """
    try:
        from monthly_reports import generate_monthly_closing_report
        # 비즈니스 로직 위임
        report = generate_monthly_closing_report(DB, year, month)

        result_text = f"## {year}년 {month}월 구매 마감 리포트\n\n"
        result_text += f"**조회 기간**: {report['query_period']}\n\n"

        result_text += f"### 📊 통계\n"
        for key, value in report['statistics'].items():
            result_text += f"- {key}: {value}\n"

        result_text += f"\n### ✅ 완료된 발주 ({len(report['completed'])}건)\n"
        if not report['completed'].empty:
            result_text += report['completed'].to_markdown(index=False)
        else:
            result_text += "없음\n"

        result_text += f"\n### ⏳ 진행 중인 발주 ({len(report['in_progress'])}건)\n"
        if not report['in_progress'].empty:
            result_text += report['in_progress'].to_markdown(index=False)
        else:
            result_text += "없음\n"

        return result_text
    except Exception as e:
        return f"오류 발생: {str(e)}"


@tool
def calculate_monthly_material_requirement(year: int, month: int) -> str:
    """
    [월별 자재 소요량 계산] 
    해당 월의 생산 계획과 BOM을 기반으로 자재별 총 소요량 및 부족분을 계산합니다.
    """
    try:
        from monthly_reports import calculate_material_requirement
        result = calculate_material_requirement(DB, year, month)

        result_text = f"## {result['period']} 자재 소요량 계산\n\n"
        result_text += f"### 📊 통계\n"
        for key, value in result['statistics'].items():
            result_text += f"- {key}: {value}\n"

        result_text += f"\n### 📋 자재별 소요량 (상위 20개)\n"
        if isinstance(result['total_requirement'], pd.DataFrame) and not result['total_requirement'].empty:
            # 너무 길면 토큰 제한 걸리므로 상위 20개만 표시
            result_text += result['total_requirement'].head(20).to_markdown(index=False)
        else:
            result_text += "데이터 없음\n"

        if result['shortage_items']:
            result_text += f"\n### ⚠️ 부족 자재 경고\n"
            for shortage in result['shortage_items']:
                result_text += f"- **{shortage['product_id']}**: 필요 {shortage['required_qty']}, 현재재고 {shortage['current_stock']}, 부족량 {shortage['shortage_qty']}\n"

        return result_text
    except Exception as e:
        return f"오류 발생: {str(e)}"


@tool
def generate_po_status_report() -> str:
    """
    [발주 현황 공유 파일 생성]
    최근 2년치 발주 내역을 자재 유형(Product Type)별로 시트를 나누어 엑셀로 저장합니다.
    """
    try:
        po_df = DB.get('purchase_order', pd.DataFrame()).copy()
        vendor_df = DB.get('vendor_info_record', pd.DataFrame()).copy()
        prod_df = DB.get('product', pd.DataFrame()).copy()

        if po_df.empty:
            return "데이터 오류: 구매오더 데이터가 없습니다."

        # 1. ID 정규화 (Join Key 통일)
        po_df['vendor_id'] = po_df['vendor_id'].apply(_normalize_id)
        po_df['product_id'] = po_df['product_id'].apply(_normalize_id)
        vendor_df['vendor_id'] = vendor_df['vendor_id'].apply(_normalize_id)
        prod_df['product_id'] = prod_df['product_id'].apply(_normalize_id)

        # 2. 날짜 필터링 (최근 2년)
        if 'po_date' in po_df.columns:
            po_df['po_date'] = pd.to_datetime(po_df['po_date'], errors='coerce')

        today = pd.Timestamp.now()
        two_years_ago = today - pd.DateOffset(years=2)

        filtered_po = po_df[(po_df['po_date'] >= two_years_ago) & (po_df['po_date'] <= today)].copy()
        if filtered_po.empty:
            return "알림: 최근 2년 내의 발주 내역이 존재하지 않습니다."

        # 3. 데이터 병합 (Merge)
        merged_df = filtered_po.merge(vendor_df[['vendor_id', 'vendor_name']].drop_duplicates(), on='vendor_id',
                                      how='left')
        # product_type 정보 가져오기 위해 Product와 병합
        merged_df = merged_df.merge(prod_df[['product_id', 'description', 'product_type']].drop_duplicates(),
                                    on='product_id', how='left')

        if merged_df.empty:
            return "알림: 조건에 맞는 데이터가 없습니다."

        # 자재 유형 결측치 처리
        merged_df.loc[merged_df['product_type'].isna() | (
                    merged_df['product_type'].astype(str).str.strip() == ''), 'product_type'] = 'Unclassified'

        # 4. 엑셀 생성 (시트 분할)
        file_date = today.strftime('%Y%m%d')
        filename = f"PO_Status_Share_{file_date}.xlsx"
        file_path = os.path.join(OUTPUT_DIR, filename)

        try:
            with pd.ExcelWriter(file_path, engine='openpyxl') as writer:
                for p_type in merged_df['product_type'].unique():
                    # 시트명 길이 제한 (31자) 및 특수문자 제거
                    raw_sheet_name = str(p_type)
                    sheet_name = "".join(x for x in raw_sheet_name if x.isalnum() or x in [' ', '_'])[:30]

                    sheet_df = merged_df[merged_df['product_type'] == p_type]
                    sheet_df.to_excel(writer, sheet_name=sheet_name, index=False)
            return f"파일 생성 완료: {file_path}"
        except Exception as e:
            # Fallback to single CSV
            csv_path = file_path.replace('.xlsx', '.csv')
            merged_df.to_csv(csv_path, index=False)
            return f"엑셀 시트 분할 저장 실패({e}) -> 통합 CSV로 저장됨: {csv_path}"

    except Exception as e:
        return f"오류 발생: {str(e)}"


@tool
def generate_supplier_evaluation_report() -> str:
    """
    [공급업체 평가 양식 생성]
    입고 실적(Good Receipt)과 구매 오더, 부적합 내역(Non-Conformance)을 결합하여 평가 기초 데이터를 생성합니다.
    """
    try:
        gr_df = DB.get('good_receipt', pd.DataFrame()).copy()
        po_df = DB.get('purchase_order', pd.DataFrame()).copy()
        prod_df = DB.get('product', pd.DataFrame()).copy()
        vendor_df = DB.get('vendor_info_record', pd.DataFrame()).copy()
        nc_df = DB.get('non_conformance', pd.DataFrame()).copy()

        if gr_df.empty or po_df.empty:
            return "데이터 오류: 입고 내역 또는 구매 오더 데이터가 없습니다."

        # 1. ID 정규화
        for df, col in [(gr_df, 'batch_no'), (gr_df, 'po_id'), (gr_df, 'product_id'),
                        (po_df, 'po_id'), (po_df, 'vendor_id'),
                        (vendor_df, 'vendor_id'), (prod_df, 'product_id')]:
            if col in df.columns:
                df[col] = df[col].apply(_normalize_id)

        if not nc_df.empty and 'batch_no' in nc_df.columns:
            nc_df['batch_no'] = nc_df['batch_no'].apply(_normalize_id)

        # 2. 데이터 병합 및 계산
        gr_base = gr_df.dropna(subset=['batch_no']).drop_duplicates(subset=['batch_no']).copy()

        # 부적합 여부 판별
        nc_batch_set = set(nc_df['batch_no'].dropna().unique()) if not nc_df.empty else set()
        gr_base['is_non_conformance'] = gr_base['batch_no'].apply(lambda x: '부적합' if x in nc_batch_set else '적합')

        # 참조 테이블 준비
        po_ref = po_df[['po_id', 'vendor_id', 'po_date', 'delivery_date']].drop_duplicates(subset=['po_id'])
        vendor_ref = vendor_df[['vendor_id', 'vendor_name']].drop_duplicates(subset=['vendor_id'])
        prod_ref = prod_df[['product_id', 'description']].drop_duplicates(subset=['product_id'])

        # Merge Chain
        merged_df = gr_base.merge(po_ref, on='po_id', how='left') \
            .merge(vendor_ref, on='vendor_id', how='left') \
            .merge(prod_ref, on='product_id', how='left')

        merged_df['vendor_name'] = merged_df['vendor_name'].fillna('Unknown')
        merged_df['description'] = merged_df['description'].fillna('-')

        # 납기 준수일(LT) 계산
        merged_df['po_date'] = pd.to_datetime(merged_df['po_date'], errors='coerce')
        merged_df['delivery_date'] = pd.to_datetime(merged_df['delivery_date'], errors='coerce')
        merged_df['delivery_lt'] = (merged_df['delivery_date'] - merged_df['po_date']).dt.days.fillna(0)

        # 3. 결과 포맷팅
        final_cols_map = {
            'vendor_name': '업체명',
            'product_id': '품목코드',
            'description': '품목명',
            'batch_no': '성적번호',
            'delivery_lt': '납품 LT (일)',
            'is_non_conformance': '부적합 여부'
        }

        # 평가자가 입력할 빈 컬럼 추가
        empty_cols = ['부적합 사유', '납품 지연 사유', '지연 통보 선제성', '납품 기준 준수']
        for col in empty_cols:
            merged_df[col] = ''

        result_df = merged_df.rename(columns=final_cols_map)

        # 최종 컬럼 순서 정리
        target_cols = list(final_cols_map.values()) + empty_cols
        valid_cols = [c for c in target_cols if c in result_df.columns]
        result_df = result_df[valid_cols].drop_duplicates()

        # 4. 파일 저장
        today_str = pd.Timestamp.now().strftime('%Y%m%d')
        filename = f"Supplier_Evaluation_{today_str}.xlsx"
        file_path = os.path.join(OUTPUT_DIR, filename)

        return _safe_save_excel(result_df, file_path)

    except Exception as e:
        return f"오류 발생: {str(e)}"

@tool
def generate_monthly_purchase_closing_report(year: int = 0, month: int = 0) -> str:
    """
    [월말 구매 마감 리포트 생성]
    구매 상세 내역을 분석하여 Summary, Top Items, Error Log가 포함된 엑셀 리포트를 생성합니다.
    Args:
        year (int): 대상 연도 (0이면 자동 계산)
        month (int): 대상 월 (0이면 자동 계산)
    """
    # 여기에 button_tools.py의 run_monthly_closing_process 내부 로직을 그대로 복사해 넣습니다.
    # 단, 함수 인자(year, month)를 활용하도록 약간의 수정이 필요합니다.
    # ...
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
        target_col = 'total_received_value_krw'
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

        # 분기(Quarter) 계산 헬퍼
        def get_quarter_str(year, month):
            q = (month - 1) // 3 + 1
            return f"{year} {q}Q"

        col_ref1 = get_quarter_str(ref1_y, ref1_m)
        col_ref2 = get_quarter_str(ref2_y, ref2_m)

        # Summary DataFrame 구성
        summary_rows = [
            {"구분": "내자 원료", "작년 총합": roh1_krw_last, col_ref1: roh1_krw_ref1, col_ref2: roh1_krw_ref2, "전월 실적": roh1_krw_prev, "당월 실적": roh1_krw_curr, "전월 대비 증감": roh1_krw_curr - roh1_krw_prev},
            {"구분": "외자 원료", "작년 총합": roh1_for_last, col_ref1: roh1_for_ref1, col_ref2: roh1_for_ref2, "전월 실적": roh1_for_prev, "당월 실적": roh1_for_curr, "전월 대비 증감": roh1_for_curr - roh1_for_prev},
            {"구분": "내자 자재", "작년 총합": roh2_krw_last, col_ref1: roh2_krw_ref1, col_ref2: roh2_krw_ref2, "전월 실적": roh2_krw_prev, "당월 실적": roh2_krw_curr, "전월 대비 증감": roh2_krw_curr - roh2_krw_prev},
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
                target_col: 'sum',
                'description': 'first',
                'po_id': lambda x: ', '.join(sorted(x.dropna().astype(str).unique()))[:100] # PO 목록 요약
            }).reset_index()

            # ROH1 (원료) Top 1
            roh1_top = grouped[grouped['product_type'] == 'ROH1'].nlargest(1, target_col)
            if not roh1_top.empty:
                row = roh1_top.iloc[0].to_dict()
                row['구분'] = '원료 최다 지출'
                top_items_list.append(row)

            # ROH2 (자재) Top 3
            roh2_top = grouped[grouped['product_type'] == 'ROH2'].nlargest(3, target_col)
            if not roh2_top.empty:
                rank = 1
                for _, row in roh2_top.iterrows():
                    r_dict = row.to_dict()
                    r_dict['구분'] = f'자재 Top {rank}'
                    top_items_list.append(r_dict)
                    rank += 1

            df_top_items = pd.DataFrame(top_items_list)
            # 컬럼 순서 정리
            if not df_top_items.empty:
                target_cols = ['구분', 'product_id', 'description', target_col, 'po_id']
                existing_cols = [c for c in target_cols if c in df_top_items.columns]
                df_top_items = df_top_items[existing_cols]

                # 한글명으로 변경
                rename_map = {
                    'product_id': '자재 코드',
                    'description': '자재명',
                    target_col: '금액',
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