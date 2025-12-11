from typing import TypedDict, Annotated, List, Dict, Any, Optional
from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages
from pydantic import BaseModel, Field  # [수정] langchain_core.pydantic_v1 -> pydantic


# 1. Agent의 전체 상태(State) 정의
class AgentState(TypedDict):
    # 메시지 기록 (add_messages 리듀서를 통해 리스트에 계속 추가됨)
    messages: Annotated[List[BaseMessage], add_messages]

    # 실행 상태 ('success', 'error', 'retry' 등)
    execution_status: Optional[str]

    # 분석 결과 데이터 (DataFrame 직렬화 결과 등)
    analysis_data: Optional[Dict[str, Any]]

    # 생성된 Python 코드
    generated_code: Optional[str]

    # 코드 실행 결과 메시지 또는 에러 로그
    code_execution_result: Optional[str]

    # 재시도 횟수
    retry_count: int

    # Chain of Thought - 단계별 생각 과정
    thinking_steps: List[Dict[str, Any]]

    # Human-in-the-Loop (HIL) 승인 대기 여부
    user_approval_pending: Optional[bool]

    # HIL 승인 결과 (approve, reject, modify)
    user_approval_decision: Optional[str]

    # 사용자 입력 (HIL에서 수정 사항이나 피드백)
    user_feedback: Optional[str]


# 2. Tool용 Pydantic 모델 정의 (라우팅용)

class PythonAnalysisRequest(BaseModel):
    """
    복잡한 데이터 분석, 재고 조회, 계산, 발주량 산출 등이 필요할 때 사용합니다.
    """
    description: str = Field(
        description="분석하거나 계산해야 할 내용에 대한 상세 설명"
    )


class FinalizeOrderRequest(BaseModel):
    """
    사용자가 분석 결과를 확인한 후, 최종적으로 발주(저장)를 요청할 때 사용합니다.
    """
    confirm_message: str = Field(
        description="발주 확정 메시지"
    )


class ApprovalDecision(BaseModel):
    """
    사용자의 승인/반려 결정 (HIL - Human in the Loop)
    """
    decision: str = Field(
        description="승인 결정: 'approve' (승인), 'reject' (반려), 'modify' (수정)"
    )
    feedback: Optional[str] = Field(
        default=None,
        description="승인/반려 사유 또는 수정 요청사항"
    )