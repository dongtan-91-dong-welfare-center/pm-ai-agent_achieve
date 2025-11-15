import operator
from typing import Annotated, List, TypedDict, Literal
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage
from langgraph.graph import StateGraph
from langgraph.prebuilt import ToolNode

from app.core.config import settings
from app.tools.inventory import analyze_long_term_inventory
from app.tools.order import calculate_optimal_purchase_order


# 1. 상태 정의 (State)
class AgentState(TypedDict):
    messages: Annotated[List[BaseMessage], operator.add]


# 2. 도구 및 모델 설정
tools = [analyze_long_term_inventory, calculate_optimal_purchase_order]
llm = ChatGoogleGenerativeAI(
    model="gemini-2.5-flash",
    google_api_key=settings.GOOGLE_API_KEY,
    temperature=0
)
llm_with_tools = llm.bind_tools(tools)


# 3. 노드 함수 정의
def call_model(state: AgentState):
    """LLM을 호출하여 다음 행동을 결정합니다."""
    messages = state["messages"]
    response = llm_with_tools.invoke(messages)
    return {"messages": [response]}


def should_continue(state: AgentState) -> Literal["tools", "__end__"]:
    """LLM의 응답에 따라 도구를 실행할지, 종료할지 결정합니다."""
    messages = state["messages"]
    last_message = messages[-1]

    # tool_calls가 있으면 도구 실행 노드로 이동
    if last_message.tool_calls:
        return "tools"
    return "__end__"


# 4. 그래프 구성 (Workflow)
def create_report_graph():
    workflow = StateGraph(AgentState)

    # 노드 추가
    workflow.add_node("agent", call_model)
    workflow.add_node("tools", ToolNode(tools))  # LangGraph 기본 ToolNode 사용

    # 엣지 연결
    workflow.set_entry_point("agent")

    workflow.add_conditional_edges(
        "agent",
        should_continue,
    )

    workflow.add_edge("tools", "agent")  # 도구 실행 후 다시 에이전트로

    return workflow.compile()


# 5. 실행 함수 (API에서 호출)
async def run_report_generation(user_prompt: str, history: List[BaseMessage], guidelines: str):
    app = create_report_graph()

    system_prompt = f"""
    당신은 생산 관리 AI 에이전트입니다. 다음 가이드라인을 준수하세요:
    {guidelines}
    """

    inputs = {
        "messages": [SystemMessage(content=system_prompt)] + history + [HumanMessage(content=user_prompt)]
    }

    # LangGraph 실행
    final_state = await app.ainvoke(inputs)

    # 결과 추출 및 로그 변환 (여기서 LangGraph 로그 -> API 스키마 매핑)
    messages = final_state["messages"]
    last_msg = messages[-1]
    content = last_msg.content

    # 로그 변환 로직 (간소화)
    logs = []
    step_count = 1
    for msg in messages:
        if msg.type == "ai" and msg.tool_calls:
            for tool_call in msg.tool_calls:
                logs.append({
                    "step": step_count,
                    "thought": "도구 호출 필요",
                    "action": {"tool_name": tool_call["name"], "tool_input": tool_call["args"]},
                    "observation": None  # ToolMessage에서 매핑 필요 (복잡성 줄임)
                })
                step_count += 1

    return content, logs