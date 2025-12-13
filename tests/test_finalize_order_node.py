from core.nodes import finalize_order
from langchain_core.messages import AIMessage


def test_finalize_order_validation_missing_fields():
    # Build a fake state with approval and analysis data lacking product_id
    state = {
        'messages': [AIMessage(content="분석 결과: 준비 완료")],
        'execution_status': 'approved',
        'analysis_data': {'last_run_result': [{'qty': 10, 'vendor_id': 'V1'}]},
        'generated_code': None,
        'code_execution_result': None,
        'retry_count': 0,
        'thinking_steps': [],
        'user_approval_pending': False,
        'user_approval_decision': None,
        'user_feedback': None
    }

    result = finalize_order(state)
    assert result["execution_status"] == "error" or result["messages"][0].content.startswith("발주 저장 실패")
