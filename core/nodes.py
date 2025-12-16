"""
파일명: core/nodes.py
설명: LangGraph 워크플로우를 구성하는 개별 노드(Node) 및 라우팅(Routing) 로직의 통합 구현체
수정사항:
1. reasoner 함수 내 모든 반환값을 ensure_messages_list로 감싸서 TypeError 방지
2. serialize_result 함수에 Matplotlib Figure -> Base64 변환 로직 포함
"""

import io
import base64
from typing import Literal, Any
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt

from langchain_core.messages import AIMessage, SystemMessage, HumanMessage, ToolMessage

# 내부 모듈 Import
from .state import AgentState
from . import config
from data_loader import TABLE_SCHEMA
from .prompt import format_schema_for_prompt, CODE_GEN_SYSTEM_PROMPT
from interface.formatting import format_analysis_result, format_thinking_process
import tools

# __all__ 정의
__all__ = [
    'reasoner', 'route_reasoner', 'route_after_execution',
    'code_generator', 'code_executor',
    'finalize_order', 'hil_approval', 'serialize_result'
]


# -------------------------------------------------------------------------
# 1. Helper Functions (유틸리티)
# -------------------------------------------------------------------------

def serialize_result(data: Any) -> Any:
    """
    [Data Serialization]
    Code Executor 결과물을 JSON 직렬화 가능한 형태로 변환합니다.
    """
    # 1. Matplotlib 객체 처리 (Figure/Axes -> Base64)
    target_fig = None
    if hasattr(data, "savefig"): target_fig = data
    elif hasattr(data, "get_figure"): target_fig = data.get_figure()
    elif isinstance(data, (list, tuple)) and len(data) > 0:
        if hasattr(data[0], "savefig"): target_fig = data[0]
        elif hasattr(data[0], "get_figure"): target_fig = data[0].get_figure()

    if target_fig:
        try:
            buf = io.BytesIO()
            # 그래프의 크기는 가로 10인치, 세로 6인치
            target_fig.set_size_inches(10, 6)
            # DPI 설정: 100DPI (10인치 * 100 = 1000px 너비)
            # 결과적으로 약 1000 x 600 픽셀의 이미지 생성
            target_fig.savefig(buf, format='png', bbox_inches='tight')

            buf.seek(0)
            img_str = base64.b64encode(buf.read()).decode('utf-8')
            plt.close(target_fig)
            return {"type": "image_base64", "data": img_str}
        except Exception as e:
            return f"이미지 변환 실패: {str(e)}"

    # 2. Pandas DataFrame -> Dict
    if isinstance(data, pd.DataFrame):
        return {
            "type": "dataframe",
            "data": data.to_dict(orient='split'),
            "columns": data.columns.tolist()
        }

    # 3. Pandas Series -> Dict
    elif isinstance(data, pd.Series):
        return data.to_dict()

    # 4. NumPy Types
    elif isinstance(data, (np.integer, np.int64)):
        return int(data)
    elif isinstance(data, (np.floating, np.float64)):
        return float(data)
    elif isinstance(data, np.bool_):
        return bool(data)
    elif isinstance(data, np.ndarray):
        return data.tolist()

    # 5. Recursive Handling
    elif isinstance(data, dict):
        return {k: serialize_result(v) for k, v in data.items()}
    elif isinstance(data, list):
        return [serialize_result(v) for v in data]

    return data


def ensure_messages_list(result: dict) -> dict:
    """
    [Safety Guard]
    LangGraph의 State 업데이트 시 'messages' 필드가 반드시 리스트(List) 형태가 되도록 보장합니다.
    """
    if not isinstance(result, dict):
        return result
    msgs = result.get('messages', None)
    if msgs is None:
        return result

    # 이미 리스트라면 패스
    if isinstance(msgs, list):
        return result

    # 단일 객체(또는 문자열)라면 리스트로 래핑
    result['messages'] = [msgs]
    return result


# -------------------------------------------------------------------------
# 2. Main Logic Nodes (핵심 노드)
# -------------------------------------------------------------------------

