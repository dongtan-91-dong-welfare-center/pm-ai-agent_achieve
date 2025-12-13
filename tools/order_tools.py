"""
설명: 생산 계획에 따른 자재 소요량 전개(MRP) 및 발주 예측(Purchase Prediction) 도구

[Core Business Logic]
1. Gross Requirement (총 소요량): (생산계획 수량 * BOM 소요량) + 오버리지(Loss)
2. Net Requirement (순 소요량): Max(0, 총 소요량 - 현재 가용 재고)
3. Vendor Selection: 고정 거래처(Fixed) -> 과거 발주 이력(History) -> 업체 마스터 순으로 탐색
"""

import os
import pandas as pd
from datetime import datetime
from langchain_core.tools import tool
from .utils import df_to_markdown
# [Adr-008] 복잡한 계산(오버리지 등)은 shared_logic.py의 순수 함수로 분리하여 테스트 용이성 확보
from .shared_logic import calculate_overage, calculate_component_gross_requirement
from .shared import DB, OUTPUT_DIR


@tool
def calculate_gross_requirement(plan_id: str | None = None, product_id: str | None = None,
                                base_requirement_per_unit: float | None = None) -> str:
    """
    [소요량 전개] 특정 생산 계획(plan_id)에 대해 BOM을 전개하고 오버리지 룰을 적용하여 총 소요량을 계산합니다.

    Args:
        plan_id (str): 생산 계획 ID 또는 Serial No. (상세 매칭 로직 포함)
        product_id (str): (Optional) 직접 품목 코드를 지정할 경우 사용
        base_requirement_per_unit (float): (Optional) 단위 소요량 강제 지정 시 사용

    Returns:
        str: 계산된 소요량 테이블(Markdown) 또는 에러 메시지
    """
    plan_df = DB.get('production_plan', pd.DataFrame())

    # 1. 대상 제품 식별 (Heuristic Plan Resolution)
    # 사용자가 정확한 ID를 모르고 "포장 단위"나 "국가"로 물어봐도 찾을 수 있도록 퍼지 매칭 수행
    target_product_id = product_id
    if not target_product_id and plan_id:
        if not plan_df.empty:
            pid_str = str(plan_id)
            # ID 매칭 시도
            if 'plan_id' in plan_df.columns and 'serial_no' in plan_df.columns:
                plan_row = plan_df[(plan_df['plan_id'] == pid_str) | (plan_df['serial_no'] == pid_str)]
            elif 'plan_id' in plan_df.columns:
                plan_row = plan_df[plan_df['plan_id'] == pid_str]
            elif 'serial_no' in plan_df.columns:
                plan_row = plan_df[plan_df['serial_no'] == pid_str]
            else:
                plan_row = pd.DataFrame()

            # 매칭 성공 시 제품 ID 추출
            if not plan_row.empty:
                row0 = plan_row.iloc[0]
                target_product_id = row0.get('product_id') or row0.get('root_product_id')

                # 제품 ID가 없으면 'prod_plan_code_map' 테이블을 통해 매핑 시도 (복잡한 매핑 로직)
                if not target_product_id:
                    ppcm = DB.get('prod_plan_code_map', pd.DataFrame())
                    if not ppcm.empty:
                        try:
                            # 국가, 포장단위 정규화 및 매칭 로직 (Team C 검수 필요)
                            country = row0.get('country')
                            packing = row0.get('packing_unit') or row0.get('pack_unit') or ''

                            def _norm_pack(x):
                                import re
                                s = str(x) if x is not None else ''
                                return re.sub(r'[^0-9A-Za-z]', '', s).lower()

                            def _digits_only(x):
                                import re
                                return re.sub(r'\D', '', str(x))

                            ppcm_candidates = ppcm.copy()
                            pack_col = None
                            for col in ['packing_unit', 'pack_unit', 'packaging_unit']:
                                if col in ppcm_candidates.columns:
                                    pack_col = col
                                    break

                            # 매핑 로직 상세 (생략 가능하나 디버깅 위해 유지)
                            if pack_col and packing:
                                ppcm_candidates['_norm_pack'] = ppcm_candidates[pack_col].astype(str).apply(_norm_pack)
                                ppcm_candidates['_digits'] = ppcm_candidates[pack_col].astype(str).apply(_digits_only)
                                target_norm = _norm_pack(packing)
                                target_digits = _digits_only(packing)
                                mapped = ppcm_candidates[ppcm_candidates['_norm_pack'] == target_norm]
                                if mapped.empty and target_digits:
                                    mapped = ppcm_candidates[ppcm_candidates['_digits'] == target_digits]
                                if not mapped.empty and country and 'country' in ppcm_candidates.columns:
                                    m2 = mapped[mapped['country'] == country]
                                    if not m2.empty:
                                        mapped = m2
                                if not mapped.empty:
                                    target_product_id = str(mapped.iloc[0]['product_id'])
                                else:
                                    # 설명(Description) 필드에서 숫자만 추출해 매칭 시도
                                    if 'description' in ppcm_candidates.columns and target_digits:
                                        ppcm_candidates['_desc_digits'] = ppcm_candidates['description'].astype(
                                            str).apply(_digits_only)
                                        mapped = ppcm_candidates[ppcm_candidates['_desc_digits'] == target_digits]
                                        if not mapped.empty and country and 'country' in ppcm_candidates.columns:
                                            m2 = mapped[mapped['country'] == country]
                                            if not m2.empty:
                                                mapped = m2
                                        if not mapped.empty:
                                            target_product_id = str(mapped.iloc[0]['product_id'])
                        except Exception:
                            pass  # 매핑 실패 시 원본 유지
                base_requirement_per_unit = base_requirement_per_unit or row0.get('standard_qty')

    if not target_product_id:
        return "제품 아이디를 지정해주세요. (plan_id 또는 product_id 필요)"

    # 2. BOM 정보 조회
    bom_df = DB.get('bom', pd.DataFrame())
    if bom_df.empty:
        return "BOM 데이터가 없습니다."

    # level '.1'은 직계 자식(Component)만을 의미함
    bom = bom_df[(bom_df['parent_product_id'] == target_product_id) & (bom_df['level'] == '.1')]

    # BOM 없음 처리
    if bom.empty:
        try:
            prod_series = DB.get('product', pd.DataFrame()).loc[
                DB.get('product', pd.DataFrame())['product_id'] == target_product_id, 'description']
            prod_desc = prod_series.iloc[0] if not prod_series.empty else target_product_id
        except Exception:
            prod_desc = target_product_id
        return f"제품({prod_desc})에 대한 BOM 정보가 존재하지 않습니다."

    # 3. 소요량 계산 루프
    requirements = []
    for _, row in bom.iterrows():
        component_id = row['component_product_id']
        base_req = base_requirement_per_unit if base_requirement_per_unit is not None else 0

        # [Adr-008] 오버리지 계산 로직 호출 (투입량 범위에 따른 Loss 적용)
        overage_qty = calculate_overage(DB, component_id, base_req)
        gross_req = base_req + overage_qty

        try:
            comp_series = DB.get('product', pd.DataFrame()).loc[
                DB.get('product', pd.DataFrame())['product_id'] == str(component_id), 'description']
            comp_desc = comp_series.iloc[0] if not comp_series.empty else "Unknown"
        except Exception:
            comp_desc = "Unknown"

        requirements.append({
            "component_id": component_id,
            "component_name": comp_desc,
            "base_requirement": base_req,
            "overage_qty": overage_qty,
            "gross_requirement": gross_req
        })

    return df_to_markdown(pd.DataFrame(requirements))


