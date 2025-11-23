import os
from dotenv import load_dotenv
from typing import TypedDict, Annotated, List, Optional, Dict, Any

# 환경 변수 로드
load_dotenv()
api_key = os.environ.get("GOOGLE_API_KEY")
model = os.environ.get("MODEL")

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import StateGraph, MessagesState
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import AIMessage, BaseMessage, SystemMessage, HumanMessage
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from pydantic import BaseModel, Field
from langchain_core.runnables import chain
from langchain_experimental.utilities import PythonREPL

import data_loader

# Python 실행기 준비(추후 보안을 위해 docker(podman)로 실행)
repl = PythonREPL()

# 메모리 전역 변수
memory = MemorySaver()

# 생성된 코드가 'DB' 변수를 사용할 수 있도록 로컬 환경(locals)을 설정
RUN_CONTEXT = {"DB": data_loader.load_master_data()}

# 내부 도구 임포트
from tools import (
    calculate_gross_requirement,
    get_current_stock,
    check_long_term_stock_criteria
)

if not api_key or not model:
    raise ValueError("GOOGLE_API_KEY 또는 MODEL 환경변수를 설정해주세요.")

# System Prompt 정의
SYSTEM_PROMPT = """
당신은 15년 경력의 생산 관리 전문가 AI Agent입니다.
Functions.csv와 ADR 문서에 정의된 규칙을 엄격히 준수하십시오.
모르는 정보는 지어내지 말고 도구를 사용하여 데이터를 조회하십시오.
답변은 한국어로 작성하며, 수치가 포함된 경우 명확한 근거를 제시하십시오.
"""

# AgentState 정의
class AgentState(TypedDict):
    """
    생산 관리 에이전트의 전체 상태를 관리하는 스키마
    업무 흐름(데이터 적재 -> 분석 -> 코드 생성 -> 승인)을 지원함
    """

    #  대화 기록
    # add_messages: 기존 메시지 리스트에 새 메시지를 append 하는 Reducer
    messages: Annotated[List[BaseMessage], add_messages]

    # 분석 컨텍스트
    # Multi-turn 대화에서 유지해야 할 핵심 비즈니스 데이터
    current_plan_id: Optional[str]  # 현재 분석 중인 생산 계획 ID (예: 'PLAN-2023-10')
    analysis_data: Dict[str, Any]  # 단계별 중간 산출물 저장소
    # 예: {
    #   "gross_req": DataFrame(dict),
    #   "net_req": DataFrame(dict),
    #   "draft_po": List[dict]
    # }

    # 코드 실행 컨텍스트 (Func-148, 144)
    # LLM이 생성한 코드와 실행 결과를 저장하여 Self-correction에 활용
    generated_code: Optional[str]  # 생성된 Python 코드 스니펫
    code_execution_result: Optional[str]  # 코드 실행 결과 (stdout 또는 에러 메시지)

    # Human-in-the-loop & 제어
    # 사용자 승인 여부 및 재시도 로직 제어
    waiting_for_approval: bool  # 사용자의 승인이 필요한 상태인지 플래그
    retry_count: int  # 에러 발생 시 재시도 횟수 (무한 루프 방지)

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

# Python 분석 요청용 구조체(라우팅 신호용)
class PythonAnalysisRequest(BaseModel):
    """복잡한 데이터 분석, 계산, 그래프 생성이 필요할 때 이 도구를 호출하세요."""
    description: str = Field(description="분석할 내용에 대한 상세 설명")

# 발주 확정 신호용 구조체 (LLM이 이 도구를 호출하면 발주 절차 시작)
class FinalizeOrderRequest(BaseModel):
    """
    모든 분석이 끝나고, 사용자가 발주를 승인했을 때 최종적으로 이 도구를 호출하여 DB에 저장합니다.
    """
    confirm_message: str = Field(description="발주 확정에 대한 최종 요약 메시지")

# LLM 바인딩
llm_with_tools = llm.bind_tools(tools + [PythonAnalysisRequest, FinalizeOrderRequest])

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


