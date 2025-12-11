import pandas as pd
import numpy as np
from langchain_core.messages import AIMessage, SystemMessage, HumanMessage, BaseMessage

from agent_state import AgentState
from agent_config import llm, chain_prompt_llm
from data_loader import TABLE_SCHEMA
from prompt import format_schema_for_prompt, CODE_GEN_SYSTEM_PROMPT
import tools


# 데이터 직렬화 헬퍼 함수
def serialize_result(data):
    """
    DataFrame, NumPy 객체 등을 JSON/MsgPack 직렬화 가능한 Python 기본 타입으로 변환합니다.
    """
    # pandas dataframe -> dict
    if isinstance(data, pd.DataFrame):
        return {
            "type": "dataframe",
            "data": data.to_dict(orient='split'),
            "columns": data.columns.tolist()
        }
    # Pandas Series -> List or Dict
    elif isinstance(data, pd.Series):
        return data.to_dict()
    # NumPy Scalar Types -> Python Native Types
    elif isinstance(data, (np.integer, np.int64)):
        return int(data)
    elif isinstance(data, (np.floating, np.float64)):
        return float(data)
    elif isinstance(data, np.bool_):
        return bool(data)
    elif isinstance(data, np.ndarray):
        return data.tolist()
    # Recursive Handling (Dict / List)
    elif isinstance(data, dict):
        return {k: serialize_result(v) for k, v in data.items()} # 딕셔너리 내부 재귀 탐색
    elif isinstance(data, list):
        return [serialize_result(v) for v in data] # 리스트 내부 재귀 탐색
    # 이외 -> 그냥 반환
    return data

# router & summarizer
def reasoner(state: AgentState) -> dict:
    """
    LangGraph가 상태를 누적할 수 있도록 dict 반환
    사용자의 입력을 받아 흐름을 제어하거나, 최종 답변을 생성
    """
    print("--- NODE: Reasoner ---")
    messages = state.get("messages", [])
    # 1. 초기 진입 처리
    if not messages:
        return {"messages": [AIMessage(content="안녕하세요! 생산 관리 AI Agent입니다. 무엇을 도와드릴까요?")]}

    last_message = messages[-1]

    # [핵심 로직 1] 새로운 사용자 질문(Turn)이 시작된 경우
    # -> 이전 분석 결과(analysis_data, execution_status)를 모두 클리어해야 함
    if isinstance(last_message, HumanMessage):
        print(">>> New Interaction Detected: Resetting State...")

        try:
            # 라우팅을 위한 LLM 호출
            # (이전 대화 맥락은 messages 리스트에 남아있으므로 LLM이 기억함)
            response = chain_prompt_llm.invoke({"messages": messages})

            # 타입 강제 변환 (String -> AIMessage)
            # LLM이 문자열을 반환하더라도 AIMessage로 감싸서 리스트 연산 오류 방지
            final_response = response
            if isinstance(response, str):
                final_response = AIMessage(content=response)
            elif hasattr(response, "content") and hasattr(response, "type"):
                # BaseMessage 계열 (AIMessage, ToolMessage 등)
                final_response = response
            elif isinstance(response, dict):
                # dict 타입이면 문자열로 변환
                final_response = AIMessage(content=str(response))
            elif hasattr(response, "__dict__"):
                # 다른 객체들은 문자열화
                final_response = AIMessage(content=str(response))
            else:
                # 폴백
                final_response = AIMessage(content=str(response))

        return {
            "messages": [final_response],
            # --- 상태 초기화 (Reset) ---
            "execution_status": None,  # 실행 상태 리셋
            "analysis_data": {},  # 이전 데이터 제거
            "generated_code": None,  # 이전 코드 제거
            "code_execution_result": None,  # 이전 로그 제거
            "retry_count": 0  # 재시도 횟수 초기화
        }

    # [핵심 로직 2] 코드 실행(Executor)이 '성공'하고 돌아온 경우
    if state.get("execution_status") == "success" and state.get("analysis_data"):
        # 결과 데이터 가져오기
        result_data = state["analysis_data"].get("last_run_result", "결과 없음")

        # LLM에게 결과를 자연어로 요약 요청 (옵션)
        # 여기서는 MVP용으로 간단히 결과 안내 메시지를 반환
        # (필요하다면 여기서 LLM을 한 번 더 호출해서 `result_data`를 문장으로 만들 수 있음)

        return {
            "messages": [AIMessage(content=f"분석이 완료되었습니다. 결과: {result_data}")],
            # 상태는 유지 (사용자가 "그걸 엑셀로 저장해줘"라고 할 수 있으므로 데이터는 남겨둠)
            # 단, 무한 루프 방지를 위해 status를 'done' 등으로 바꾸거나,
            # 다음 턴에서 HumanMessage가 오면 알아서 초기화되므로 놔둬도 됨.
            "execution_status": "done"  # success 상태를 done으로 변경하여 루프 끊기
        }

    # [핵심 로직 3] 에러가 발생하여 실패로 끝난 경우
    if state.get("execution_status") == "error":
        error_msg = state.get("code_execution_result", "알 수 없는 오류")
        return {
            "messages": [AIMessage(content=f"작업을 수행하는 도중 오류가 발생했습니다.\n(내용: {error_msg})")],
            "execution_status": "done"
        }

    # 그 외의 경우 (예: Router가 Tool을 호출하고 ToolMessage가 들어온 직후 등)
    # ToolMessage가 마지막이라면 -> 다시 LLM을 호출해서 결과를 해석해야 함
    if hasattr(last_message, "tool_call_id") or last_message.type == "tool":
        response = chain_prompt_llm.invoke({"messages": messages})
        return {"messages": [response]}

    # 기본 안전 장치
    return {"messages": [AIMessage(content="다음 작업을 진행할 수 없습니다.")]}


