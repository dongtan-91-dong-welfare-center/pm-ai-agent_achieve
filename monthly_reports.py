"""
월말 구매 마감 리포트 및 자재 관리 리포트 생성 모듈

목적:
1. 월말 구매 마감 리포트: 해당 월의 구매 완료, 미완료, 예정 현황
2. 월별 자재 소요량 계산: 생산 계획 기반 BOM 전개를 통한 자재 소요량 산출
3. 발주 현황 공유 파일: 공급업체별, 자재별 발주 상태 조회
"""

import pandas as pd
from datetime import datetime, timedelta
from typing import Dict, List, Any, Tuple, Optional


class MonthlyReportGenerator:
    """월별 리포트 생성 클래스"""
    
    def __init__(self, db: Dict[str, pd.DataFrame]):
        """
        Args:
            db: 마스터 데이터 딕셔너리
               - product: 자재 마스터
               - purchase_order: 구매 오더
               - good_receipt: 입고 이력
               - purchase_transaction_history: 구매 상세 내역
               - bom: 자재 명세서
               - production_plan: 생산 계획
               - purchase_prediction: 발주 예측
        """
        self.db = db
        self.po_df = db.get("purchase_order", pd.DataFrame())
        self.receipt_df = db.get("good_receipt", pd.DataFrame())
        self.product_df = db.get("product", pd.DataFrame())
        self.bom_df = db.get("bom", pd.DataFrame())
        self.prod_plan_df = db.get("production_plan", pd.DataFrame())
        self.purchase_pred_df = db.get("purchase_prediction", pd.DataFrame())
    
    def get_monthly_purchase_closing_report(self, year: int, month: int) -> Dict[str, Any]:
        """
        월말 구매 마감 리포트 생성
        
        Args:
            year: 조회 년도
            month: 조회 월
        
        Returns:
            {
                'summary': 월말 구매 현황 요약,
                'completed': 완료된 발주,
                'in_progress': 진행 중인 발주,
                'scheduled': 예정된 발주,
                'cancelled': 취소된 발주,
                'statistics': 통계 정보
            }
        """
        # 해당 월의 PO 필터링
        target_date_start = pd.Timestamp(year=year, month=month, day=1)
        target_date_end = target_date_start + timedelta(days=32)  # 다음 달 2일
        target_date_end = target_date_end.replace(day=1) - timedelta(days=1)  # 마지막 날
        
        # PO 데이터 필터링
        try:
            po_df = self.po_df.copy()
            po_df["po_date"] = pd.to_datetime(po_df.get("po_date", []))
            po_filtered = po_df[
                (po_df["po_date"] >= target_date_start) & 
                (po_df["po_date"] <= target_date_end)
            ]
        except:
            po_filtered = pd.DataFrame()
        
        # 상태별 분류
        if not po_filtered.empty:
            # schedule_qty와 received_qty 비교
            po_filtered["status"] = po_filtered.apply(
                lambda row: "완료" if row.get("received_qty", 0) >= row.get("schedule_qty", 0) else "진행중",
                axis=1
            )
            
            completed = po_filtered[po_filtered["status"] == "완료"]
            in_progress = po_filtered[po_filtered["status"] == "진행중"]
        else:
            completed = pd.DataFrame()
            in_progress = pd.DataFrame()
        
        # 통계
        stats = {
            "총_발주건수": len(po_filtered),
            "완료_건수": len(completed),
            "진행중_건수": len(in_progress),
            "완료율_%": (len(completed) / len(po_filtered) * 100) if len(po_filtered) > 0 else 0,
            "총_발주금액": po_filtered.get("schedule_qty", pd.Series()).sum() if not po_filtered.empty else 0,
        }
        
        return {
            "summary": f"{year}년 {month}월 구매 마감 리포트",
            "completed": completed,
            "in_progress": in_progress,
            "statistics": stats,
            "query_period": f"{target_date_start.date()} ~ {target_date_end.date()}"
        }
    
    def calculate_monthly_material_requirement(self, year: int, month: int, 
                                                with_bom: bool = True) -> Dict[str, Any]:
        """
        월별 자재 소요량 계산
        
        Args:
            year: 조회 년도
            month: 조회 월
            with_bom: BOM 전개 여부
        
        Returns:
            {
                'total_requirement': 총 자재 소요량,
                'by_material': 자재별 소요량,
                'by_vendor': 공급업체별 소요량,
                'by_product_type': 자재 유형별 소요량,
                'shortage_alert': 부족 경고
            }
        """
        # 해당 월의 생산 계획 조회
        try:
            prod_plan = self.prod_plan_df.copy()
            if "start_date" in prod_plan.columns:
                prod_plan["start_date"] = pd.to_datetime(prod_plan["start_date"])
                plan_filtered = prod_plan[
                    (prod_plan["start_date"].dt.year == year) &
                    (prod_plan["start_date"].dt.month == month)
                ]
            else:
                plan_filtered = prod_plan
        except:
            plan_filtered = pd.DataFrame()
        
        # BOM 전개 (단순 집계)
        material_requirements = {}
        
        if not plan_filtered.empty and with_bom and not self.bom_df.empty:
            for _, plan in plan_filtered.iterrows():
                product_id = plan.get("root_product_id") or plan.get("product_id")
                plan_qty = plan.get("standard_qty", 0)
                
                # BOM에서 구성요소 조회
                bom_items = self.bom_df[self.bom_df["root_product_id"] == product_id]
                
                for _, bom in bom_items.iterrows():
                    component_id = bom.get("component_product_id")
                    component_qty = bom.get("component_qty", 0)
                    required_qty = plan_qty * component_qty
                    
                    if component_id not in material_requirements:
                        material_requirements[component_id] = 0
                    material_requirements[component_id] += required_qty
        
        # DataFrame 변환
        req_df = pd.DataFrame(list(material_requirements.items()), 
                            columns=["product_id", "requirement_qty"])
        
        # 공급업체 정보 병합
        if not req_df.empty and not self.purchase_pred_df.empty:
            vendor_info = self.purchase_pred_df[["product_id", "vendor_name"]].drop_duplicates()
            req_df = req_df.merge(vendor_info, on="product_id", how="left")
        
        # 통계
        total_items = len(req_df)
        total_qty = req_df["requirement_qty"].sum() if not req_df.empty else 0
        
        return {
            "period": f"{year}년 {month}월",
            "total_requirement": req_df,
            "statistics": {
                "총_자재종류": total_items,
                "총_소요량": total_qty,
            },
            "shortage_items": self._detect_shortage(req_df) if not req_df.empty else []
        }
    
    def get_purchase_order_status(self, vendor_id: Optional[str] = None,
                                   product_id: Optional[str] = None) -> Dict[str, Any]:
        """
        발주 현황 조회
        
        Args:
            vendor_id: 특정 공급업체만 조회 (선택사항)
            product_id: 특정 자재만 조회 (선택사항)
        
        Returns:
            {
                'summary': 발주 현황 요약,
                'by_vendor': 공급업체별 현황,
                'by_product': 자재별 현황,
                'pending': 미처리 발주
            }
        """
        po_df = self.po_df.copy()
        
        # 필터링
        if vendor_id:
            po_df = po_df[po_df["vendor_id"] == vendor_id]
        
        if product_id:
            po_df = po_df[po_df["product_id"] == product_id]
        
        # 상태 계산
        po_df["completion_rate_%"] = po_df.apply(
            lambda row: (row.get("received_qty", 0) / row.get("schedule_qty", 1) * 100) 
                       if row.get("schedule_qty", 0) > 0 else 0,
            axis=1
        )
        
        # 공급업체별 집계
        by_vendor = po_df.groupby("vendor_id").agg({
            "po_id": "count",
            "schedule_qty": "sum",
            "received_qty": "sum"
        }).rename(columns={"po_id": "po_count"})
        
        # 미처리 발주
        pending = po_df[po_df["completion_rate_%"] < 100]
        
        return {
            "summary": "발주 현황 조회",
            "total_pos": len(po_df),
            "by_vendor": by_vendor,
            "by_product": po_df,
            "pending": pending,
            "statistics": {
                "평균_완료율_%": po_df["completion_rate_%"].mean(),
                "미처리_발주건": len(pending)
            }
        }
    
    def _detect_shortage(self, requirement_df: pd.DataFrame, 
                        buffer_rate: float = 0.1) -> List[Dict[str, Any]]:
        """
        자재 부족 감지 (현재 재고 vs 소요량)
        
        Args:
            requirement_df: 소요량 DataFrame
            buffer_rate: 안전 재고율 (기본 10%)
        
        Returns:
            부족 자재 목록
        """
        shortages = []
        
        if "batch_stock" in self.db:
            batch_stock = self.db["batch_stock"]
            
            for _, req in requirement_df.iterrows():
                product_id = req.get("product_id")
                required_qty = req.get("requirement_qty", 0)
                
                # 현재 재고 조회
                stock_row = batch_stock[batch_stock["product_id"] == product_id]
                current_stock = stock_row["available_stock_value"].sum() if not stock_row.empty else 0
                
                # 부족 여부 (안전 재고 포함)
                required_with_buffer = required_qty * (1 + buffer_rate)
                
                if current_stock < required_with_buffer:
                    shortages.append({
                        "product_id": product_id,
                        "required_qty": required_qty,
                        "current_stock": current_stock,
                        "shortage_qty": required_with_buffer - current_stock,
                        "vendor": req.get("vendor_name", "미정")
                    })
        
        return shortages


# 사용 예시 및 래퍼 함수
def generate_monthly_closing_report(db: Dict[str, pd.DataFrame], year: int, month: int) -> Dict[str, Any]:
    """월말 구매 마감 리포트 생성 (래퍼)"""
    generator = MonthlyReportGenerator(db)
    return generator.get_monthly_purchase_closing_report(year, month)


def calculate_material_requirement(db: Dict[str, pd.DataFrame], year: int, month: int) -> Dict[str, Any]:
    """월별 자재 소요량 계산 (래퍼)"""
    generator = MonthlyReportGenerator(db)
    return generator.calculate_monthly_material_requirement(year, month)


def get_purchase_status(db: Dict[str, pd.DataFrame], 
                       vendor_id: Optional[str] = None,
                       product_id: Optional[str] = None) -> Dict[str, Any]:
    """발주 현황 조회 (래퍼)"""
    generator = MonthlyReportGenerator(db)
    return generator.get_purchase_order_status(vendor_id, product_id)