@chain
def code_generator(state: AgentState) -> dict:
    """
    Func-148: 분석을 위한 Python 코드 생성
    """
    messages = state.get("messages", [])
    last_error = state.get("code_execution_result")
    generated_code = state.get("generated_code")

    # 시스템 프롬프트: 데이터 스키마와 가이드라인 제공
    code_gen_prompt = """
    당신은 생산 관리 데이터를 분석하는 Python 전문가입니다.
    주어진 질문을 해결하기 위해 'DB' 딕셔너리에 있는 Pandas DataFrame을 사용하는 코드를 작성하세요.

    [사용 가능한 데이터 (DB keys)]
    - 'plan', 'bom', 'inventory', 'product', 'purchase_order'

    [규칙]
    1. 코드는 반드시 실행 가능한 Python 스크립트여야 합니다.
    2. 결과 데이터는 반드시 `result` 라는 변수에 할당해야 합니다.
    3. 마크다운(```python ... ```) 태그 없이 코드만 출력하거나, 태그가 있다면 파싱 가능한 형태여야 합니다.
    4. 그래프/시각화가 필요하면 스트림릿을 사용하지 말고 데이터프레임 자체를 `result`에 담으세요.
    """

    # 재시도(Self-Correction) 상황인 경우 에러 메시지 포함
    if last_error and generated_code:
        user_msg = f"""
        이전 코드 실행 중 에러가 발생했습니다.

        [이전 코드]
        {generated_code}

        [에러 메시지]
        {last_error}

        코드를 수정하여 다시 작성해주세요.
        """
    else:
        user_msg = "사용자의 요청을 분석하여 코드를 작성해주세요."

    # LLM 호출 (코드 생성 전용 프롬프트 적용)
    msg_history = [SystemMessage(content=code_gen_prompt)] + messages + [HumanMessage(content=user_msg)]

    response = llm.invoke(msg_history)

    # 코드 추출 (간단한 파싱 로직)
    code = response.content.replace("```python", "").replace("```", "").strip()

    return {"generated_code": code, "retry_count": 0}  # 카운트 리셋은 성공 시에만, 여기선 단순히 코드 갱신


def code_executor(state: AgentState) -> dict:
    """
    Func-144: 생성된 코드 실행 및 결과 검증
    """
    code = state.get("generated_code")
    retry_count = state.get("retry_count", 0)

    if not code:
        return {"code_execution_result": "실행할 코드가 없습니다.", "retry_count": retry_count}

    try:
        # 코드 실행 (안전한 샌드박스 환경 권장..)
        # 주의: 배포 시에는 exec()를 별도 실행 컨테이너 사용하기
        local_scope = RUN_CONTEXT.copy()
        exec(code, {}, local_scope)

        # 결과 추출 ('result' 변수 약속)
        result = local_scope.get("result")

        if result is None:
            return {
                "code_execution_result": "코드는 실행되었으나 'result' 변수가 정의되지 않았습니다.",
                "retry_count": retry_count + 1
            }

        # 실행 성공 시
        return {
            "analysis_data": {"last_run_result": result},  # 결과를 State에 저장
            "code_execution_result": None,  # 에러 클리어
            "messages": [AIMessage(content=f"분석 결과:\n{result}")]  # 사용자에게 결과 보고
        }

    except Exception as e:
        # 실행 실패 시 에러 메시지 저장
        return {
            "code_execution_result": str(e),
            "retry_count": retry_count + 1
        }


def route_after_execution(state: AgentState):
    """
    코드 실행 후 성공 여부에 따른 분기 처리
    """
    error = state.get("code_execution_result")
    retry_count = state.get("retry_count", 0)

    if error:
        if retry_count >= 3:
            return "max_retries"  # 3회 실패 시 중단
        return "retry"  # 에러 있으면 다시 생성(Self-Correction)

    return "success"  # 성공하면 종료(또는 다음 단계)


