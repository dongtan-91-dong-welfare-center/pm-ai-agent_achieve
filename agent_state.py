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