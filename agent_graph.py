from dotenv import load_dotenv

# 환경 변수 최우선 로드
load_dotenv()

from langgraph.graph import StateGraph
from langgraph.prebuilt import ToolNode
from langgraph.checkpoint.memory import MemorySaver

from agent_state import AgentState
from agent_config import all_tools
from agent_nodes import reasoner, code_generator, code_executor, finalize_order, route_reasoner, route_after_execution

# 메모리 설정
memory = MemorySaver()

# 그래프 빌드
builder = StateGraph(AgentState)

# 노드 추가
builder.add_node("reasoner", reasoner)
builder.add_node("tools", ToolNode(all_tools))
builder.add_node("code_generator", code_generator)
builder.add_node("code_executor", code_executor)
builder.add_node("finalize_order", finalize_order)

# 진입점 설정
builder.set_entry_point("reasoner")

# 조건부 엣지: reasoner → (tools | code_generator | finalize_order | __end__)
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
builder.add_edge("tools", "reasoner")  # tools 완료 후 reasoner로 복귀
builder.add_edge("code_generator", "code_executor")  # code_generator → code_executor (자동)

# 조건부 엣지: code_executor → (reasoner | code_generator | reasoner)
builder.add_conditional_edges(
    "code_executor",
    route_after_execution,
    {
        "success": "reasoner",  # 성공 → reasoner에서 결과 처리
        "retry": "code_generator",  # 재시도 → 수정된 코드 생성
        "max_retries": "reasoner"  # 최대 재시도 초과 → reasoner에서 실패 보고
    }
)

# 고정 엣지
builder.add_edge("finalize_order", "reasoner")  # finalize_order 완료 후 reasoner

# 컴파일 (승인 대기 설정)
graph = builder.compile(
    checkpointer=memory,
    interrupt_before=["finalize_order"]
)