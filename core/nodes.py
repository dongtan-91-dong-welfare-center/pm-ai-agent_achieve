"""
설명: LangGraph 워크플로우를 구성하는 개별 노드(Node) 및 라우팅(Routing) 로직의 통합 구현체

[Role & Responsibility]
- Context Management: HumanMessage 감지 시 대화 맥락(Analysis Data)을 초기화하여 환각을 방지합니다.
"""

from typing import Literal, Any
import pandas as pd
import numpy as np
from langchain_core.messages import AIMessage, SystemMessage, HumanMessage

# 내부 모듈 Import
from .state import AgentState
from . import config
from data_loader import TABLE_SCHEMA
from .prompt import format_schema_for_prompt, CODE_GEN_SYSTEM_PROMPT
from interface.formatting import format_analysis_result, format_thinking_process
import tools

# __all__ 정의: 외부(graph.py)에서 가져다 쓸 함수들 명시
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
    Code Executor가 생성한 복잡한 객체(DataFrame, Series, NumPy)를
    JSON 직렬화 가능한 Python 기본 타입(dict, list, int, float)으로 변환합니다.

    Why: LangGraph의 State는 체크포인트 저장 시 JSON 호환성이 필요하기 때문입니다.
    """
    # pandas dataframe -> dict (split orientation: index, columns, data 분리)
    if isinstance(data, pd.DataFrame):
        return {
            "type": "dataframe",
            "data": data.to_dict(orient='split'),
            "columns": data.columns.tolist()
        }
    # Pandas Series -> Dict
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
    # Recursive Handling (Dict / List 내부 탐색)
    elif isinstance(data, dict):
        return {k: serialize_result(v) for k, v in data.items()}
    elif isinstance(data, list):
        return [serialize_result(v) for v in data]

    # 변환 불필요 시 원본 반환
    return data


def ensure_messages_list(result: dict) -> dict:
    """
    [Safety Guard]
    LangGraph의 State 업데이트 시 'messages' 필드가 반드시 리스트(List) 형태가 되도록 보장합니다.
    단일 Message 객체가 들어오면 리스트로 감싸서 TypeError를 방지합니다.
    """
    if not isinstance(result, dict):
        return result
    msgs = result.get('messages', None)
    if msgs is None:
        return result

    # 이미 리스트라면 패스
    if isinstance(msgs, list):
        return result

    # 단일 객체라면 리스트로 래핑
    result['messages'] = [msgs]
    return result


# -------------------------------------------------------------------------
# 2. Main Logic Nodes (핵심 노드)
# -------------------------------------------------------------------------

def reasoner(state: AgentState) -> dict:
    """
    [Node: Reasoner] - The Brain
    사용자의 입력을 해석하고, 대화의 맥락을 관리하며, 최종 답변을 생성하는 진입점입니다.

    Key Features:
        1. Context Reset: 사용자가 새로운 주제(New Turn)를 시작하면 이전 분석 데이터(analysis_data)를 초기화합니다.
        2. Tool Result Interpretation: 도구 실행 결과를 바탕으로 최종 답변을 작성합니다.
        3. Error Reporting: 실행 중 발생한 에러를 사용자 친화적인 메시지로 변환합니다.
    """
    print("--- NODE: Reasoner ---")
    messages = state.get("messages", [])

    # 1. 초기 진입 처리 (Empty Message)
    if not messages:
        return {"messages": [AIMessage(content="안녕하세요! 생산 관리 AI Agent입니다. 무엇을 도와드릴까요?")]}

    last_message = messages[-1]

    # [핵심 로직 1] 새로운 사용자 질문(HumanMessage) 감지 및 상태 초기화
    # 사용자가 질문을 던졌다는 것은, 이전 분석 결과가 더 이상 유효하지 않을 수 있음을 의미합니다.
    if isinstance(last_message, HumanMessage):
        # 명시적인 초기화 키워드 확인 (Optional)
        new_convo_keywords = ["새로운", "처음", "초기화", "reset", "다시 시작", "새로 시작", "처음으로"]
        last_text = (getattr(last_message, 'content', '') or '').lower()
        is_new_conversation = any(k in last_text for k in new_convo_keywords)

        if is_new_conversation:
            print(">>> New Interaction Detected: Full Reset of State...")

        try:
            # LLM 호출 (Context Window에는 이전 대화 내용이 포함됨)
            if getattr(config, 'chain_prompt_llm', None) is not None:
                response = config.chain_prompt_llm.invoke({"messages": messages})
            else:
                response = config.llm.invoke({"messages": messages})

            # 응답 타입 안전성 확보
            final_response = response
            if isinstance(response, str):
                final_response = AIMessage(content=response)
            elif hasattr(response, "content") and hasattr(response, "type"):
                final_response = response
            else:
                final_response = AIMessage(content=str(response))

            # [상태 관리전략] HumanMessage가 들어왔을 때의 State Update
            if is_new_conversation:
                return ensure_messages_list({
                    "messages": [final_response],
                    "execution_status": None,
                    "analysis_data": {},  # [중요] 이전 데이터 클리어
                    "generated_code": None,
                    "code_execution_result": None,
                    "retry_count": 0,
                    "thinking_steps": [],
                    "user_approval_pending": False,
                    "user_approval_decision": None,
                    "user_feedback": None
                })

            # 일반 대화(Multi-turn)에서도 실행 관련 상태는 리셋
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
                "execution_status": None,
                "retry_count": 0
            })

    # [핵심 로직 2] Code Executor가 성공적으로 데이터를 가져온 후 (Reporting)
    if state.get("execution_status") == "success" and state.get("analysis_data"):
        result_data = state["analysis_data"].get("last_run_result", "결과 없음")

        # 결과 포맷팅 (Markdown Table 등)
        formatted_result = format_analysis_result(result_data, "분석 결과")

        # CoT(Chain of Thought) 로그 포맷팅
        thinking_steps = state.get("thinking_steps", [])
        thinking_output = ""
        if thinking_steps:
            thinking_output = format_thinking_process(thinking_steps)

        final_message = thinking_output + "\n\n" + formatted_result

        return ensure_messages_list({
            "messages": [AIMessage(content=final_message)],
            "execution_status": "done",
            "user_approval_pending": True  # HIL 승인 대기 가능 상태로 전환
        })

    # [핵심 로직 3] 에러 발생 시 사용자 보고
    if state.get("execution_status") == "error":
        error_msg = state.get("code_execution_result", "알 수 없는 오류")
        return ensure_messages_list({
            "messages": [AIMessage(content=f"작업을 수행하는 도중 오류가 발생했습니다.\n(내용: {error_msg})")],
            "execution_status": "done"
        })

    # Tool Call 후처리 (ToolMessage가 마지막일 경우 LLM 재호출)
    if hasattr(last_message, "tool_call_id") or last_message.type == "tool":
        response = config.chain_prompt_llm.invoke({"messages": messages})
        return ensure_messages_list({"messages": [response]})

    # Fallback
    return ensure_messages_list({"messages": [AIMessage(content="다음 작업을 진행할 수 없습니다.")]})


def code_generator(state: AgentState) -> dict:
    """
    [Node: Code Generator] - The Engineer
    사용자의 질문을 해결하기 위한 Python 코드(Pandas)를 생성합니다.

    Features:
        1. Schema-Only: Adr-007에 따라 실제 데이터가 아닌 스키마 정보만 프롬프트에 주입합니다.
        2. Self-Correction: 이전 실행에서 에러가 발생했다면, 에러 메시지를 포함하여 코드를 재생성(수정)합니다.
    """
    print("--- NODE: Code Generator ---")
    messages = state["messages"]
    execution_status = state.get("execution_status")
    error_message = state.get("code_execution_result")
    retry_count = state.get("retry_count", 0)

    # 사용자 질문 추출 (Context의 가장 마지막 HumanMessage)
    user_message = next(
        (msg for msg in reversed(messages) if isinstance(msg, HumanMessage)),
        None
    )
    user_question = user_message.content if user_message else "질문을 찾을 수 없습니다."

    # 스키마 정보 로드 및 포맷팅 (prompt.py 참조)
    schema_context = format_schema_for_prompt(TABLE_SCHEMA)

    # 시스템 프롬프트 구성
    system_content = CODE_GEN_SYSTEM_PROMPT.format(
        schema_context=schema_context,
        user_question=user_question
    )

    # [Self-Correction Logic] 재시도(Retry) 상황일 경우 에러 로그 주입
    if execution_status == "error" and error_message:
        print(f">>> Retry #{retry_count}: Generating corrected code...")
        correction_instruction = (
            f"\n\n[⚠️  이전 코드 실행 실패]\n"
            f"이전 코드가 다음 오류로 인해 실행되지 않았습니다:\n{error_message}\n"
            f"이 오류를 해결하도록 코드를 수정하여 다시 작성해주세요."
        )
        system_content += correction_instruction

    try:
        # Code Generation LLM 호출
        response = config.llm.invoke([
            SystemMessage(content=system_content),
            HumanMessage(content=user_question)
        ])

        # Markdown 코드 블록 파싱 (```python ... ``` 제거)
        generated_code = response.content.replace("```python", "").replace("```", "").strip()
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
    [Node: Code Executor] - The Worker
    생성된 Python 코드를 로컬 샌드박스 환경에서 실행합니다.

    Safety & Logic:
        1. exec(): 동적 코드 실행을 위해 Python 내장 exec 함수를 사용합니다.
        2. Global Context: 'tools', 'DB', 'pd' 등을 주입하여 코드가 활용할 수 있게 합니다.
        3. Result Capture: 코드 내에서 'result' 변수에 할당된 값을 추출하여 State에 저장합니다.
    """
    print("--- NODE: Code Executor ---")
    generated_code = state.get("generated_code", "")
    retry_count = state.get("retry_count", 0)
    thinking_steps = state.get("thinking_steps", [])

    if not generated_code:
        return {
            "execution_status": "error",
            "code_execution_result": "생성된 코드가 비어 있습니다.",
            "retry_count": retry_count
        }

    # CoT 기록: 준비
    thinking_steps.append({
        "step": len(thinking_steps) + 1,
        "action": "실행 환경 준비",
        "reason": "생성된 Python 코드를 안전한 샌드박스에서 실행하기 위함",
        "result": "진행 중"
    })

    # 실행 컨텍스트(Global Namespace) 설정
    global_context = {
        "pd": pd,
        "np": np,
        "tools": tools,  # Adr-008: 복잡한 로직은 tools 함수 호출
        "DB": tools.DB,  # In-Memory DB 접근
    }

    # DataFrame 단축 변수 주입 (예: df_product)
    missing_df_vars = []
    if tools.DB:
        for table_name, df in tools.DB.items():
            varname = f"df_{table_name}"
            global_context[varname] = df
            # 디버깅용: 변수명 확인
            if varname not in global_context:
                missing_df_vars.append(varname)

    try:
        # CoT 기록: 실행
        thinking_steps.append({
            "step": len(thinking_steps) + 1,
            "action": "코드 실행",
            "reason": "작성된 Python 코드를 실행하여 분석 결과 도출",
            "result": "진행 중"
        })

        # [Code Execution]
        local_context = {}
        exec(generated_code, global_context, local_context)

        # 'result' 변수 검증
        if 'result' not in local_context:
            thinking_steps.append({
                "step": len(thinking_steps) + 1,
                "action": "결과 검증",
                "reason": "'result' 변수 확인",
                "result": "❌ 실패 - result 변수 미정의"
            })
            return {
                "execution_status": "error",
                "code_execution_result": "코드에서 'result' 변수가 정의되지 않았습니다.",
                "retry_count": retry_count + 1,
                "thinking_steps": thinking_steps
            }

        execution_result = local_context.get("result")

        # CoT 기록: 성공
        thinking_steps.append({
            "step": len(thinking_steps) + 1,
            "action": "결과 처리",
            "reason": "분석 결과를 직렬화하여 상태에 저장",
            "result": "✅ 성공"
        })

        return {
            "analysis_data": {"last_run_result": serialize_result(execution_result)},
            "execution_status": "success",
            "code_execution_result": "성공",
            "retry_count": 0,
            "thinking_steps": thinking_steps
        }

    except Exception as e:
        # CoT 기록: 예외 발생
        error_msg = str(e)
        thinking_steps.append({
            "step": len(thinking_steps) + 1,
            "action": "코드 실행",
            "reason": "코드 실행 중 예외 발생",
            "result": f"❌ 실패 - {error_msg}"
        })
        print(f"!!! Execution Error: {error_msg}")

        return {
            "execution_status": "error",
            "code_execution_result": error_msg,
            "retry_count": retry_count + 1,
            "thinking_steps": thinking_steps
        }


