from typing import List
from langchain_core.tools import tool
from pydantic import BaseModel, Field

class PurchaseOrderInput(BaseModel):
    product_list: List[str] = Field(description="발주량 계산 대상 품목 목록")

@tool("calculate_optimal_purchase_order", args_schema=PurchaseOrderInput)
def calculate_optimal_purchase_order(product_list: List[str]) -> str:
    """[Func-131] 적정 발주량을 산출합니다."""
    # Mock 구현
    return f"{product_list}에 대한 발주량 계산 완료: 각 100개."