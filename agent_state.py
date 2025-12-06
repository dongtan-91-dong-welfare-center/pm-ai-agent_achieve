from typing import TypedDict, Annotated, List, Optional, Dict, Any
from langgraph.graph.message import add_messages
from langchain_core.messages import BaseMessage
from pydantic import BaseModel, Field


class AgentState(TypedDict):
    """LangGraph 상태 정의"""
    messages: Annotated[List[BaseMessage], add_messages]
    generated_code: Optional[str]  # Code Generator가 생성한 Python 코드
    analysis_data: Dict[str, Any]  # Code Executor의 실행 결과
    execution_status: Optional[str]  # "success" | "error" | "done" (상태 머신)
    code_execution_result: Optional[str]  # 실행 결과 또는 에러 메시지
    retry_count: int  # 자동 재시도 횟수 (최대 3회)


class PythonAnalysisRequest(BaseModel):
    """복잡한 데이터 분석/계산 요청 → Code Generator로 라우팅"""
    description: str = Field(description="분석할 내용에 대한 상세 설명")


class FinalizeOrderRequest(BaseModel):
    """발주 최종 확정 요청 → Finalize Order로 라우팅"""
    confirm_message: str = Field(description="발주 확정에 대한 최종 요약 메시지")