# -------------------------------------------------------------------------
# 3. Router Logic (분기 제어)
# -------------------------------------------------------------------------

def route_reasoner(state: AgentState) -> str:
    """
    [Router] Reasoner의 결과(LLM의 Tool Call)를 보고 다음 노드를 결정합니다.

    Returns:
        - "code_generator": PythonAnalysisRequest (복잡 분석)
        - "finalize_order": FinalizeOrderRequest (발주 확정)
        - "tools": 기타 일반 도구 (재고 조회 등)
        - "__end__": 더 이상 할 일이 없음 (답변 완료)
    """
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
    """
    [Router] Code Executor의 실행 결과를 평가하여 재시도 여부를 결정합니다.

    Logic:
        - success: Reasoner로 돌아가서 결과 보고
        - error & retry_count < MAX: Code Generator로 돌아가서 코드 수정 (Self-Correction)
        - error & retry_count >= MAX: Reasoner로 돌아가서 실패 보고
    """
    status = state.get("execution_status")
    retry_count = state.get("retry_count", 0)
    MAX_RETRIES = 3

    print(f"--- [Execution Router] Status: {status}, Retries: {retry_count}/{MAX_RETRIES} ---")

    if status == "success":
        return "success"

    if status == "error":
        if retry_count < MAX_RETRIES:
            print(f">>> RETRY (Attempt {retry_count + 1}/{MAX_RETRIES})")
            return "retry"
        else:
            print(f">>> MAX RETRIES REACHED - GIVING UP")
            return "max_retries"

    return "success"


