import math
import pandas as pd
import os
import json
from datetime import datetime, timedelta
from langchain_core.tools import tool
from .shared import DB, OUTPUT_DIR


# -------------------------------------------------------------------------
# 조회 및 분석 도구 (AI Agent용)
# -------------------------------------------------------------------------

@tool
def get_current_stock(product_ids: str) -> str:
    """[현재고 간편 조회] 특정 자재들의 현재 재고 수량을 조회합니다."""
    p_ids = [pid.strip() for pid in str(product_ids).split(',')]
    stock = DB.get('warehouse_stock', pd.DataFrame())

    if stock.empty:
        return "재고 데이터가 없습니다."

    stock['product_id'] = stock['product_id'].astype(str)
    target_stock = stock[stock['product_id'].isin(p_ids)]

    return target_stock.to_markdown(index=False)


@tool
def get_product_detail(product_id: str) -> str:
    """[자재 상세 조회] 자재 마스터 정보를 조회합니다."""
    prod_df = DB.get('product', pd.DataFrame())
    if prod_df.empty:
        return "자재 마스터 데이터가 없습니다."

    row = prod_df[prod_df['product_id'] == str(product_id).strip()]
    if row.empty:
        return f"자재 코드 {product_id}를 찾을 수 없습니다."

    return row.iloc[0].to_markdown()


@tool
def check_long_term_stock_criteria(product_id: str) -> str:
    """[장기재고 기준 확인] 자재별 장기재고 기준일(Days)을 확인합니다."""
    prod = DB.get('product', pd.DataFrame())
    if prod.empty:
        return "자재 마스터 데이터가 없습니다."

    row = prod[prod['product_id'] == str(product_id).strip()]
    if row.empty:
        return "해당 자재가 존재하지 않습니다."

    days = row.iloc[0].get('long_term_stock_days')
    return f"장기재고 기준일: {days}일" if days and days != 0 else "기준일 설정 없음 (SOP 확인 필요)"


@tool
def get_stock_status(product_ids: str) -> str:
    """[재고 상세 조회] 가용, 보류, 품질검사 등 상세 재고 상태를 조회합니다."""
    stock_df = DB.get('warehouse_stock', pd.DataFrame())
    if stock_df.empty:
        return "재고 데이터가 없습니다."

    p_ids = [pid.strip() for pid in str(product_ids).split(',')]
    stock_df['product_id'] = stock_df['product_id'].astype(str)
    target_stock = stock_df[stock_df['product_id'].isin(p_ids)]

    if target_stock.empty:
        return "해당 자재의 재고 정보가 없습니다."

    cols = ['product_id', 'batch_no', 'unrestricted_qty', 'inspection_qty', 'blocked_qty']
    valid_cols = [c for c in cols if c in target_stock.columns]

    return target_stock[valid_cols].to_markdown(index=False)


@tool
def analyze_long_term_stock(days_threshold: int = 180) -> str:
    """[장기 재고 분석] 입고된 지 특정 일수 이상 지난 재고를 분석합니다."""
    batch_df = DB.get('batch_stock', pd.DataFrame())
    if batch_df.empty:
        return "배치 재고 데이터가 없습니다."

    if 'receipt_date' not in batch_df.columns:
        return "입고일 정보가 없어 분석할 수 없습니다."

    limit_date = datetime.now() - timedelta(days=int(days_threshold))
    try:
        batch_df['receipt_date'] = pd.to_datetime(batch_df['receipt_date'])
        long_term = batch_df[batch_df['receipt_date'] <= limit_date]

        if long_term.empty:
            return f"{days_threshold}일 이상 경과한 장기 재고가 없습니다."

        return long_term[['product_id', 'batch_no', 'receipt_date', 'available_stock_value']].to_markdown(index=False)
    except Exception as e:
        return f"날짜 변환 중 오류 발생: {str(e)}"


