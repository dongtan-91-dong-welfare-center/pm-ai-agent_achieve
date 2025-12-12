# tools/__init__.py

# 1. 공통 자원 (DB, OUTPUT_DIR)을 외부로 노출
# [핵심] 이 부분이 있어야 외부에서 tools.DB로 접근 가능합니다.
from .shared import DB, OUTPUT_DIR

# 2. AI Agent가 사용할 도구들 (ai_tools.py)
from .ai_tools import (
    get_current_stock,
    get_product_detail,
    check_long_term_stock_criteria,
    get_stock_status,
    analyze_long_term_stock,
    calculate_gross_requirement,
    generate_purchase_prediction,
    generate_excel_report,
    generate_monthly_purchase_closing_report,
    calculate_monthly_material_requirement,
    get_purchase_order_status,
    submit_purchase_order,
    submit_purchase_order_sync,
)

# 3. UI(Streamlit)에서 버튼으로 실행할 함수들 (button_tools.py)
from .button_tools import (
    run_monthly_closing_process
)

# 4. Agent에게 전달할 도구 리스트 정의
AGENT_TOOLS = [
    get_current_stock,
    get_product_detail,
    check_long_term_stock_criteria,
    get_stock_status,
    analyze_long_term_stock,
    calculate_gross_requirement,
    generate_purchase_prediction,
    generate_excel_report,
    generate_monthly_purchase_closing_report,
    calculate_monthly_material_requirement,
    get_purchase_order_status,
    submit_purchase_order,
    run_monthly_closing_process
]