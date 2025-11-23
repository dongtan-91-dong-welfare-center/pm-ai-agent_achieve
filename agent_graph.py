from dotenv import load_dotenv

# 환경 변수 최우선 로드
load_dotenv()

from langgraph.graph import StateGraph
from langgraph.prebuilt import ToolNode
from langgraph.checkpoint.memory import MemorySaver

# 분리한 모듈들 임포트
from agent_state import AgentState
from agent_config import base_tools
from agent_nodes import reasoner, code_generator, code_executor, finalize_order
from agent_routers import route_reasoner, route_after_execution

# 메모리 설정
memory = MemorySaver()

# 그래프 빌드
builder = StateGraph(AgentState)

# 노드 추가
builder.add_node("reasoner", reasoner)
builder.add_node("tools", ToolNode(base_tools)) # base_tools만 실제 실행 (Request 모델 제외)
builder.add_node("code_generator", code_generator)
builder.add_node("code_executor", code_executor)
builder.add_node("finalize_order", finalize_order)

# 진입점 설정
builder.set_entry_point("reasoner")

# 엣지 연결
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

builder.add_edge("tools", "reasoner")
builder.add_edge("code_generator", "code_executor")

builder.add_conditional_edges(
    "code_executor",
    route_after_execution,
    {
        "success": "reasoner",
        "retry": "code_generator",
        "max_retries": "reasoner"
    }
)

builder.add_edge("finalize_order", "reasoner")

# 최종 컴파일 (승인 절차 포함)
graph = builder.compile(
    checkpointer=memory,
    interrupt_before=["finalize_order"]
)