@tool
def generate_purchase_prediction(dummy_arg: str = "") -> str:
    """
    [발주 예측] 전체 생산 계획과 현재 재고를 분석해 부족 자재에 대해 발주가 필요할 경우 예측 결과를 생성합니다.

    [Algorithm Description]
    1. 생산 계획을 날짜순으로 정렬합니다 (Time-Phasing).
    2. 계획된 날짜 순서대로 자재를 소모(Simulation) 시킵니다.
    3. 가용 재고(Stock)가 부족해지는 시점에 부족분(Shortage)을 계산합니다.
    4. 부족분 발생 시 적절한 공급업체를 선정하여 발주 목록에 추가합니다.
    """
    plans = DB.get('production_plan', pd.DataFrame()).copy()
    bom = DB.get('bom', pd.DataFrame())
    stock = DB.get('warehouse_stock', pd.DataFrame())
    products = DB.get('product', pd.DataFrame())
    vendors = DB.get('vendor_info_record', pd.DataFrame())
    purchase_orders = DB.get('purchase_order', pd.DataFrame())
    vendor_master = DB.get('vendor', pd.DataFrame())

    if plans.empty: return "등록된 생산 계획이 없습니다."

    # 1. 생산 계획 정렬 (선입선출 가정)
    if 'start_date' in plans.columns:
        plans['start_date'] = pd.to_datetime(plans['start_date'])
        plans = plans.sort_values('start_date')

    # 2. 현재 재고 스냅샷 생성
    current_stock = {}
    if not stock.empty and 'unrestricted_qty' in stock.columns:
        stock['product_id'] = stock['product_id'].astype(str)
        current_stock = stock.groupby('product_id')['unrestricted_qty'].sum().to_dict()

    prediction_rows = []
    # 원자재(ROH)만 발주 대상에 포함 (반제품/완제품 제외)
    TARGET_MAT_TYPES = ['ROH']

    # 3. 계획 순회 및 시뮬레이션
    for _, plan in plans.iterrows():
        # 계획 수량 확인 (여러 컬럼명 대응)
        plan_qty = plan.get('standard_qty') or plan.get('quantity') or plan.get('plan_qty') or plan.get(
            'packing_unit') or plan.get('pack_unit') or 1
        target_product = plan.get('product_id') or plan.get('root_product_id') or plan.get('material_type') or plan.get(
            'product_code')
        delivery_date = plan['start_date'].strftime('%Y-%m-%d') if 'start_date' in plan else "Unknown"

        # BOM 전개
        plan_bom = bom[bom['parent_product_id'] == target_product]
        if plan_bom.empty: continue

        for _, comp in plan_bom.iterrows():
            comp_id = str(comp['component_product_id'])

            # 자재 유형 필터링 (ROH 확인)
            if not products.empty:
                product_info = products[products['product_id'] == comp_id]
                if not product_info.empty:
                    mat_type = product_info.iloc[0].get('product_type', '')
                    # 반제품(HALB)은 구매 대상이 아님
                    if mat_type == 'HALB':
                        continue
                    if TARGET_MAT_TYPES and not any(str(mat_type).startswith(t) for t in TARGET_MAT_TYPES):
                        continue

            # 소요량 계산 (Unit Req * Plan Qty)
            unit_req = comp['component_qty']
            total_req = unit_req * plan_qty

            # [Adr-008] 오버리지 적용
            overage_qty = calculate_overage(DB, comp_id, total_req)
            gross_req = total_req + overage_qty

            # 현재 시점의 가상 재고
            available = current_stock.get(comp_id, 0)

            # [핵심 로직] 재고 차감 시뮬레이션
            if available >= gross_req:
                # 재고 충분: 차감 후 진행
                current_stock[comp_id] = available - gross_req
            else:
                # 재고 부족: 부족분(Shortage) 계산 및 발주 예측 생성
                shortage = gross_req - available
                current_stock[comp_id] = 0  # 재고는 0이 됨

                # 자재명 조회
                prod_desc = ""
                if not products.empty:
                    p_row = products[products['product_id'] == comp_id]
                    if not p_row.empty: prod_desc = p_row.iloc[0]['description']

                # 공급업체 선정 로직 (우선순위 적용)
                vendor_name = "미지정"

                # 1순위: 구매정보레코드(Vendor Info Record)의 고정 거래처(Fixed Vendor)
                if not vendors.empty and 'product_id' in vendors.columns:
                    try:
                        v_rows = vendors[vendors['product_id'].astype(str) == comp_id]
                        if not v_rows.empty:
                            fixed = v_rows[v_rows.get('is_fixed_vendor',
                                                      '') == 'X'] if 'is_fixed_vendor' in v_rows.columns else v_rows
                            if not fixed.empty and 'vendor_name' in fixed.columns:
                                vendor_name = fixed.iloc[0]['vendor_name']
                    except Exception:
                        pass

                # 2순위: 최근 구매 이력(Purchase Order History)
                if vendor_name == "미지정" and not purchase_orders.empty and 'product_id' in purchase_orders.columns and 'vendor_id' in purchase_orders.columns:
                    try:
                        po_rows = purchase_orders[purchase_orders['product_id'].astype(str) == comp_id]
                        if not po_rows.empty and 'vendor_id' in po_rows.columns:
                            vid = po_rows.iloc[-1]['vendor_id']  # 가장 최근 발주처

                            # ID -> Name 변환
                            if not vendor_master.empty and 'vendor_id' in vendor_master.columns and 'vendor_name' in vendor_master.columns:
                                vm_row = vendor_master[vendor_master['vendor_id'] == vid]
                                if not vm_row.empty:
                                    vendor_name = vm_row.iloc[0]['vendor_name']
                                else:
                                    vendor_name = str(vid)
                            else:
                                vendor_name = str(vid)
                    except Exception:
                        pass

                prediction_rows.append({
                    "품목코드": comp_id,
                    "품목명": prod_desc,
                    "수량": shortage,  # 발주 필요량
                    "납품일자": delivery_date,  # 이 날짜까지 필요함
                    "공급업체": vendor_name
                })

    if not prediction_rows:
        return "발주 대상이 없습니다."

    # 결과 파일 저장 (OUTPUT_DIR)
    df_result = pd.DataFrame(prediction_rows)
    file_path = os.path.join(OUTPUT_DIR, f"Purchase_Prediction_{datetime.now().strftime('%Y%m%d')}.xlsx")
    alias_path = os.path.join(OUTPUT_DIR, f"Purchase_Order_Prediction.xlsx")  # 최신본 Alias

    try:
        df_result.to_excel(file_path, index=False)
        try:
            df_result.to_excel(alias_path, index=False)
        except Exception:
            try:
                import shutil
                shutil.copy(file_path, alias_path)
            except Exception:
                pass
    except Exception:
        # 엑셀 저장 실패 시 CSV로 대체
        csv_path = file_path.replace('.xlsx', '.csv')
        df_result.to_csv(csv_path, index=False)
        try:
            open(file_path, 'a').close()
        except Exception:
            pass

    return f"발주 예측 결과가 생성되었습니다.\n파일 경로: {file_path}\n대체 경로: {alias_path}"


