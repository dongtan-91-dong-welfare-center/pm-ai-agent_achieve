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


# Code Generator (LLM -> schema만 활용)
def code_generator(state):
    """
    사용자 질문과 스키마 정보를 바탕으로 Python 코드를 생성합니다.
    보안 원칙: 실제 데이터(Value)는 보지 않고, 스키마(Column)만 참조합니다.
    """
    print("--- NODE: Code Generator ---")
    messages = state["messages"]

    # 리스트를 거꾸로 탐색하여 가장 최근의 HumanMessage를 찾습니다.
    user_message = next(
        (msg for msg in reversed(messages) if isinstance(msg, HumanMessage)),
        None
    )

    if user_message is None:
        return {"messages": [AIMessage(content="사용자의 질문을 찾을 수 없습니다.")]}

    user_question = user_message.content

    # 스키마 정보를 프롬프트용 텍스트로 변환
    schema_context = format_schema_for_prompt(TABLE_SCHEMA)

    # 시스템 프롬프트 구성
    system_content = CODE_GEN_SYSTEM_PROMPT.format(
        schema_context=schema_context,
        user_question=user_question
    )

    # LLM 호출 Tools를 사용하지 않고, 순수 Code Generation
    # binds_toos가 없는 순수 LLM 객체 사용
    try:
        # 메시지 구성: 시스템 프롬프트(지시) + 사용자 질문(컨텍스트)
        response = llm.invoke([
            SystemMessage(content=system_content),
            HumanMessage(content=user_question)
        ])
        # Markdown 코드 블록 제거
        generated_code = response.content.replace("```python", "").replace("```", "").strip()

        print(f"Generated Code:\n{generated_code}")  # 디버깅용

        return {"generated_code": generated_code}

    except Exception as e:
        return {
            "messages": [AIMessage(content=f"코드 생성 중 오류가 발생했습니다: {str(e)}")],
            "generated_code": ""
    }


# Code Executor (Local Execution)
def code_executor(state):
    """
    생성된 코드를 내부 안전 환경(exec)에서 실행합니다.
    이때 실제 데이터를 메모리에 로드하여 변수로 주입합니다.
    """
    print("--- NODE: Code Executor ---")
    generated_code = state.get("generated_code", "")

    if not generated_code:
        return {"messages": [AIMessage(content="실행할 코드가 생성되지 않았습니다.")]}

    # 실행 환경(Context) 준비: 실제 데이터를 로드
    # 보안상 이 데이터는 외부로 나가지 않고 이 함수 스코프 내에서만 존재합니다.
    # raw_data_dict = load_master_data()  # {'Inventory': df, 'BOM': df ...}
    raw_data_dict = load_mock_data_for_test()

    local_env = {"pd": pd}

    # 데이터프레임을 변수명(df_tablename)으로 매핑
    # 예: Product -> df_product
    for table, df in raw_data_dict.items():
        local_env[f"df_{table}"] = df

    # 하이브리드 로직: 비즈니스 함수 추가
    # 이제 LLM이 작성한 코드에서 이 함수명들을 변수처럼 쓸 수 있습니다.
    # local_env["calculate_safety_stock"] = 추가한 함수명
    # local_env["get_exchange_rate"] = 추가한 함수명
    
    # 코드 실행
    try:
        # exec()는 위험할 수 있으므로, 상용에서는 Sandbox(Docker/E2B) 사용 권장
        # MVP 단계에서는 로컬 exec 사용하되, 생성된 코드 검증 필요
        exec(generated_code, {}, local_env)

        # 결과 추출 ('result' 변수에 담긴 값)
        execution_result = local_env.get("result", None)

        if execution_result is None:
            return {
                "messages": [AIMessage(content="코드는 실행되었으나 결과(result) 변수가 없습니다.")],
                "execution_status": "failed"
            }

        return {
            # UI가 렌더링할 데이터
            # UI(Streamlit)로 보내기 위해 직렬화
            "analysis_data": {"last_run_result": serialize_result(execution_result)}, # # 결과 직렬화 (DataFrame -> Dict)
            # 실행 상태
            "execution_status": "success",
            # LLM에게 결과를 텍스트로도 알려주고 싶다면 messages에 추가
            "messages": [AIMessage(content=f"계산 결과는 다음과 같습니다: {str(execution_result)}")]
        }

    except Exception as e:
        print(f"Execution Error: {e}")
    return {
        "messages": [AIMessage(content=f"코드 실행 중 오류가 발생했습니다.\nError: {str(e)}")],
        "execution_status": "failed",
        "error_message": str(e)
    }

# finalize order(Action)
def finalize_order(state: AgentState) -> dict:
    """
    발주 결과를 반영하여 실제 DB 저장을 수행하는 노드
    """
    print("--- NODE: Finalize Order ---")
    # data = state.get("analysis_data", {}
    
    # 실제 DB 저장 로직 (Mock)
    return {"messages": [AIMessage(content="발주 정보를 데이터베이스에 저장하였습니다.")], "waiting_for_approval": False}