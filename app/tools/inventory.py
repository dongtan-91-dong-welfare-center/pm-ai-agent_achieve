from typing import List, Optional
from langchain_core.tools import tool
from pydantic import BaseModel, Field

class InventoryAnalysisInput(BaseModel):
    analysis_period: str = Field(description="분석할 기간 (예: 'monthly', '2025-10')")
    exclude_items: Optional[List[str]] = Field(None, description="분석 제외 품목 코드")

@tool("analyze_long_term_inventory", args_schema=InventoryAnalysisInput)
def analyze_long_term_inventory(analysis_period: str, exclude_items: Optional[List[str]] = None) -> str:
    """[Func-121] 장기 재고 현황을 분석하여 결과를 반환합니다."""
    # Mock 구현
    return f"[{analysis_period}] 분석 완료. 장기 재고 3건 발견 (A, B, C)."