# -------------------------------------------------------------------------
# 4. Action & HIL Nodes (실행 및 승인)
# -------------------------------------------------------------------------

def finalize_order(state: AgentState) -> dict:
    """
    [Node: Finalize Order]
    분석 및 승인이 완료된 발주 데이터를 실제 시스템(DB/File)에 저장합니다.
    """
    print("--- NODE: Finalize Order ---")

    # [HIL Check] 승인되지 않은 상태면 중단
    if state.get("execution_status") != "approved" and state.get("user_approval_decision") != "approve":
        return {
            "messages": [AIMessage(content="발주 확정 전 사용자 승인이 필요합니다.")],
            "execution_status": None
        }

    # 데이터 추출
    analyze_data = state.get("analysis_data", {}) or {}
    last_result = analyze_data.get("last_run_result")

    if not last_result:
        return {
            "messages": [AIMessage(content="저장할 발주 데이터가 없습니다.")],
            "execution_status": "done"
        }

    try:
        # 데이터 정규화 (Dictionary List로 변환)
        po_rows = []
        if isinstance(last_result, dict) and last_result.get("type") == "dataframe":
            df = pd.DataFrame(**last_result.get("data", {}))
            po_rows = df.to_dict(orient='records')
        elif isinstance(last_result, list):
            po_rows = last_result
        elif isinstance(last_result, dict):
            po_rows = [last_result]
        else:
            return {
                "messages": [AIMessage(content="지원되지 않는 데이터 포맷입니다.")],
                "execution_status": "done"
            }

        # 데이터 저장 툴 호출
        from tools import submit_purchase_order_sync as submit_tool

        # 필수 필드 검증 및 포맷팅
        normalized_rows = []
        for row in po_rows:
            if isinstance(row, dict):
                # 컬럼 매핑 (LLM이 한글 컬럼을 쓸 경우 대비)
                product_id = row.get('product_id') or row.get('component_id') or row.get('품목코드')
                schedule_qty = row.get('schedule_qty') or row.get('required_qty') or row.get('발주필요량') or row.get('수량')
                vendor_id = row.get('vendor_id') or row.get('vendor') or row.get('공급업체')

                if not product_id or schedule_qty in [None, '', 0]:
                    continue  # 필수값 누락 시 스킵

                normalized = {
                    'po_id': row.get('po_id'),
                    'vendor_id': str(vendor_id) if vendor_id else '',
                    'product_id': str(product_id),
                    'po_date': pd.Timestamp.now().strftime('%Y-%m-%d'),
                    'schedule_qty': float(schedule_qty),
                    'received_qty': 0,
                    'delivery_date': row.get('납품일자') or ''
                }
                normalized_rows.append(normalized)

        if not normalized_rows:
            return {
                "messages": [AIMessage(content="유효한 발주 항목이 없습니다 (필수 컬럼 누락).")],
                "execution_status": "error"
            }

        res_msg = submit_tool(normalized_rows)
        success = not str(res_msg).startswith("저장 실패")

        # DB 리로드 (변경 사항 반영)
        import data_loader
        from tools import shared
        shared.DB = data_loader.load_master_data()

        if success:
            return ensure_messages_list({
                "messages": [
                    AIMessage(content=f"✅ 발주가 시스템에 반영되었습니다. {res_msg}"),
                    AIMessage(content="추가로 도와드릴까요?")
                ],
                "execution_status": "done"
            })
        else:
            return ensure_messages_list({
                "messages": [AIMessage(content=f"❌ 발주 저장 실패: {res_msg}")],
                "execution_status": "error"
            })

    except Exception as e:
        return ensure_messages_list({
            "messages": [AIMessage(content=f"발주 저장 중 예외 발생: {e}")],
            "execution_status": "error"
        })


