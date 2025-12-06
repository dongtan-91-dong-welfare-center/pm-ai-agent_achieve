from agent_state import AgentState
from langchain_core.messages import AIMessage

def route_reasoner(state: AgentState):
    """ Reasoner의 결정(Tool Call)을 보고 다음 노드를 결정합니다. """
    messages = state.get("messages", [])
    last_message = messages[-1]

    # 도구 호출이 없는 경우 (일반 대화) -> 바로 종료하여 답변 출력
    if not isinstance(last_message, AIMessage) or not last_message.tool_calls:
        return "__end__"

    # 도구 이름 확인
    tool_name = last_message.tool_calls[0]["name"]

    if tool_name == "PythonAnalysisRequest":
        # 코드 생성
        return "code_generator"
    if tool_name == "FinalizeOrderRequest":
        # 발주 확정 노드로 이동
        return "finalize_order"

    # return "tools"
    return "__end__"


def route_after_execution(state: AgentState):
    """Code Executor의 실행 결과를 보고 재시도 여부를 결정합니다. """

    # agent_nodes.py의 code_executor가 반환하는 키("execution_status") 사용
    status = state.get("execution_status", "success")
    retry_count = state.get("retry_count", 0)

    # 실행 실패 시 재시도 로직
    if status == "failed":
        # 3회 미만이면 재시도 (Code Generator로 돌아가서 코드 수정 요청)
        if retry_count < 3:
            return "retry"
        # 3회 초과 시 포기 (Reasoner로 돌아가서 "실패" 보고)
        else:
            return "max_retries"

    # 성공 시 Reasoner로 돌아가서 결과 보고
    return "success"