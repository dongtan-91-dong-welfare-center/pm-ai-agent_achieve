from dotenv import load_dotenv

# 환경 변수 최우선 로드
load_dotenv()

from langgraph.graph import StateGraph
from langgraph.prebuilt import ToolNode
from langgraph.checkpoint.memory import MemorySaver

from agent_state import AgentState
from agent_config import all_tools
from agent_nodes import (
    reasoner, code_generator, code_executor, finalize_order, hil_approval,
    route_reasoner, route_after_execution
)


def create_graph():
    """
    LangGraph 인스턴스를 생성하고 컴파일하여 반환합니다.
    main.py 등 외부에서 이 함수를 호출하여 그래프 객체를 얻습니다.
    """

    # 메모리 설정 (스트리밍 및 상태 저장을 위해 필수)
    memory = MemorySaver()

    # 그래프 빌더 초기화
    builder = StateGraph(AgentState)

    # 노드 추가
    builder.add_node("reasoner", reasoner)
    builder.add_node("tools", ToolNode(all_tools))
    builder.add_node("code_generator", code_generator)
    builder.add_node("code_executor", code_executor)
    builder.add_node("hil_approval", hil_approval)  # HIL 노드 추가
    builder.add_node("finalize_order", finalize_order)

    # 진입점 설정
    builder.set_entry_point("reasoner")

    # 엣지 설정
    # reasoner → (tools | code_generator | finalize_order | __end__)
    builder.add_conditional_edges(
        "reasoner",
        route_reasoner,
        {
            "tools": "tools",
            "code_generator": "code_generator",
            "finalize_order": "finalize_order",
            "__end__": "__end__"
        }
    )

    # 고정 엣지
    builder.add_edge("tools", "reasoner")   # tools 완료 후 reasoner로 복귀
    builder.add_edge("code_generator", "code_executor")

    # code_executor -> 분기 (성공/재시도)
    builder.add_conditional_edges(
        "code_executor",
        route_after_execution,
        {
            "success": "reasoner",        # 성공 -> reasoner 에서 결과 포맷팅
            "retry": "code_generator",    # 재시도 -> 수정 코드 생성
            "max_retries": "reasoner"     # 최대 재시도 초과 -> reasoner에서 실패 보고
        }
    )

    # HIL (Human-in-the-Loop) 승인 흐름
    # reasoner가 결과를 반환할 때 user_approval_pending=True이면 HIL로 라우팅
    def route_to_hil_or_end(state):
        """결과 후 HIL 승인이 필요한지 판단"""
        if state.get("user_approval_pending"):
            return "hil_approval"
        return "__end__"
    
    builder.add_conditional_edges(
        "reasoner",
        route_to_hil_or_end,
        {
            "hil_approval": "hil_approval",
            "__end__": "__end__"
        }
    )

    # HIL -> finalize_order 또는 reasoner (수정 모드)
    def route_after_approval(state):
        """승인 결과에 따른 라우팅"""
        decision = state.get("user_approval_decision")
        if decision == "approve":
            return "finalize_order"
        elif decision == "modify":
            return "reasoner"  # 사용자 피드백을 포함해 재분석
        else:  # reject
            return "__end__"
    
    builder.add_conditional_edges(
        "hil_approval",
        route_after_approval,
        {
            "finalize_order": "finalize_order",
            "reasoner": "reasoner",
            "__end__": "__end__"
        }
    )

    builder.add_edge("finalize_order", "__end__")

    # 컴파일
    # interrupt_before를 사용하여 사용자 개입 지점 설정 (선택사항)
    graph = builder.compile(
        checkpointer=memory,
        interrupt_before=["hil_approval"]  # HIL 승인 전 멈춤
    )

    return graph