def reasoner(state: AgentState) -> dict:
    """
    [Node: Reasoner] - The Brain (Safe Version)
    사용자의 입력을 해석하고, 대화의 맥락을 관리하며, 최종 답변을 생성하는 진입점입니다.
    """
    print("--- NODE: Reasoner ---")
    messages = state.get("messages", [])

    if not messages:
        return ensure_messages_list({"messages": [AIMessage(content="안녕하세요! 생산 관리 AI Agent입니다.")]})

    last_message = messages[-1]

    # ---------------------------------------------------------------------
    # [Logic 1] 실행 상태(Execution Status) 기반 처리 (Reporting)
    # ---------------------------------------------------------------------

    # (1-1) 에러 발생 시 사용자 보고
    if state.get("execution_status") == "error":
        error_msg = state.get("code_execution_result", "알 수 없는 오류")
        return ensure_messages_list({
            "messages": [AIMessage(content=f"작업을 수행하는 도중 오류가 발생했습니다.\n(내용: {error_msg})")],
            "execution_status": "done"
        })

    # (1-2) Code Executor 실행 성공 후 보고
    if state.get("execution_status") == "success" and state.get("analysis_data"):
        result_data = state["analysis_data"].get("last_run_result", "결과 없음")
        formatted_result = format_analysis_result(result_data, "분석 결과")

        # 결과만 깔끔하게 출력
        return ensure_messages_list({
            "messages": [AIMessage(content=formatted_result)],
            "execution_status": "done",
            "user_approval_pending": True
        })

    # ---------------------------------------------------------------------
    # [Logic 2] 메시지 타입 기반 처리 (Reasoning)
    # ---------------------------------------------------------------------

    # (2-1) 도구 실행 완료 후 (ToolMessage) -> 결과를 해석하여 최종 답변 생성
    # [수정 포인트] 여기서 리스트 래핑이 누락되지 않도록 주의
    if isinstance(last_message, ToolMessage) or (hasattr(last_message, "tool_call_id") and last_message.tool_call_id) or last_message.type == "tool":
        print(">>> Analyzing Tool Result...")
        try:
            if getattr(config, 'chain_prompt_llm', None) is not None:
                response = config.chain_prompt_llm.invoke({"messages": messages})
            else:
                response = config.llm.invoke({"messages": messages})

            # [안전 장치] response가 문자열일 경우 AIMessage로 변환
            if isinstance(response, str):
                response = AIMessage(content=response)

            return ensure_messages_list({"messages": [response]})
        except Exception as e:
             return ensure_messages_list({"messages": [AIMessage(content=f"결과 해석 중 오류: {e}")]})

    # (2-2) 사용자의 새로운 질문 (HumanMessage) -> LLM 호출
    if isinstance(last_message, HumanMessage):
        # 새로운 대화 감지 로직
        new_convo_keywords = ["새로운", "처음", "초기화", "reset", "다시 시작"]
        last_text = (getattr(last_message, 'content', '') or '').lower()
        is_new_conversation = any(k in last_text for k in new_convo_keywords)

        if is_new_conversation:
            print(">>> New Interaction Detected: Full Reset of State...")

        try:
            # LLM 호출
            if getattr(config, 'chain_prompt_llm', None) is not None:
                response = config.chain_prompt_llm.invoke({"messages": messages})
            else:
                response = config.llm.invoke({"messages": messages})

            # [우선순위 1] Tool Call 감지
            if hasattr(response, 'tool_calls') and response.tool_calls:
                print(f">>> LLM Generated Tool Calls: {len(response.tool_calls)}")

                base_update = {
                    "messages": [response],
                    "execution_status": None,
                }

                if is_new_conversation:
                    base_update["analysis_data"] = {}

                return ensure_messages_list(base_update)

            # [우선순위 2] 일반 대화 처리
            final_response = response
            if isinstance(response, str):
                final_response = AIMessage(content=response)
            elif hasattr(response, "content") and hasattr(response, "type"):
                final_response = response
            else:
                final_response = AIMessage(content=str(response))

            if is_new_conversation:
                return ensure_messages_list({
                    "messages": [final_response],
                    "execution_status": None,
                    "analysis_data": {},
                    "generated_code": None,
                    "code_execution_result": None,
                    "retry_count": 0,
                    "thinking_steps": [],
                    "user_approval_pending": False,
                    "user_approval_decision": None,
                    "user_feedback": None
                })

            return ensure_messages_list({
                "messages": [final_response],
                "generated_code": None,
                "execution_status": None,
                "code_execution_result": None,
                "retry_count": 0,
                "thinking_steps": []
            })

        except Exception as e:
            print(f"❌ LLM invocation error: {str(e)}")
            return ensure_messages_list({
                "messages": [AIMessage(content=f"시스템 오류: {str(e)}")],
                "execution_status": "error"
            })

    # ---------------------------------------------------------------------
    # [Logic 3] Fallback
    # ---------------------------------------------------------------------
    return ensure_messages_list({"messages": [AIMessage(content="다음 작업을 진행할 수 없습니다.")]})


