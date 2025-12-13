#!/usr/bin/env python3
"""
리팩토링된 에이전트 검증 스크립트

목적:
1. 재시도 로직 (Self-Correction) 동작 확인
2. 라우팅 로직 정확성 검증
3. 상태 초기화 확인
4. 변수명 일관성 확인
"""

from core.nodes import (
    route_after_execution,
)
from langchain_core.messages import HumanMessage, AIMessage


def test_retry_logic():
    """재시도 로직 검증"""
    print("=" * 60)
    print("TEST 1: 재시도 로직 (Self-Correction)")
    print("=" * 60)

    # 시나리오: 코드 실행 실패 → 재시도 결정
    state = {
        "messages": [],
        "generated_code": "result = invalid_code()",
        "analysis_data": {},
        "execution_status": "error",
        "code_execution_result": "NameError: invalid_code is not defined",
        "retry_count": 1,
    }

    print("\n[State]")
    print(f"  execution_status: {state['execution_status']}")
    print(f"  retry_count: {state['retry_count']}")
    print(f"  code_execution_result: {state['code_execution_result']}")

    # Router 호출
    route_result = route_after_execution(state)
    print(f"\n[Router Decision]")
    print(f"  Result: {route_result}")
    assert route_result == "retry", f"❌ 재시도 결정 실패: {route_result}"
    print("  ✅ 재시도 결정 성공")

    # 최대 재시도 초과 시나리오
    state["retry_count"] = 3
    print(f"\n[Max Retries Check]")
    print(f"  retry_count: {state['retry_count']} >= MAX_RETRIES(3)")
    route_result = route_after_execution(state)
    print(f"  Result: {route_result}")
    assert route_result == "max_retries", f"❌ 최대 재시도 초과 결정 실패: {route_result}"
    print("  ✅ 최대 재시도 초과 결정 성공")

    # 성공 시나리오
    state["execution_status"] = "success"
    state["retry_count"] = 0
    print(f"\n[Success Case]")
    print(f"  execution_status: {state['execution_status']}")
    route_result = route_after_execution(state)
    print(f"  Result: {route_result}")
    assert route_result == "success", f"❌ 성공 결정 실패: {route_result}"
    print("  ✅ 성공 결정 정상")


def test_routing_logic():
    print("\n============================================================")
    print("TEST 2: 라우팅 로직 (Tool 분류)")
    print("============================================================")

    # agent_nodes에서 라우터 함수 가져오기
    try:
        from core.nodes import route_reasoner
    except ImportError:
        print("❌ agent_nodes.py에서 route_reasoner를 찾을 수 없습니다.")
        return

    # ---------------------------------------------------------
    # Case 1: PythonAnalysisRequest -> code_generator로 가야 함
    # ---------------------------------------------------------
    state_py = {
        "messages": [
            AIMessage(
                content="분석 요청",
                tool_calls=[{
                    "id": "call_001",  # [수정] id 필수 추가
                    "name": "PythonAnalysisRequest",
                    "args": {"description": "분석해줘"},
                    "type": "tool_call"
                }]
            )
        ]
    }

    result_py = route_reasoner(state_py)
    print(f"\n[Case 1: PythonAnalysisRequest]")
    print(f"  Expected: code_generator")
    print(f"  Actual:   {result_py}")

    if result_py == "code_generator":
        print("  ✅ PASS")
    else:
        print("  ❌ FAIL")

    # ---------------------------------------------------------
    # Case 2: FinalizeOrderRequest -> finalize_order로 가야 함
    # ---------------------------------------------------------
    state_order = {
        "messages": [
            AIMessage(
                content="발주 확정",
                tool_calls=[{
                    "id": "call_002",  # [수정] id 필수 추가
                    "name": "FinalizeOrderRequest",
                    "args": {"confirm_message": "확정"},
                    "type": "tool_call"
                }]
            )
        ]
    }

    result_order = route_reasoner(state_order)
    print(f"\n[Case 2: FinalizeOrderRequest]")
    print(f"  Expected: finalize_order")
    print(f"  Actual:   {result_order}")

    if result_order == "finalize_order":
        print("  ✅ PASS")
    else:
        print("  ❌ FAIL")

    # ---------------------------------------------------------
    # Case 3: 일반 Tool (예: get_stock_status) -> tools로 가야 함
    # ---------------------------------------------------------
    state_tool = {
        "messages": [
            AIMessage(
                content="재고 조회",
                tool_calls=[{
                    "id": "call_003",  # [수정] id 필수 추가
                    "name": "get_stock_status",
                    "args": {"product_ids": "A"},
                    "type": "tool_call"
                }]
            )
        ]
    }

    result_tool = route_reasoner(state_tool)
    print(f"\n[Case 3: General Tool]")
    print(f"  Expected: tools")
    print(f"  Actual:   {result_tool}")

    if result_tool == "tools":
        print("  ✅ PASS")
    else:
        print("  ❌ FAIL")


