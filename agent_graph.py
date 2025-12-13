"""
설명: LangGraph를 사용하여 Agent의 노드(Nodes)와 엣지(Edges)를 연결하는 워크플로우 정의 파일

[Role & Responsibility]
- Checkpointing: MemorySaver를 통해 대화 턴(Turn) 간의 상태를 저장하고, Human-in-the-Loop(HIL) 개입을 지원합니다.
- Interrupt Logic: 'hil_approval' 단계 직전에 실행을 멈추고(interrupt_before), 사용자의 승인을 기다리도록 설정합니다.
"""

from dotenv import load_dotenv

# 환경 변수 최우선 로드 (API Key 등)
load_dotenv()

from langgraph.graph import StateGraph
from langgraph.prebuilt import ToolNode
from langgraph.checkpoint.memory import MemorySaver

# 내부 모듈 Import
from agent_state import AgentState
# tools/__init__.py 에서 정의한 도구 리스트
from tools import AGENT_TOOLS
from agent_nodes import (
    reasoner, code_generator, code_executor, finalize_order, hil_approval,
    route_reasoner, route_after_execution
)


def create_graph():
    """
    [Main Workflow Factory]
    LangGraph 인스턴스를 생성하고, 노드와 엣지를 연결하여 실행 가능한 그래프 객체를 반환합니다.

    Returns:
        CompiledStateGraph: 실행 가능한 그래프 객체 (app)
    """

    # 1. 메모리 설정 (State Persistence)
    # 대화 기록 유지 및 'interrupt_before' 기능을 위해 필수적입니다.
    # 실제 배포 시에는 Redis, Postgres 등의 영구 저장소(Saver)로 교체를 고려해야 합니다.
    memory = MemorySaver()

    # 2. 그래프 빌더 초기화
    builder = StateGraph(AgentState)

    # 3. 노드(Node) 등록
    # 각 함수는 agent_nodes.py에 정의되어 있으며, State를 입력받아 State를 반환합니다.
    builder.add_node("reasoner", reasoner)  # 두뇌: 판단 및 라우팅
    builder.add_node("tools", ToolNode(AGENT_TOOLS))  # 도구: 일반 조회/계산 (code_gen 제외)
    builder.add_node("code_generator", code_generator)  # 기술자: 파이썬 코드 생성
    builder.add_node("code_executor", code_executor)  # 작업자: 코드 실행 (샌드박스)
    builder.add_node("hil_approval", hil_approval)  # 관리자: 사용자 승인 (HIL)
    builder.add_node("finalize_order", finalize_order)  # 실행자: 최종 발주 처리

    # 4. 진입점(Entry Point) 설정
    builder.set_entry_point("reasoner")

    # -------------------------------------------------------------------------
    # 5. 엣지(Edge) 설정 - 워크플로우 연결
    # -------------------------------------------------------------------------

    # [Router 1] Reasoner -> Next Step
    # (도구 사용? vs 코드 생성? vs 승인 대기? vs 종료?)
    # 기존 코드의 중복 라우팅 문제를 해결하기 위해 통합 래퍼(Wrapper) 함수를 사용합니다.
    def united_reasoner_router(state):
        # 1순위: 만약 승인 대기 상태(pending=True)라면 HIL 노드로 이동
        if state.get("user_approval_pending"):
            return "hil_approval"

        # 2순위: 도구 호출(Tool Call)이 있다면 해당 도구/제너레이터로 이동
        # agent_nodes.py에 정의된 route_reasoner 로직 재사용
        decision = route_reasoner(state)
        return decision

    builder.add_conditional_edges(
        "reasoner",
        united_reasoner_router,
        {
            "tools": "tools",  # 일반 도구 호출
            "code_generator": "code_generator",  # Python 분석 요청
            "finalize_order": "finalize_order",  # 즉시 발주 확정 요청 (HIL 없이)
            "hil_approval": "hil_approval",  # 분석 완료 후 승인 대기 진입
            "__end__": "__end__"  # 답변 완료 및 대기
        }
    )

    # [Edge] Tools -> Reasoner
    # 도구 실행 결과(ToolMessage)를 가지고 다시 Reasoner가 판단하도록 복귀
    builder.add_edge("tools", "reasoner")

    # [Edge] Code Generator -> Code Executor
    # 생성된 코드는 반드시 실행기로 전달됨
    builder.add_edge("code_generator", "code_executor")

    # [Router 2] Code Executor -> Next Step
    # 실행 성공/실패 여부에 따른 재시도(Self-Correction) 로직
    builder.add_conditional_edges(
        "code_executor",
        route_after_execution,
        {
            "success": "reasoner",  # 성공 -> Reasoner로 돌아가서 결과 포맷팅
            "retry": "code_generator",  # 실패(재시도 가능) -> 코드 재생성
            "max_retries": "reasoner"  # 실패(횟수 초과) -> 에러 보고
        }
    )

    # [Router 3] HIL Approval -> Next Step
    # 사용자의 승인/반려/수정 결정에 따른 분기
    def route_after_approval(state):
        decision = state.get("user_approval_decision")
        if decision == "approve":
            return "finalize_order"  # 승인 시 최종 저장
        elif decision == "modify":
            return "reasoner"  # 수정 요청 시 다시 분석(Plan 수정)
        else:
            return "__end__"  # 반려 시 종료

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
    # interrupt_before를 사용하여 'hil_approval' 노드 실행 직전에 멈추도록 설정
    # 이를 통해 Streamlit UI에서 사용자가 "승인/반려" 버튼을 누를 시간을 확보함
    graph = builder.compile(
        checkpointer=memory,
        interrupt_before=["hil_approval"]
    )

    return graph