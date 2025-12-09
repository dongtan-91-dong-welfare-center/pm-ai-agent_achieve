from dotenv import load_dotenv

# 환경 변수 최우선 로드
load_dotenv()

from langgraph.graph import StateGraph
from langgraph.prebuilt import ToolNode
from langgraph.checkpoint.memory import MemorySaver

from agent_state import AgentState
from agent_config import all_tools
from agent_nodes import reasoner, code_generator, code_executor, finalize_order, route_reasoner, route_after_execution


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
    builder.add_edge("finalize_order", "reasoner")  # 로직상 finalize 후 다시 생각하는 것이 의도가 맞는지 확인 필요 (보통은 End)

    # code_executor -> 분기 (성공/재시도)
    builder.add_conditional_edges(
        "code_executor",
        route_after_execution,
        {
            "success": "reasoner",  # 성공 -> reasoner 에서 결과 처리
            "retry": "code_generator",  # 재시도 -> 수정 코드 생성
            "max_retries": "reasoner"   # 최대 재시도 초과 -> reasoner에서 실패 보고
        }
    )

    # 6. 컴파일
    # interrupt_before=["finalize_order"]는 '승인' 버튼 구현을 위해 유지합니다.
    graph = builder.compile(
        checkpointer=memory,
        interrupt_before=["finalize_order"]
    )

    return graph