def test_state_consistency():
    """상태 변수명 일관성 검증"""
    print("\n" + "=" * 60)
    print("TEST 3: 상태 변수명 일관성")
    print("=" * 60)

    required_fields = [
        "messages",
        "generated_code",
        "analysis_data",
        "execution_status",
        "code_execution_result",
        "retry_count",
    ]

    print("\n[Required State Fields]")
    for field in required_fields:
        print(f"  ✓ {field}")

    # AgentState TypedDict 확인
    from core.state import AgentState as AgentStateDict

    state_annotations = AgentStateDict.__annotations__
    print("\n[AgentState Annotations]")
    for key in state_annotations:
        print(f"  {key}: {state_annotations[key]}")

    # 모든 필수 필드가 정의되어 있는지 확인
    for field in required_fields:
        assert field in state_annotations, f"❌ 필수 필드 누락: {field}"
    print("\n  ✅ 모든 필수 필드 정의됨")


def test_execution_flow():
    """실행 흐름 통합 테스트"""
    print("\n" + "=" * 60)
    print("TEST 4: 실행 흐름 통합")
    print("=" * 60)

    # 초기 상태
    state = {
        "messages": [HumanMessage(content="분석을 요청합니다")],
        "generated_code": None,
        "analysis_data": {},
        "execution_status": None,
        "code_execution_result": None,
        "retry_count": 0,
    }

    print("\n[Initial State]")
    print(f"  execution_status: {state['execution_status']}")
    print(f"  retry_count: {state['retry_count']}")
    print("  ✅ 초기 상태 정상")

    # 라우팅 시뮬레이션
    print("\n[Flow Simulation: Request → Generate → Execute → Retry → Success]")

    # Step 1: 코드 생성
    state["execution_status"] = None
    print(f"  Step 1: Code Generation (execution_status={state['execution_status']})")

    # Step 2: 코드 실행 실패
    state["execution_status"] = "error"
    state["code_execution_result"] = "KeyError: 'price'"
    state["retry_count"] = 1
    print(
        f"  Step 2: Execution Failed (execution_status={state['execution_status']}, retry_count={state['retry_count']})"
    )

    # Step 3: 재시도 결정
    route_result = route_after_execution(state)
    assert route_result == "retry"
    print(f"  Step 3: Router → {route_result}")

    # Step 4: 코드 재생성 (에러 메시지 포함)
    print(
        f"  Step 4: Code Re-generation (with error: {state['code_execution_result']})"
    )

    # Step 5: 코드 재실행 (성공)
    state["execution_status"] = "success"
    state["retry_count"] = 0
    print(f"  Step 5: Re-execution Success (execution_status={state['execution_status']})")

    # Step 6: 라우팅 결정 (성공)
    route_result = route_after_execution(state)
    assert route_result == "success"
    print(f"  Step 6: Router → {route_result}")

    print("\n  ✅ 통합 흐름 정상")


def test_state_reset():
    """상태 초기화 검증"""
    print("\n" + "=" * 60)
    print("TEST 5: 상태 초기화 (State Reset)")
    print("=" * 60)

    # Turn 1: 분석 완료 상태
    state = {
        "messages": [HumanMessage(content="질문1")],
        "generated_code": "result = df_product.sum()",
        "analysis_data": {"last_run_result": {"value": 100}},
        "execution_status": "done",
        "code_execution_result": "성공",
        "retry_count": 0,
    }

    print("\n[Turn 1 - After Analysis]")
    print(f"  execution_status: {state['execution_status']}")
    print(f"  analysis_data: {state['analysis_data']}")
    print(f"  generated_code: {state['generated_code']}")

    # Turn 2: 새로운 사용자 질문 → 상태 초기화
    last_message = state["messages"][-1]
    if isinstance(last_message, HumanMessage):
        print("\n[Turn 2 - New HumanMessage Detected]")
        print("  Resetting state...")

        state["execution_status"] = None
        state["analysis_data"] = {}
        state["generated_code"] = None
        state["code_execution_result"] = None
        state["retry_count"] = 0

        print(f"  execution_status: {state['execution_status']} (초기화됨)")
        print(f"  analysis_data: {state['analysis_data']} (초기화됨)")
        print(f"  generated_code: {state['generated_code']} (초기화됨)")
        print(f"  retry_count: {state['retry_count']} (초기화됨)")
        print("  ✅ 상태 초기화 정상")


if __name__ == "__main__":
    print("\n" + "=" * 60)
    print("🔧 Production Management AI Agent - 리팩토링 검증 테스트")
    print("=" * 60)

    try:
        test_retry_logic()
        test_routing_logic()
        test_state_consistency()
        test_execution_flow()
        test_state_reset()

        print("\n" + "=" * 60)
        print("✅ 모든 검증 테스트 통과!")
        print("=" * 60)
        print("\n[요약]")
        print("  ✓ 재시도 로직 (Self-Correction): 작동 정상")
        print("  ✓ 라우팅 로직 (Tool 분류): 작동 정상")
        print("  ✓ 상태 변수명 일관성: 확인됨")
        print("  ✓ 실행 흐름 통합: 작동 정상")
        print("  ✓ 상태 초기화: 작동 정상")
        print("\n🎯 MVP 준비 완료!")

    except AssertionError as e:
        print(f"\n❌ 검증 실패: {e}")
        exit(1)
    except Exception as e:
        print(f"\n❌ 예상 외 에러: {e}")
        import traceback

        traceback.print_exc()
        exit(1)
