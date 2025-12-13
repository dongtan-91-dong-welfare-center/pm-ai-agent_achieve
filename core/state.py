"""
[Role & Responsibility]
- 이 모듈은 시스템 전체에서 공유되는 '단일 진실 공급원(Single Source of Truth)' 역할을 합니다.
- Node 간 데이터 전달, 재시도 카운트, 실행 결과 등을 관리합니다.
- HumanMessage 감지 시 `analysis_data` 등 일부 상태는 초기화되어야 함을 유의하십시오 (컨텍스트 꼬임 방지).
"""

from typing import TypedDict, Annotated, List, Dict, Any, Optional
from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages
from pydantic import BaseModel, Field


# -------------------------------------------------------------------------
# 1. Agent State Definition (전역 상태 관리)
# -------------------------------------------------------------------------
class AgentState(TypedDict):
    """
    LangGraph의 각 노드(Node)가 공유하고 업데이트하는 상태 객체입니다.

    Attributes:
        messages (List[BaseMessage]):
            - 사용자와 에이전트 간의 모든 대화 기록입니다.
            - `add_messages` 리듀서를 사용하여, 기존 리스트를 덮어쓰지 않고 새 메시지를 append 합니다.
            - LLM의 Context Window 관리를 위해 오래된 메시지는 트림(Trim) 될 수 있습니다.

        execution_status (str):
            - 현재 워크플로우의 실행 상태를 나타냅니다.
            - 값 예시: 'start', 'analyzing', 'coding', 'executing', 'success', 'error', 'retry_needed'
            - UI에서 스피너(Spinner)나 상태 바를 표시하는 기준으로 사용됩니다.

        analysis_data (Dict[str, Any]):
            - [중요] Code Executor가 실행한 결과 데이터(DataFrame, JSON 등)를 저장합니다.
            - 보안(Adr-007): 원본 데이터는 로컬 메모리에만 로드되며, LLM에게는 이 데이터의 요약이나 스키마만 전달됩니다.
            - 생명주기: 사용자의 새로운 질문(HumanMessage)이 들어오면, 이전 분석 결과와의 혼동을 막기 위해 초기화(Reset) 되어야 합니다.

        generated_code (str):
            - Code Generator 노드(LLM)가 생성한 Python 실행 코드입니다.
            - LLM은 데이터 스키마를 기반으로 이 코드를 작성합니다.

        code_execution_result (str):
            - Code Executor 노드(Local Python)가 `generated_code`를 실행한 표준 출력(Stdout) 또는 에러 메시지입니다.
            - 에러 발생 시, 이 메시지는 다시 Reflector(Self-Correction) 노드로 전달되어 코드 수정의 근거가 됩니다.

        retry_count (int):
            - 실행 오류 발생 시 재시도 횟수를 추적합니다.
            - `MAX_RETRIES` 설정값(예: 3회)에 도달하면 재시도를 멈추고 에러를 사용자에게 보고합니다.

        thinking_steps (List[Dict[str, Any]]):
            - 에이전트의 의사결정 과정(Reasoning)을 단계별로 기록합니다.
            - 예: {"step": "plan", "content": "재고 부족분 계산을 위해 tools.py의 calc_shortage 함수 호출 예정"}
            - XAI(Explainable AI) 및 디버깅 용도로 활용됩니다.

        user_approval_pending (bool):
            - [HIL] 민감한 작업(예: 발주 확정) 전 사용자의 승인이 필요한지 여부입니다.
            - True일 경우 워크플로우는 `interrupt_before` 지점에서 멈추고 사용자 입력을 대기합니다.

        user_approval_decision (str):
            - 사용자의 승인/반려 결과입니다 ('approve', 'reject', 'modify').

        user_feedback (str):
            - 사용자가 HIL 단계에서 입력한 수정 사항이나 피드백 텍스트입니다.
            - 반려 시 이 내용을 바탕으로 계획을 수정합니다.
    """

    # 메시지 기록 (add_messages 리듀서를 통해 리스트에 계속 추가됨)
    messages: Annotated[List[BaseMessage], add_messages]

    # 실행 상태 ('success', 'error', 'retry' 등)
    execution_status: Optional[str]

    # 분석 결과 데이터 (DataFrame 직렬화 결과 등 - HumanMessage 시 초기화 권장)
    analysis_data: Optional[Dict[str, Any]]

    # 생성된 Python 코드 (LLM이 작성)
    generated_code: Optional[str]

    # 코드 실행 결과 메시지 또는 에러 로그 (Local Exec 결과)
    code_execution_result: Optional[str]

    # 재시도 횟수 (Self-Correction 임계치 확인용)
    retry_count: int

    # Chain of Thought - 단계별 생각 과정 (UI 표시 및 로그용)
    thinking_steps: List[Dict[str, Any]]

    # Human-in-the-Loop (HIL) 승인 대기 여부
    user_approval_pending: Optional[bool]

    # HIL 승인 결과 (approve, reject, modify)
    user_approval_decision: Optional[str]

    # 사용자 입력 (HIL에서 수정 사항이나 피드백)
    user_feedback: Optional[str]


# -------------------------------------------------------------------------
# 2. Tool Pydantic Models (Structured Output for Routing)
# -------------------------------------------------------------------------

class PythonAnalysisRequest(BaseModel):
    """
    [Router Node용] 사용자의 요청이 데이터 분석이나 계산이 필요한 경우 매핑되는 구조체입니다.

    용도:
        - LLM이 사용자의 자연어 질문을 해석하여 이 도구를 선택하면,
          워크플로우는 'Code Generator' 노드로 라우팅됩니다.

    주의사항 (Adr-008):
        - 단순 조회나 계산은 Code Gen을 타지만, 복잡한 비즈니스 로직(오버리지, MRP 등)은
          `tools.py`에 정의된 사전 정의 함수를 호출하도록 유도해야 합니다.
    """
    description: str = Field(
        description="분석, 데이터 조회, 혹은 계산해야 할 내용에 대한 구체적이고 상세한 설명 (Prompt Context 포함)"
    )


class FinalizeOrderRequest(BaseModel):
    """
    [End Node용] 분석 및 검토가 끝나고 최종 발주를 진행하려는 의도일 때 사용됩니다.

    용도:
        - 이 모델이 선택되면 워크플로우는 최종 보고서 생성 또는 시스템 저장 단계로 진입합니다.
    """
    confirm_message: str = Field(
        description="발주 확정 또는 프로세스 완료를 위한 메시지"
    )


class ApprovalDecision(BaseModel):
    """
    [HIL Interaction용] 중간 개입 단계에서 사용자의 의사결정을 캡처합니다.

    용도:
        - Streamlit UI 등 프론트엔드에서 사용자의 버튼 클릭이나 입력을 받아
          Graph의 상태(`user_approval_decision`, `user_feedback`)를 업데이트할 때 사용됩니다.
    """
    decision: str = Field(
        description="승인 결정: 'approve' (승인 - 진행), 'reject' (반려 - 중단/재계획), 'modify' (수정 - 피드백 반영)"
    )
    feedback: Optional[str] = Field(
        default=None,
        description="승인/반려 사유 또는 수정 요청사항 (LLM이 이를 반영하여 코드를 재생성함)"
    )