# Code Generator Node (with Self-Correction)
def code_generator(state):
    """
    사용자 질문과 스키마 정보를 바탕으로 Python 코드를 생성합니다.
    에러 발생 시, 이전 에러 메시지를 포함하여 자동 수정(Self-Correction) 시도.
    """
    print("--- NODE: Code Generator ---")
    messages = state["messages"]
    execution_status = state.get("execution_status")
    error_message = state.get("code_execution_result")
    retry_count = state.get("retry_count", 0)

    # 가장 최근의 사용자 질문 찾기
    user_message = next(
        (msg for msg in reversed(messages) if isinstance(msg, HumanMessage)),
        None
    )
    user_question = user_message.content if user_message else "질문을 찾을 수 없습니다."

    # 스키마 정보 포맷팅
    schema_context = format_schema_for_prompt(TABLE_SCHEMA)

    # 기본 시스템 프롬프트 + 재시도 시 에러 정보 추가
    system_content = CODE_GEN_SYSTEM_PROMPT.format(
        schema_context=schema_context,
        user_question=user_question
    )

    # [Self-Correction] 이전 에러가 있으면 수정 지시 추가
    if execution_status == "error" and error_message:
        print(f">>> Retry #{retry_count}: Generating corrected code...")
        correction_instruction = (
            f"\n\n[⚠️  이전 코드 실행 실패]\n"
            f"이전 코드가 다음 오류로 인해 실행되지 않았습니다:\n{error_message}\n"
            f"이 오류를 해결하도록 코드를 수정하여 다시 작성해주세요."
        )
        system_content += correction_instruction

    try:
        # LLM 호출
        response = llm.invoke([
            SystemMessage(content=system_content),
            HumanMessage(content=user_question)
        ])

        # Markdown 포맷 제거
        generated_code = response.content.replace("```python", "").replace("```", "").strip()
        print(f"✓ Code Generated (retry_count={retry_count})")

        return {"generated_code": generated_code}

    except Exception as e:
        # 코드 생성 자체 실패 → 재시도 로직으로 넘김
        error_msg = f"코드 생성 중 오류: {str(e)}"
        print(f"❌ {error_msg}")

        return {
            "execution_status": "error",
            "code_execution_result": error_msg,
            "retry_count": retry_count + 1
        }