def hil_approval(state: AgentState) -> dict:
    """
    [Node: HIL Approval] Human-in-the-Loop
    중요한 의사결정(발주 등) 전에 사용자의 승인을 대기하고 처리합니다.
    """
    print("--- NODE: Human-in-the-Loop Approval ---")

    # 1. 승인 대기 여부 체크
    if not state.get("user_approval_pending"):
        return {"user_approval_pending": False}

    # 2. 사용자 피드백 처리
    decision = state.get("user_approval_decision", "approve")
    feedback = state.get("user_feedback", "")

    if decision == "approve":
        return ensure_messages_list({
            "messages": [AIMessage(content="✅ 승인되었습니다. 후속 절차를 진행합니다.")],
            "user_approval_pending": False,
            "execution_status": "approved"
        })
    elif decision == "reject":
        return ensure_messages_list({
            "messages": [AIMessage(content=f"❌ 반려되었습니다. (사유: {feedback})")],
            "user_approval_pending": False,
            "execution_status": "rejected"
        })
    elif decision == "modify":
        return ensure_messages_list({
            "messages": [AIMessage(content=f"🔄 수정 요청이 접수되었습니다: {feedback}")],
            "user_approval_pending": False,
            "execution_status": None  # 재시작 트리거로 활용 가능
        })

    return {"user_approval_pending": False}