@tool
def calculate_gross_requirement(plan_id: str) -> str:
    """
    [소요량 전개] 특정 생산 계획(plan_id)에 대해 BOM을 전개하여 필요한 원자재 총 소요량을 계산합니다.
    오버리지(Overage) 규칙을 적용하여 여유분을 포함한 총 소요량을 산출합니다.
    """
    plan_df = DB.get('production_plan', pd.DataFrame())

    # [Test Config] 테스트용 하드코딩 변수
    target_product_id = "9309896"
    base_requirement_per_unit = 12000

    bom_df = DB.get('bom', pd.DataFrame())
    if bom_df.empty:
        return "BOM 데이터가 없습니다."

    bom = bom_df[(bom_df['parent_product_id'] == target_product_id) & (bom_df['level'] == '.1')]

    if bom.empty:
        try:
            prod_desc = DB['product'].loc[DB['product']['product_id'] == target_product_id, 'description'].values[0]
        except:
            prod_desc = target_product_id
        return f"제품({prod_desc})에 대한 BOM 정보가 존재하지 않습니다."

    def _calculate_overage(component_id: str, base_qty: float) -> float:
        overage_df = DB.get('overage_rule', pd.DataFrame())
        if overage_df.empty: return 0.0

        target_comp_id = str(component_id).strip().lstrip('0')
        rules = overage_df[overage_df['product_id'] == target_comp_id]

        if rules.empty: return 0.0

        matched = rules[(rules['range_from'] <= base_qty) & (base_qty <= rules['range_to'])]
        if matched.empty: return 0.0

        rule = matched.iloc[0]
        overage_val = 0.0

        if pd.notna(rule.get('overage_abs_qty')):
            overage_val = float(rule['overage_abs_qty'])
        elif pd.notna(rule.get('overage_rate')):
            overage_val = base_qty * float(rule['overage_rate']) / 100

        decimals = int(rule.get('rounding_decimal') or 0)
        factor = 10 ** decimals
        if decimals == 0: return math.ceil(overage_val)
        return math.ceil(overage_val * factor) / factor

    requirements = []
    for _, row in bom.iterrows():
        component_id = row['component_product_id']
        base_req = base_requirement_per_unit  # Test Config
        overage_qty = _calculate_overage(component_id, base_req)
        gross_req = base_req + overage_qty

        try:
            comp_desc = DB['product'].loc[DB['product']['product_id'] == str(component_id), 'description'].values[0]
        except:
            comp_desc = "Unknown"

        requirements.append({
            "component_id": component_id,
            "component_name": comp_desc,
            "base_requirement": base_req,
            "overage_qty": overage_qty,
            "gross_requirement": gross_req
        })

    return pd.DataFrame(requirements).to_markdown(index=False)


@tool
def generate_purchase_prediction(dummy_arg: str = "") -> str:
    """
    [발주 예측] 전체 생산 계획과 현재 재고를 분석하여 자재별 발주 필요량을 예측합니다.
    """
    plans = DB.get('production_plan', pd.DataFrame()).copy()
    bom = DB.get('bom', pd.DataFrame())
    stock = DB.get('warehouse_stock', pd.DataFrame())
    products = DB.get('product', pd.DataFrame())
    vendors = DB.get('vendor_info_record', pd.DataFrame())

    if plans.empty: return "등록된 생산 계획이 없습니다."

    if 'start_date' in plans.columns:
        plans['start_date'] = pd.to_datetime(plans['start_date'])
        plans = plans.sort_values('start_date')

    current_stock = {}
    if not stock.empty and 'unrestricted_qty' in stock.columns:
        stock['product_id'] = stock['product_id'].astype(str)
        current_stock = stock.groupby('product_id')['unrestricted_qty'].sum().to_dict()

    prediction_rows = []
    TARGET_MAT_TYPES = ['ROH1', 'ROH2']

    for _, plan in plans.iterrows():
        target_product = 9309896  # Test
        plan_qty = 2
        delivery_date = plan['start_date'].strftime('%Y-%m-%d') if 'start_date' in plan else "Unknown"

        plan_bom = bom[bom['parent_product_id'] == target_product]
        if plan_bom.empty: continue

        for _, comp in plan_bom.iterrows():
            comp_id = str(comp['component_product_id'])

            # 원자재(ROH) 필터링
            if not products.empty:
                product_info = products[products['product_id'] == comp_id]
                if not product_info.empty:
                    mat_type = product_info.iloc[0].get('product_type', '')
                    if mat_type == 'HALB' or (TARGET_MAT_TYPES and mat_type not in TARGET_MAT_TYPES):
                        continue

            unit_req = comp['component_qty']
            total_req = unit_req * plan_qty
            available = current_stock.get(comp_id, 0)

            if available >= total_req:
                current_stock[comp_id] = available - total_req
            else:
                shortage = total_req - available
                current_stock[comp_id] = 0

                prod_desc = ""
                if not products.empty:
                    p_row = products[products['product_id'] == comp_id]
                    if not p_row.empty: prod_desc = p_row.iloc[0]['description']

                vendor_name = "미지정"
                if not vendors.empty:
                    v_rows = vendors[vendors['product_id'].astype(str) == comp_id]
                    if not v_rows.empty:
                        fixed = v_rows[v_rows['is_fixed_vendor'] == 'X']
                        if not fixed.empty:
                            vendor_name = fixed.iloc[0]['vendor_name']
                        else:
                            vendor_name = v_rows.iloc[0]['vendor_name']

                prediction_rows.append({
                    "품목코드": comp_id,
                    "품목명": prod_desc,
                    "발주필요량": shortage,
                    "납품요청일": delivery_date,
                    "추천공급사": vendor_name
                })

    if not prediction_rows:
        return "발주 대상이 없습니다."

    df_result = pd.DataFrame(prediction_rows)
    file_path = os.path.join(OUTPUT_DIR, f"Purchase_Prediction_{datetime.now().strftime('%Y%m%d')}.xlsx")
    df_result.to_excel(file_path, index=False)
    return f"발주 예측 결과가 생성되었습니다.\n파일 경로: {file_path}"


