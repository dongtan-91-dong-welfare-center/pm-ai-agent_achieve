import pandas as pd
from langchain_core.messages import AIMessage, SystemMessage, HumanMessage
from langchain_core.runnables import chain

# 모듈 임포트
import data_loader
from agent_state import AgentState
from agent_config import llm, chain_prompt_llm

# Python 실행 환경 준비
RUN_CONTEXT = {"DB": data_loader.load_master_data(), "pd": pd}


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
    code_gen_prompt = """
    당신은 생산 관리 데이터를 분석하는 Python 전문가입니다.
    주어진 질문을 해결하기 위해 'DB' 딕셔너리에 있는 Pandas DataFrame을 사용하는 코드를 작성하세요.
    변수 'result'에 최종 결과를 할당해야 합니다.
    """

    if last_error and generated_code:
        user_msg = f"이전 코드 에러 발생:\n{last_error}\n코드를 수정해주세요."
    else:
        user_msg = "분석 코드를 작성해주세요."

    msg_history = [SystemMessage(content=code_gen_prompt)] + messages + [HumanMessage(content=user_msg)]
    response = llm.invoke(msg_history)

    # 코드를 추출하는 로직
    code = response.content.replace("```python", "").replace("```", "").strip()
    return {"generated_code": code}


def code_executor(state: AgentState) -> dict:
    """
    생성된 코드 실행 및 결과 검증
    """
    code = state.get("generated_code")
    retry_count = state.get("retry_count", 0)

    if not code:
        return {"code_execution_result": "실행할 코드를 찾을 수 없습니다."}

    try:
        local_scope = RUN_CONTEXT.copy()
        # TO DO: 배포 시에는 exec()를 별도 실행 컨테이너로 구성하기
        exec(code, {}, local_scope)
        # 결과 추출
        result = local_scope.get("result")
        return {
            "analysis_data": {"last_run_result": result},
            "code_execution_result": None,
            "messages": [AIMessage(content=f"분석 결과:\n{result}")]
        }
    except Exception as e:
        return {"code_execution_result": str(e), "retry_count": retry_count + 1}


def finalize_order(state: AgentState) -> dict:
    """
    발주 결과를 반영하여 실제 DB 저장을 수행하는 노드
    """
    data = state.get("analysis_data", {})
    # 실제 DB 저장 로직 (Mock)
    return {"messages": [AIMessage(content="발주 정보를 데이터베이스에 저장하였습니다.")], "waiting_for_approval": False}