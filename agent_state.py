from typing import TypedDict, Annotated, List, Optional, Dict, Any
from langgraph.graph.message import add_messages
from langchain_core.messages import BaseMessage
from pydantic import BaseModel, Field

# 그래프 상태 (State)
class AgentState(TypedDict):
    messages: Annotated[List[BaseMessage], add_messages]
    current_plan_id: Optional[str]
    analysis_data: Dict[str, Any]
    generated_code: Optional[str]
    code_execution_result: Optional[str]
    waiting_for_approval: bool
    retry_count: int

# 라우팅용 데이터 모델 (Pydantic)
class PythonAnalysisRequest(BaseModel):
    """복잡한 데이터 분석, 계산, 그래프 생성이 필요할 때 이 도구를 호출하세요."""
    description: str = Field(description="분석할 내용에 대한 상세 설명")

class FinalizeOrderRequest(BaseModel):
    """모든 분석이 끝나고, 사용자가 발주를 승인했을 때 최종적으로 이 도구를 호출하여 DB에 저장합니다."""
    confirm_message: str = Field(description="발주 확정에 대한 최종 요약 메시지")