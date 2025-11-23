import os
from dotenv import load_dotenv

from langgraph.graph import StateGraph, MessagesState
from langgraph.prebuilt import ToolNode, tools_condition

from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.runnables import chain

# 내부 도구 임포트
from tools import (
    calculate_gross_requirement,
    get_current_stock,
    check_long_term_stock_criteria
)

# 환경 변수 로드
load_dotenv()
api_key = os.environ.get("GOOGLE_API_KEY")
model = os.environ.get("MODEL")

if not api_key or not model:
    raise ValueError("GOOGLE_API_KEY 또는 MODEL 환경변수를 설정해주세요.")

# System Prompt 정의
SYSTEM_PROMPT = """
당신은 15년 경력의 생산 관리 전문가 AI Agent입니다.
Functions.csv와 ADR 문서에 정의된 규칙을 엄격히 준수하십시오.
모르는 정보는 지어내지 말고 도구를 사용하여 데이터를 조회하십시오.
답변은 한국어로 작성하며, 수치가 포함된 경우 명확한 근거를 제시하십시오.
"""

# LLM + Tools 설정
llm = ChatGoogleGenerativeAI(
    temperature=0,
    model=model,
    google_api_key=api_key
)

tools = [
    calculate_gross_requirement,
    get_current_stock,
    check_long_term_stock_criteria
]

llm_with_tools = llm.bind_tools(tools)

# Prompt Template
prompt_template = ChatPromptTemplate.from_messages([
    ("system", SYSTEM_PROMPT),
    MessagesPlaceholder(variable_name="messages"),
])

chain_prompt_llm = prompt_template | llm_with_tools


# 에이전트 노드 정의
@chain
def reasoner(state: MessagesState) -> dict:
    """
    MessagesState → Partial(MessagesState)
    LangGraph가 상태를 누적할 수 있도록 dict 반환
    """
    messages: list[BaseMessage] = state.get("messages", [])

    # 첫 메시지 처리
    if len(messages) == 0:
        return {"messages": [AIMessage(content="안녕하세요! 생산 관리 AI Agent입니다. 무엇을 도와드릴까요?")]}

    try:
        response: BaseMessage = chain_prompt_llm.invoke({"messages": messages})
        return {"messages": [response]}

    except Exception as e:
        return {"messages": [AIMessage(content=f"처리 중 오류 발생: {e}")]}


# 그래프 정의
builder = StateGraph(MessagesState)

builder.add_node("reasoner", reasoner)
builder.add_node("tools", ToolNode(tools))

builder.set_entry_point("reasoner")

# Tool 실행 조건부 경로
builder.add_conditional_edges("reasoner", tools_condition)

# Tool 실행 후 다시 Reasoner
builder.add_edge("tools", "reasoner")

# 최종 그래프 컴파일
graph = builder.compile()