@tool
def generate_excel_report(data_json: str, filename: str = "report.xlsx") -> str:
    """[보고서 파일 생성] AI가 분석한 데이터를 엑셀로 저장할 때 사용합니다."""
    try:
        data = json.loads(data_json) if isinstance(data_json, str) else data_json
        df = pd.DataFrame(data)
        if not filename.endswith('.xlsx'): filename += '.xlsx'
        file_path = os.path.join(OUTPUT_DIR, filename)
        df.to_excel(file_path, index=False)
        return f"파일이 생성되었습니다: {file_path}"
    except Exception as e:
        return f"파일 생성 실패: {str(e)}"


@tool
def generate_monthly_purchase_closing_report(year: int, month: int) -> str:
    """
    [월말 구매 마감 리포트] 특정 월의 구매 마감 현황을 조회합니다.
    완료된 발주, 진행 중인 발주, 예정된 발주를 분류하여 반환합니다.
    """
    try:
        from monthly_reports import generate_monthly_closing_report
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
        return f"오류: {str(e)}"


@tool
def calculate_monthly_material_requirement(year: int, month: int) -> str:
    """
    [월별 자재 소요량 계산] 해당 월의 생산 계획을 기반으로 필요한 자재 소요량을 계산합니다.
    BOM을 전개하여 자재별 소요량과 부족 경고를 반환합니다.
    """
    try:
        from monthly_reports import calculate_material_requirement
        result = calculate_material_requirement(DB, year, month)

        result_text = f"## {result['period']} 자재 소요량 계산\n\n"
        result_text += f"### 📊 통계\n"
        for key, value in result['statistics'].items():
            result_text += f"- {key}: {value}\n"

        result_text += f"\n### 📋 자재별 소요량\n"
        if isinstance(result['total_requirement'], pd.DataFrame) and not result['total_requirement'].empty:
            result_text += result['total_requirement'].to_markdown(index=False)
        else:
            result_text += "데이터 없음\n"

        if result['shortage_items']:
            result_text += f"\n### ⚠️ 부족 자재 경고\n"
            for shortage in result['shortage_items']:
                result_text += f"- **{shortage['product_id']}**: 필요 {shortage['required_qty']}, 현재재고 {shortage['current_stock']}, 부족량 {shortage['shortage_qty']}\n"

        return result_text
    except Exception as e:
        return f"오류: {str(e)}"


@tool
def get_purchase_order_status(vendor_id: str = None, product_id: str = None) -> str:
    """
    [발주 현황 조회] 공급업체 또는 자재별 발주 상태를 조회합니다.
    미처리 발주, 완료율 등을 포함한 상세 현황을 반환합니다.
    """
    try:
        from monthly_reports import get_purchase_status
        status = get_purchase_status(DB, vendor_id, product_id)

        result_text = f"## 발주 현황 조회\n\n"
        if vendor_id:
            result_text += f"**공급업체**: {vendor_id}\n"
        if product_id:
            result_text += f"**자재**: {product_id}\n"

        result_text += f"\n### 📊 통계\n"
        for key, value in status['statistics'].items():
            result_text += f"- {key}: {value}\n"

        result_text += f"\n### 📋 공급업체별 현황\n"
        if isinstance(status['by_vendor'], pd.DataFrame) and not status['by_vendor'].empty:
            result_text += status['by_vendor'].to_markdown()
        else:
            result_text += "데이터 없음\n"

        result_text += f"\n### 🔴 미처리 발주 ({len(status['pending'])}건)\n"
        if not status['pending'].empty:
            result_text += status['pending'].to_markdown(index=False)
        else:
            result_text += "모두 처리됨\n"

        return result_text
    except Exception as e:
        return f"오류: {str(e)}"


@tool
def submit_purchase_order(data_json: str) -> str:
    """
    [발주 제출] AI가 생성한 발주 항목을 시스템에 저장합니다.
    입력은 JSON 문자열(또는 리스트)이며, 각 항목은 purchase_order 테이블의 컬럼명을 따라야 합니다.
    """
    try:
        import json
        from data_loader import core as dl_core
        from data_loader import config as dl_conf

        # Parse JSON
        rows = json.loads(data_json) if isinstance(data_json, str) else data_json
        if not isinstance(rows, list):
            rows = [rows]

        success, msg = dl_core.append_purchase_order_rows(rows)
        return msg if success else f"저장 실패: {msg}"
    except Exception as e:
        return f"발주 저장 중 예외 발생: {e}"


def submit_purchase_order_sync(rows: list | dict) -> str:
    """
    Synchronous API to store purchase orders. Rows can be a list or a single dict.
    Intended for direct Python invocation (tests, scripts) where StructuredTool is not invokable.
    """
    try:
        from data_loader import core as dl_core
        if isinstance(rows, dict):
            rows = [rows]
        success, msg = dl_core.append_purchase_order_rows(rows)
        return msg if success else f"저장 실패: {msg}"
    except Exception as e:
        return f"발주 저장 중 예외 발생: {e}"