# Code Executor (Local Execution with Error Handling)
def code_executor(state):
    """
    생성된 코드를 안전한 환경(exec)에서 실행합니다.
    실패 시 execution_status='error'를 반환하여 재시도 로직 트리거.
    """
    print("--- NODE: Code Executor ---")
    generated_code = state.get("generated_code", "")
    retry_count = state.get("retry_count", 0)

    if not generated_code:
        return {
            "execution_status": "error",
            "code_execution_result": "생성된 코드가 비어 있습니다.",
            "retry_count": retry_count
        }

    # 실행 환경(Context) 준비
    global_context = {
        "pd": pd,
        "np": np,
        "tools": tools,
        "DB": tools.DB,
    }

    # 데이터프레임 단축 변수 추가 (예: df_product)
    if tools.DB:
        for table_name, df in tools.DB.items():
            global_context[f"df_{table_name}"] = df

    try:
        local_context = {}
        exec(generated_code, global_context, local_context)
        
        execution_result = local_context.get("result", None)

        if execution_result is None:
            return {
                "execution_status": "error",
                "code_execution_result": "'result' 변수에 값이 할당되지 않았습니다. 코드에서 반드시 result = ... 형태로 결과를 할당하세요.",
                "retry_count": retry_count + 1
            }

        # ✅ 성공
        return {
            "analysis_data": {"last_run_result": serialize_result(execution_result)},
            "execution_status": "success",
            "code_execution_result": "성공",
            "retry_count": 0
        }

    except Exception as e:
        # ❌ 실패 (에러 메시지와 함께 재시도 횟수 증가)
        error_msg = str(e)
        print(f"!!! Execution Error: {error_msg}")

        return {
            "execution_status": "error",
            "code_execution_result": error_msg,
            "retry_count": retry_count + 1
        }

# ============================================================================
# ROUTER FUNCTIONS (병합됨: agent_routers.py 로직)
# ============================================================================

from typing import Literal


def route_reasoner(state: AgentState) -> str:
    """
    LLM의 판단(Tool Call)을 보고 다음 노드를 결정합니다.
    
    Returns:
        "code_generator" - PythonAnalysisRequest 트리거
        "finalize_order" - FinalizeOrderRequest 트리거
        "tools" - 일반 도구 호출
        "__end__" - 종료
    """
    messages = state.get("messages", [])
    if not messages:
        return "__end__"
    
    last_message = messages[-1]

    # Tool Calls 확인
    if hasattr(last_message, "tool_calls") and last_message.tool_calls:
        first_tool = last_message.tool_calls[0]
        tool_name = first_tool["name"]

        print(f">>> [Reasoner Router] Tool Call: {tool_name}")

        # PythonAnalysisRequest → Code Generator (복잡한 분석)
        if tool_name == "PythonAnalysisRequest":
            return "code_generator"

        # FinalizeOrderRequest → Finalize Order (발주 최종 확정)
        if tool_name == "FinalizeOrderRequest":
            return "finalize_order"

        # 일반 도구 → Tools Node (재고 조회 등)
        return "tools"

    # 도구 호출 없음 → 종료
    return "__end__"


def route_after_execution(state: AgentState) -> Literal["success", "retry", "max_retries"]:
    """
    Code Executor의 실행 결과를 보고 재시도 여부를 결정합니다.
    
    **Self-Correction Loop:**
    - success: 정상 완료 → reasoner 진행
    - retry: 에러 발생, 재시도 가능 → code_generator 재실행
    - max_retries: 최대 재시도 횟수 초과 → reasoner에 실패 보고
    """
    status = state.get("execution_status")
    retry_count = state.get("retry_count", 0)
    MAX_RETRIES = 3

    print(f"--- [Execution Router] Status: {status}, Retries: {retry_count}/{MAX_RETRIES} ---")

    # ✅ 성공
    if status == "success":
        return "success"

    # ❌ 실패 → 재시도 가능?
    if status == "error":
        if retry_count < MAX_RETRIES:
            print(f">>> RETRY (Attempt {retry_count + 1}/{MAX_RETRIES})")
            return "retry"
        else:
            print(f">>> MAX RETRIES REACHED - GIVING UP")
            return "max_retries"

    # 예기치 않은 상태 → 성공으로 간주
    return "success"


# Finalize Order Node
def finalize_order(state: AgentState) -> dict:
    """
    발주 최종 확정 처리 (DB 저장 등)
    """
    print("--- NODE: Finalize Order ---")
    
    return {
        "messages": [AIMessage(content="발주가 최종 승인되어 시스템에 반영되었습니다.")]
    }