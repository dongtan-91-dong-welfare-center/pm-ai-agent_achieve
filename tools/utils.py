"""
설명: 데이터 포맷팅 및 공통 유틸리티 함수 모음

[Role & Responsibility]
- Data Formatting: DataFrame을 LLM이 이해하기 쉬운 Markdown Table 형식으로 변환합니다.
- Robustness: 다양한 입력 타입(Series, List)과 결측치(NaN)를 안전하게 처리합니다.
- Token Optimization: 너무 큰 데이터는 자동으로 상위 N행만 잘라서 토큰 비용을 절약합니다.
"""

import pandas as pd
from typing import Union, List, Dict, Any
from .shared import DB as SHARED_DB

def get_db():
    """
    [Legacy Support] 런타임 DB 접근 헬퍼
    테스트 코드에서 `tools.DB`를 모킹(Mocking)할 때 주로 사용됩니다.
    일반적인 상황에서는 `from tools.shared import DB`를 직접 사용하는 것을 권장합니다.
    """
    return SHARED_DB


def df_to_markdown(data: Union[pd.DataFrame, pd.Series, List[Dict]], max_rows: int = 20) -> str:
    """
    [Universal Formatter]
    다양한 데이터 타입을 LLM이 읽기 좋은 Markdown Table 문자열로 변환합니다.

    Features:
        1. Series -> DataFrame 자동 변환
        2. List[Dict] -> DataFrame 자동 변환
        3. NaN(결측치) -> '-' 로 치환하여 가독성 확보
        4. 행 개수 제한 (Token Saving)
    """
    # 1. 입력 타입 정규화
    if isinstance(data, pd.Series):
        df = data.to_frame().T
    elif isinstance(data, list):
        df = pd.DataFrame(data)
    elif isinstance(data, pd.DataFrame):
        df = data
    else:
        # DataFrame이 아닌 경우 문자열로 변환하여 반환
        return str(data)

    # 2. 빈 데이터 처리
    if df.empty:
        return "데이터 없음"

    # 3. 데이터 전처리 (결측치 처리 및 타입 변환)
    # LLM은 'NaN'보다 '-'이나 빈칸을 더 잘 이해함
    df_clean = df.fillna('-')

    # 4. Markdown 변환 (라이브러리 의존성 제거를 위한 Fallback 구현)
    try:
        # tabulate 라이브러리가 설치되어 있다면 예쁘게 출력
        # head(max_rows)를 통해 토큰 폭발 방지
        return df_clean.head(max_rows).to_markdown(index=False)
    except (ImportError, AttributeError):
        # 5. Fallback: 수동 포맷팅 (tabulate가 없을 경우)
        cols = [str(c) for c in df_clean.columns]
        header = "| " + " | ".join(cols) + " |"
        sep = "| " + " | ".join(["---"] * len(cols)) + " |"

        rows = []
        # itertuples가 iterrows보다 빠름
        for r in df_clean.head(max_rows).itertuples(index=False):
            rows.append("| " + " | ".join(str(x) for x in r) + " |")

        footer = ""
        if len(df_clean) > max_rows:
            footer = f"\n(.. 외 {len(df_clean) - max_rows}건 생략 ..)"

        return header + "\n" + sep + "\n" + "\n".join(rows) + footer