@tool
def get_purchase_order_status(vendor_id: str = None, product_id: str = None) -> str:
    """[발주 현황 조회] 공급업체 또는 자재별로 현재 발주 상태(미처리, 진행 중, 완료)를 조회합니다."""
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
    [발주 제출] AI가 생성한 발주 항목(JSON)를 시스템에 저장합니다.

    Args:
        data_json (str): 발주 데이터를 포함한 JSON 문자열 (List of Dicts)

    Returns:
        str: 저장 성공 여부 메시지
    """
    try:
        import json
        from data_loader import core as dl_core

        rows = json.loads(data_json) if isinstance(data_json, str) else data_json
        if not isinstance(rows, list):
            rows = [rows]

        # 데이터 로더의 append 기능을 사용하여 영구 저장소에 기록
        success, msg = dl_core.append_purchase_order_rows(rows)
        return msg if success else f"저장 실패: {msg}"
    except Exception as e:
        return f"발주 저장 중 예외 발생: {e}"


def submit_purchase_order_sync(rows: list | dict) -> str:
    """
    [동기 발주 제출] UI 버튼 클릭 등 동기 방식 호출이 필요할 때 사용합니다.
    (Agent Tool 아님)
    """
    try:
        from data_loader import core as dl_core
        if isinstance(rows, dict):
            rows = [rows]
        success, msg = dl_core.append_purchase_order_rows(rows)
        return msg if success else f"저장 실패: {msg}"
    except Exception as e:
        return f"발주 저장 중 예외 발생: {e}"