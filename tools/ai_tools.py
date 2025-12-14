"""
설명: (Legacy Support) 도구 모듈화 이후, 기존 import 경로와의 호환성을 유지하기 위한 재내보내기(Re-export) 모듈

[Role & Responsibility]
- Proxy: 실제 로직은 `stock_tools`, `order_tools` 등에 있으며, 이 파일은 바로가기 역할만 수행합니다.
- Compatibility: `from tools.ai_tools import get_current_stock`과 같은 기존 코드가 에러 없이 작동하게 합니다.
"""

# 1. 재고 관련 도구 (Stock Tools)
from .stock_tools import (
    get_current_stock,
    get_product_detail,
    check_long_term_stock_criteria,
    get_stock_status,
    analyze_long_term_stock,
)

# 2. 발주 및 소요량 도구 (Order Tools)
from .order_tools import (
    calculate_gross_requirement,
    generate_purchase_prediction,
    get_purchase_order_status,
    submit_purchase_order,
    submit_purchase_order_sync,
)

# 3. 보고서 생성 도구 (Report Tools)
from .report_tools import (
    generate_excel_report,                    # 범용 엑셀 리포트 생성기
    generate_monthly_purchase_closing_report, # 월간 구매 마감 보고서 생성
    generate_po_status_report,  #  발주 내역
    generate_supplier_evaluation_report,    # 공급업체 평가
)

# 외부에서 'from tools.ai_tools import *' 사용 시 노출될 목록 정의
__all__ = [
    # Stock
    'get_current_stock',
    'get_product_detail',
    'check_long_term_stock_criteria',
    'get_stock_status',
    'analyze_long_term_stock',

    # Order
    'calculate_gross_requirement',
    'generate_purchase_prediction',
    'get_purchase_order_status',
    'submit_purchase_order',
    'submit_purchase_order_sync',

    # Report
    'generate_excel_report',
    'generate_monthly_purchase_closing_report',
    'generate_po_status_report',
    'generate_supplier_evaluation_report',
]