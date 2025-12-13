"""
파일명: core/graph.py
설명: LangGraph 워크플로우 정의 (수정됨)
"""
from dotenv import load_dotenv

# 환경 변수 최우선 로드
load_dotenv()

from langgraph.graph import StateGraph
from langgraph.prebuilt import ToolNode
from langgraph.checkpoint.memory import MemorySaver

# -------------------------------------------------------------------------
# [수정된 부분] Import 경로 수정 (Relative Import 사용)
# -------------------------------------------------------------------------
# 같은 core 폴더 내에 있으므로 .state, .nodes 라고 명시해야 합니다.
from .state import AgentState
from .nodes import (
    reasoner, code_generator, code_executor, finalize_order, hil_approval,
    route_reasoner, route_after_execution
)

# tools는 프로젝트 루트에 있으므로 그대로 둡니다.
from tools import AGENT_TOOLS

# -------------------------------------------------------------------------

def create_graph():
    """
    [Main Workflow Factory]
    LangGraph 인스턴스를 생성하고, 노드와 엣지를 연결하여 실행 가능한 그래프 객체를 반환합니다.
    """

    # 1. 메모리 설정
    memory = MemorySaver()

    # 2. 그래프 빌더 초기화
    builder = StateGraph(AgentState)

    # 3. 노드(Node) 등록
    builder.add_node("reasoner", reasoner)
    builder.add_node("tools", ToolNode(AGENT_TOOLS))
    builder.add_node("code_generator", code_generator)
    builder.add_node("code_executor", code_executor)
    builder.add_node("hil_approval", hil_approval)
    builder.add_node("finalize_order", finalize_order)

    # 4. 진입점(Entry Point) 설정
    builder.set_entry_point("reasoner")

    # 5. 엣지(Edge) 설정

    # [Router 1] Reasoner -> Next Step (통합 라우터)
    def united_reasoner_router(state):
        if state.get("user_approval_pending"):
            return "hil_approval"

        # agent_nodes.py (이제 core/nodes.py)의 라우터 재사용
        decision = route_reasoner(state)
        return decision

    builder.add_conditional_edges(
        "reasoner",
        united_reasoner_router,
        {
            "tools": "tools",
            "code_generator": "code_generator",
            "finalize_order": "finalize_order",
            "hil_approval": "hil_approval",
            "__end__": "__end__"
        }
    )

    # [Edge] Tools -> Reasoner
    builder.add_edge("tools", "reasoner")

    # [Edge] Code Generator -> Code Executor
    builder.add_edge("code_generator", "code_executor")

    # [Router 2] Code Executor -> Next Step
    builder.add_conditional_edges(
        "code_executor",
        route_after_execution,
        {
            "success": "reasoner",
            "retry": "code_generator",
            "max_retries": "reasoner"
        }
    )

    # [Router 3] HIL Approval -> Next Step
    def route_after_approval(state):
        decision = state.get("user_approval_decision")
        if decision == "approve":
            return "finalize_order"
        elif decision == "modify":
            return "reasoner"
        else:
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

    # [Edge] Finalize Order -> End
    builder.add_edge("finalize_order", "__end__")

    # 6. 컴파일 (Compile)
    graph = builder.compile(
        checkpointer=memory,
        interrupt_before=["hil_approval"]
    )

    return graph