def code_generator(state: AgentState) -> dict:
    """
    [Node: Code Generator]
    """
    print("--- NODE: Code Generator ---")
    messages = state["messages"]
    execution_status = state.get("execution_status")
    error_message = state.get("code_execution_result")
    retry_count = state.get("retry_count", 0)

    user_message = next(
        (msg for msg in reversed(messages) if isinstance(msg, HumanMessage)),
        None
    )
    user_question = user_message.content if user_message else "질문을 찾을 수 없습니다."

    schema_context = format_schema_for_prompt(TABLE_SCHEMA)
    system_content = CODE_GEN_SYSTEM_PROMPT.format(
        schema_context=schema_context,
        user_question=user_question
    )

    if execution_status == "error" and error_message:
        print(f">>> Retry #{retry_count}: Generating corrected code...")
        correction_instruction = (
            f"\n\n[⚠️ 이전 코드 실행 실패]\n"
            f"이전 코드가 다음 오류로 인해 실행되지 않았습니다:\n{error_message}\n"
            f"이 오류를 해결하도록 코드를 수정하여 다시 작성해주세요."
        )
        system_content += correction_instruction

    try:
        response = config.llm.invoke([
            SystemMessage(content=system_content),
            HumanMessage(content=user_question)
        ])

        raw_content = response.content
        generated_code = ""

        if "```python" in raw_content:
            generated_code = raw_content.split("```python")[1].split("```")[0].strip()
        elif "```" in raw_content:
            generated_code = raw_content.split("```")[1].split("```")[0].strip()
        else:
            if "import " in raw_content or "=" in raw_content:
                generated_code = raw_content.strip()
            else:
                return {
                    "execution_status": "error",
                    "code_execution_result": "AI가 유효한 Python 코드를 생성하지 않았습니다.",
                    "retry_count": retry_count + 1
                }

        if not generated_code:
             return {
                "execution_status": "error",
                "code_execution_result": "생성된 코드가 비어 있습니다.",
                "retry_count": retry_count + 1
            }

        print(f"✓ Code Generated (retry_count={retry_count})")
        return {"generated_code": generated_code}

    except Exception as e:
        error_msg = f"코드 생성 중 오류: {str(e)}"
        print(f"❌ {error_msg}")
        return {
            "execution_status": "error",
            "code_execution_result": error_msg,
            "retry_count": retry_count + 1
        }


def code_executor(state: AgentState) -> dict:
    """
    [Node: Code Executor]
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

    global_context = {
        "pd": pd, "np": np, "plt": plt,
        "tools": tools, "DB": tools.DB,
    }

    if tools.DB:
        for table_name, df in tools.DB.items():
            global_context[f"df_{table_name}"] = df

    try:
        local_context = {}
        exec(generated_code, global_context, local_context)

        if 'result' not in local_context:
            return {
                "execution_status": "error",
                "code_execution_result": "코드에서 'result' 변수가 정의되지 않았습니다.",
                "retry_count": retry_count + 1
            }

        execution_result = local_context.get("result")

        return {
            "analysis_data": {"last_run_result": serialize_result(execution_result)},
            "execution_status": "success",
            "code_execution_result": "성공",
            "retry_count": 0
        }

    except Exception as e:
        error_msg = str(e)
        print(f"!!! Execution Error: {error_msg}")
        return {
            "execution_status": "error",
            "code_execution_result": error_msg,
            "retry_count": retry_count + 1
        }


# -------------------------------------------------------------------------
# 3. Router Logic (분기 제어)
# -------------------------------------------------------------------------

def route_reasoner(state: AgentState) -> str:
    messages = state.get("messages", [])
    if not messages:
        return "__end__"

    last_message = messages[-1]

    if hasattr(last_message, "tool_calls") and last_message.tool_calls:
        first_tool = last_message.tool_calls[0]
        tool_name = first_tool["name"]

        print(f">>> [Reasoner Router] Tool Call: {tool_name}")

        if tool_name == "PythonAnalysisRequest":
            return "code_generator"
        if tool_name == "FinalizeOrderRequest":
            return "finalize_order"

        return "tools"

    return "__end__"


def route_after_execution(state: AgentState) -> Literal["success", "retry", "max_retries"]:
    status = state.get("execution_status")
    retry_count = state.get("retry_count", 0)
    MAX_RETRIES = 3

    if status == "success":
        return "success"

    if status == "error":
        if retry_count < MAX_RETRIES:
            return "retry"
        else:
            return "max_retries"

    return "success"


# -------------------------------------------------------------------------
# 4. Action & HIL Nodes (실행 및 승인)
# -------------------------------------------------------------------------

def finalize_order(state: AgentState) -> dict:
    """[Node: Finalize Order]"""
    # (이전과 동일하여 생략 가능하나 안전을 위해 기본 형태 반환)
    return ensure_messages_list({
        "messages": [AIMessage(content="발주 확정 기능은 현재 구현 중입니다.")],
        "execution_status": "done"
    })

def hil_approval(state: AgentState) -> dict:
    """[Node: HIL Approval]"""
    return {"user_approval_pending": False}