# Reasoner의 다음 경로를 결정하는 함수
def route_reasoner(state: AgentState):
    messages = state.get("messages", [])
    last_message = messages[-1]

    # 도구 호출이 없는 경우 -> 종료(END)
    if not last_message.tool_calls:
        return "__end__"

    # 도구 호출이 있는 경우, 어떤 도구인지 확인
    tool_call = last_message.tool_calls[0]
    tool_name = tool_call["name"]

    # "PythonAnalysisRequest"를 호출했다면 -> Code Generator로 전환
    if tool_name == "PythonAnalysisRequest":
        return "code_generator"

    # 발주 확정 요청 시 finalize_order로 이동
    if tool_name == "FinalizeOrderRequest":
        return "finalize_order"

    # 그 외 일반 도구(재고 조회 등)라면 -> 일반 Tools 노드로 이동
    return "tools"

# 실제 DB 저장을 수행하는 노드 (Func-133 구현부)
def finalize_order(state: AgentState) -> dict:
    """
    [Human-in-the-loop 대상 노드]
    이 노드는 'interrupt_before'에 의해 보호됩니다.
    사용자가 승인 버튼을 눌러야만 비로소 실행됩니다.
    """
    # 저장할 데이터 가져오기 (CodeExecutor 등이 analysis_data에 저장해둔 Draft 데이터)
    data = state.get("analysis_data", {})
    draft_po = data.get("draft_po")  # 예: 발주 리스트

    if not draft_po:
        return {
            "messages": [AIMessage(content="❌ 확정할 발주 데이터(Draft PO)가 없습니다. 먼저 소요량 분석을 수행해주세요.")]
        }

    # DB 적재 로직 (여기서는 MVP용 Mock 처리)
    # 실제로는 data_loader.save_purchase_order(draft_po) 호출
    try:
        # TODO: @parksaehyun 님이 구현할 DB Insert 함수 호출 위치
        # saved_count = insert_to_db(draft_po)
        saved_count = len(draft_po) if isinstance(draft_po, list) else 1

        result_msg = f"성공적으로 {saved_count}건의 발주 정보를 'Purchase_Order' 테이블에 이관했습니다."

        return {
            "messages": [AIMessage(content=result_msg)],
            "waiting_for_approval": False,  # 승인 대기 상태 해제
            "analysis_data": {}  # 데이터 초기화 (선택사항)
        }

    except Exception as e:
        return {
            "messages": [AIMessage(content=f"DB 저장 중 오류 발생: {e}")]
        }

# 그래프 정의
builder = StateGraph(AgentState)

# 그래프 빌더 연결
builder.add_node("reasoner", reasoner)
builder.add_node("tools", ToolNode(tools))
builder.add_node("code_generator", code_generator)
builder.add_node("code_executor", code_executor)
builder.add_node("finalize_order", finalize_order)

builder.set_entry_point("reasoner")

# Tool 실행 조건부 경로
builder.add_conditional_edges(
    "reasoner",
    route_reasoner,  # 위에서 만든 커스텀 라우터 함수
    {
        "tools": "tools",
        "code_generator": "code_generator",
        "finalize_order": "finalize_order",
        "__end__": "__end__"
    }
)

# [엣지 연결]
# 1. Reasoner가 코드 생성을 결정하면 Generator로 이동 (조건부 엣지 필요하지만, 지금은 테스트를 위해 직접 연결)
# 실제로는 reasoner의 output을 보고 tool_call이냐 code_gen이냐를 판단해야 합니다.
# 여기서는 '사용자가 분석을 요청하면' -> code_generator로 간다고 가정하는 별도 진입점을 만들거나
# reasoner가 'GenerateCode' 라는 도구를 호출하게 만들 수 있습니다.

# Reasoner -> CodeGenerator -> CodeExecutor -> Reasoner
builder.add_edge("tools", "reasoner")
builder.add_edge("code_generator", "code_executor")
builder.add_conditional_edges(
    "code_executor",
    route_after_execution,  # success/retry 분기
    {
        "success": "reasoner",     # 성공 시 결과를 가지고 다시 추론
        "retry": "code_generator", # 실패 시 다시 코드 작성 (Loop)
        "max_retries": "reasoner"  # 포기하고 에러 보고
    }
)

# finalize_order 실행 후에는 다시 reasoner로 가서 "저장 완료"를 보고함
builder.add_edge("finalize_order", "reasoner")

# 최종 그래프 컴파일
graph = builder.compile(
    checkpointer=memory,    # 상태 저장소
    interrupt_before=["finalize_order"],
)