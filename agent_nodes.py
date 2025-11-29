import pandas as pd
from langchain_core.messages import AIMessage, SystemMessage, HumanMessage
from langchain_core.runnables import chain

import data_loader
from prompt import CODE_GEN_PROMPT
from agent_state import AgentState
from agent_config import llm, chain_prompt_llm

# Python 실행 환경 준비 - 내부 LLM을 사용하는 경우 모두 사용해도 됨
# RUN_CONTEXT = {"DB": data_loader.load_master_data(), "pd": pd}

@chain
def reasoner(state: AgentState) -> dict:
    """
    LangGraph가 상태를 누적할 수 있도록 dict 반환
    """
    messages = state.get("messages", [])
    # 첫 메시지 처리
    if len(messages) == 0:
        return {"messages": [AIMessage(content="안녕하세요! 생산 관리 AI Agent입니다. 무엇을 도와드릴까요?")]}
    try:
        response = chain_prompt_llm.invoke({"messages": messages})
        return {"messages": [response]}
    except Exception as e:
        return {"messages": [AIMessage(content=f"처리 중 오류 발생: {e}")]}


@chain
def code_generator(state: AgentState) -> dict:
    """
    분석을 위한 Python 코드 생성
    """
    messages = state.get("messages", [])
    last_error = state.get("code_execution_result")
    generated_code = state.get("generated_code")

    # 코드 생성을 위한 가이드라인 제공
    code_gen_prompt = CODE_GEN_PROMPT

    if last_error and generated_code:
        user_msg = f"이전 코드 에러 발생:\n{last_error}\n코드를 수정해주세요."
    else:
        user_msg = "분석 코드를 작성해주세요."

    msg_history = [SystemMessage(content=code_gen_prompt)] + messages + [HumanMessage(content=user_msg)]
    response = llm.invoke(msg_history)

    # 코드를 추출하는 로직
    code = response.content.replace("```python", "").replace("```", "").strip()
    return {"generated_code": code}

# 데이터 직렬화 헬퍼 함수
def serialize_result(data):
    """
    DataFrame이 딕셔너리나 리스트 안에 숨어 있어도 찾아서 변환합니다.
    """
    if isinstance(data, pd.DataFrame):
        return data.to_dict(orient='split')  # DataFrame -> Dict 변환
    elif isinstance(data, dict):
        return {k: serialize_result(v) for k, v in data.items()} # 딕셔너리 내부 재귀 탐색
    elif isinstance(data, list):
        return [serialize_result(v) for v in data] # 리스트 내부 재귀 탐색
    return data

def code_executor(state: AgentState) -> dict:
    """
    생성된 코드 실행 및 결과 검증
    """
    code = state.get("generated_code")
    if not code:
        return {"code_execution_result": "실행할 코드를 찾을 수 없습니다."}

    retry_count = state.get("retry_count", 0)

    # LLM용 보안 DB 생성(민감한 컬럼을 제거)
    full_db = data_loader.load_master_data()
    secure_db = {}
    for name, df in full_db.items():
        # 원본 보존
        secure_db[name] = df.drop(columns=['description', 'vendor_name'], errors='ignore')

    # 실행 컨텍스트에 보안 DB 주입
    local_scope = {"DB": secure_db, "pd": pd}

    try:
        # TO DO: 배포 시에는 exec()를 별도 실행 컨테이너로 구성하기
        exec(code, {}, local_scope)

        # 결과 추출
        result = local_scope.get("result")

        if result is None:
            return {
                "code_execution_result": "코드는 실행되었으나 'result' 변수가 정의되지 않았습니다.",
                "retry_count": retry_count + 1
            }

        # 결과 직렬화 (DataFrame -> Dict 변환)
        # 그냥 result가 아니라, 딕셔너리 내부에 있는 DataFrame까지 찾아서 변환
        safe_result = serialize_result(result)

        # 실행 성공 반환
        return {
            "analysis_data": {"last_run_result": safe_result},  # 변환된 safe_result 저장
            "code_execution_result": None,
            "messages": [AIMessage(content=f"분석이 완료되었습니다.")]
            # (옵션: result 내용을 텍스트로 다 찍으면 너무 기니까 멘트만 남김)
        }

    except Exception as e:
        return {
            "code_execution_result": str(e),
            "retry_count": retry_count + 1
        }


def finalize_order(state: AgentState) -> dict:
    """
    발주 결과를 반영하여 실제 DB 저장을 수행하는 노드
    """
    data = state.get("analysis_data", {})
    # 실제 DB 저장 로직 (Mock)
    return {"messages": [AIMessage(content="발주 정보를 데이터베이스에 저장하였습니다.")], "waiting_for_approval": False}