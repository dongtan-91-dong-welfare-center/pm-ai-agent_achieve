import pandas as pd
import numpy as np
from langchain_core.messages import AIMessage, SystemMessage, HumanMessage
from langchain_core.runnables import chain

# 설정 및 데이터 로더 관련 임포트
from agent_state import AgentState
from agent_config import llm, chain_prompt_llm # llm: 순수 모델, chain_prompt_llm: 대화형 모델
from data_loader import TABLE_SCHEMA, load_master_data, load_mock_data_for_test
from prompt import CODE_GEN_SYSTEM_PROMPT, format_schema_for_prompt

# Python 실행 환경 준비 - 내부 LLM을 사용하는 경우 모두 사용해도 됨
# RUN_CONTEXT = {"DB": data_loader.load_master_data(), "pd": pd}

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
    # if isinstance(data, pd.DataFrame):
    #     return data.to_dict(orient='split')  # DataFrame -> Dict 변환

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

    # 첫 메시지 처리
    if len(messages) == 0:
        return {"messages": [AIMessage(content="안녕하세요! 생산 관리 AI Agent입니다. 무엇을 도와드릴까요?")]}

    last_message = messages[-1]

    # 사용자의 새로운 질문이 들어왔다면?
    # 기존에 analysis_data가 남아있더라도 무시하고 새로운 라우팅(LLM 호출)을 시작해야 함.
    if isinstance(last_message, HumanMessage):
        # 새로운 질문이 시작되었으므로 과거 분석 데이터는 클리어하는 것이 안전할 수 있으나,
        # LangGraph 구조상 여기서 state를 지우기보다 로직으로 무시하는 것이 깔끔합니다.
        print('사용자의 요청')
        pass

    # 사용자가 아니라 시스템이 루프를 돌고 돌아온 경우
    if state.get("analysis_data"):
        # Code Executor가 막 일을 마치고 돌아온 상태라면 종료 메시지 반환
        # 이때는 마지막 메시지가 HumanMessage가 아님 (보통 ToolMessage거나 직전 단계의 산출물)
        # LLM에게 결과를 텍스트로 요약해달라고 요청하는 로직 추가 가능
        return {"message": [AIMessage(content="분석을 완료하였습니다. 결과를 확인해 주시기 바랍니다.")]}

    # 일반적인 대화 처리(router가 code gen으로 보낼지 결정을 함)
    try:
        response = chain_prompt_llm.invoke({"messages": messages})
        return {"messages": [response]}
    except Exception as e:
        return {"messages": [AIMessage(content=f"처리 중 오류 발생: {e}")]}



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

    # 시스템 프롬프트 구성
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
    발주 결과를 반영하여 실제 DB 저장을 수행하는 노드
    """
    print("--- NODE: Finalize Order ---")
    # data = state.get("analysis_data", {}
    
    # 실제 DB 저장 로직 (Mock)
    return {"messages": [AIMessage(content="발주 정보를 데이터베이스에 저장하였습니다.")], "waiting_for_approval": False}