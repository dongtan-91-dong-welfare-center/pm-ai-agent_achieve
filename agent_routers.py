from agent_state import AgentState


def route_reasoner(state: AgentState):
    messages = state.get("messages", [])
    last_message = messages[-1]

    if not last_message.tool_calls:
        return "__end__"

    tool_name = last_message.tool_calls[0]["name"]

    if tool_name == "PythonAnalysisRequest":
        return "code_generator"
    if tool_name == "FinalizeOrderRequest":
        return "finalize_order"

    return "tools"


def route_after_execution(state: AgentState):
    error = state.get("code_execution_result")
    retry_count = state.get("retry_count", 0)

    if error:
        return "max_retries" if retry_count >= 3 else "retry"
    return "success"