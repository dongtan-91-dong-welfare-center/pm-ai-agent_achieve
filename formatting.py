"""
결과 포맷팅 유틸리티 모듈

목적:
- 딕셔너리, 리스트, DataFrame 등의 구조화된 데이터를 마크다운 테이블 형태로 변환
- 비전공자가 이해할 수 있는 사람 친화적 형식으로 반환
"""

import pandas as pd
import json
from typing import Any, Dict, List, Union


def format_dataframe_to_markdown(df: pd.DataFrame, max_rows: int = 20) -> str:
    """
    DataFrame을 마크다운 테이블 형식으로 변환합니다.
    
    Args:
        df: 변환할 DataFrame
        max_rows: 최대 표시 행 수 (기본 20행)
    
    Returns:
        마크다운 테이블 문자열
    """
    if df.empty:
        return "📋 데이터가 없습니다."
    
    # 행 수 제한
    display_df = df.head(max_rows)
    
    # 마크다운 테이블로 변환
    markdown = f"📊 **데이터 조회 결과** (총 {len(df)}건, 표시: {len(display_df)}건)\n\n"
    try:
        markdown += display_df.to_markdown(index=False)
    except Exception:
        markdown += display_df.to_string(index=False)
    
    if len(df) > max_rows:
        markdown += f"\n\n⚠️ 결과가 많아 처음 {max_rows}건만 표시됩니다."
    
    return markdown


def format_dict_to_table(data: Dict[str, Any], title: str = "결과") -> str:
    """
    딕셔너리를 마크다운 테이블 형식으로 변환합니다.
    
    Args:
        data: 변환할 딕셔너리
        title: 테이블 제목
    
    Returns:
        마크다운 테이블 문자열
    """
    if not data:
        return "📋 데이터가 없습니다."
    
    # 중첩된 딕셔너리 처리
    if any(isinstance(v, (dict, list)) for v in data.values()):
        # 깊은 구조 -> JSON 형식
        return format_nested_data(data, title)
    
    # 평탄한 구조 -> 테이블
    markdown = f"📋 **{title}**\n\n"
    markdown += "| 항목 | 값 |\n"
    markdown += "|------|------|\n"
    
    for key, value in data.items():
        # 특수 문자 처리
        key_str = str(key).replace("|", "\\|")
        value_str = str(value).replace("|", "\\|")[:100]  # 길이 제한
        markdown += f"| {key_str} | {value_str} |\n"
    
    return markdown


def format_list_to_table(data: List[Dict], title: str = "결과", max_rows: int = 20) -> str:
    """
    딕셔너리 리스트를 마크다운 테이블로 변환합니다.
    
    Args:
        data: 딕셔너리 리스트
        title: 테이블 제목
        max_rows: 최대 표시 행 수
    
    Returns:
        마크다운 테이블 문자열
    """
    if not data:
        return "📋 데이터가 없습니다."
    
    # DataFrame으로 변환 후 포맷
    df = pd.DataFrame(data)
    return format_dataframe_to_markdown(df, max_rows)


def format_nested_data(data: Any, title: str = "결과", indent: int = 0) -> str:
    """
    중첩된 데이터 구조를 포맷된 문자열로 변환합니다.
    
    Args:
        data: 변환할 데이터
        title: 제목
        indent: 들여쓰기 수준
    
    Returns:
        포맷된 문자열
    """
    result = ""
    prefix = "  " * indent
    
    if isinstance(data, dict):
        if indent == 0:
            result += f"📋 **{title}**\n\n"
        
        for key, value in data.items():
            if isinstance(value, (dict, list)) and value:
                result += f"{prefix}**{key}:**\n"
                result += format_nested_data(value, "", indent + 1)
            else:
                result += f"{prefix}- **{key}**: {str(value)[:100]}\n"
    
    elif isinstance(data, list):
        if all(isinstance(item, dict) for item in data):
            # 딕셔너리 리스트 -> 테이블
            df = pd.DataFrame(data)
            result += format_dataframe_to_markdown(df)
        else:
            # 일반 리스트
            for i, item in enumerate(data[:20], 1):
                result += f"{prefix}{i}. {str(item)[:100]}\n"
            if len(data) > 20:
                result += f"{prefix}... (외 {len(data) - 20}건)\n"
    
    return result


def format_analysis_result(result: Any, title: str = "분석 결과") -> str:
    """
    분석 결과를 자동으로 가장 적절한 형식으로 포맷합니다.
    
    Args:
        result: 분석 결과 (DataFrame, dict, list 등)
        title: 결과 제목
    
    Returns:
        포맷된 문자열
    """
    if isinstance(result, pd.DataFrame):
        return format_dataframe_to_markdown(result)
    
    elif isinstance(result, dict):
        # DataFrame 중첩 여부 확인
        if "data" in result and isinstance(result.get("data"), list):
            # {'type': 'dataframe', 'data': [...], 'columns': [...]} 형식
            try:
                df = pd.DataFrame(result["data"], columns=result.get("columns", []))
                return format_dataframe_to_markdown(df)
            except:
                return format_dict_to_table(result, title)
        elif "type" in result and result["type"] == "dataframe":
            # serialize_result로 변환된 DataFrame
            data = result.get("data", {})
            if isinstance(data, dict):
                try:
                    df = pd.DataFrame(data.get("data", []), columns=data.get("columns", []))
                    return format_dataframe_to_markdown(df)
                except:
                    return format_dict_to_table(result, title)
            return format_nested_data(result, title)
        else:
            return format_dict_to_table(result, title)
    
    elif isinstance(result, list):
        if not result:
            return "📋 데이터가 없습니다."
        
        if all(isinstance(item, dict) for item in result):
            return format_list_to_table(result, title)
        else:
            # 단순 리스트
            markdown = f"📋 **{title}** ({len(result)}건)\n\n"
            for i, item in enumerate(result[:20], 1):
                markdown += f"{i}. {str(item)}\n"
            if len(result) > 20:
                markdown += f"\n... (외 {len(result) - 20}건)\n"
            return markdown
    
    elif isinstance(result, (int, float)):
        return f"📊 **{title}**: {result:,.2f}" if isinstance(result, float) else f"📊 **{title}**: {result:,}"
    
    elif isinstance(result, str):
        if len(result) > 500:
            return f"📋 **{title}**\n\n{result[:500]}...\n\n⚠️ (내용이 길어 처음 500자만 표시)"
        return f"📋 **{title}**\n\n{result}"
    
    else:
        return f"📋 **{title}**\n\n```\n{str(result)}\n```"


def format_thinking_process(steps: List[Dict[str, str]]) -> str:
    """
    생각 과정(Chain of Thought)을 시각화합니다.
    
    Args:
        steps: 단계별 생각 과정
               [
                   {"step": 1, "action": "데이터 로드", "reason": "...", "result": "성공"},
                   ...
               ]
    
    Returns:
        포맷된 CoT 문자열
    """
    if not steps:
        return ""
    
    markdown = "🧠 **AI의 사고 과정**\n\n"
    
    for i, step in enumerate(steps, 1):
        action = step.get("action", "")
        reason = step.get("reason", "")
        result = step.get("result", "")
        
        markdown += f"**Step {i}: {action}**\n"
        if reason:
            markdown += f"- 이유: {reason}\n"
        if result:
            markdown += f"- 결과: {result}\n"
        markdown += "\n"
    
    return markdown


def format_hil_prompt(decision_point: str, options: List[str], context: str = "") -> str:
    """
    Human-in-the-Loop (HIL) 승인 요청 프롬프트를 포맷합니다.
    
    Args:
        decision_point: 결정 포인트 (e.g., "발주 승인")
        options: 옵션 목록 (e.g., ["승인", "반려", "수정"])
        context: 배경 정보
    
    Returns:
        포맷된 HIL 프롬프트
    """
    markdown = f"⚠️ **{decision_point}**\n\n"
    
    if context:
        markdown += f"**배경 정보:**\n{context}\n\n"
    
    markdown += "**선택 옵션:**\n"
    for i, option in enumerate(options, 1):
        markdown += f"{i}. {option}\n"
    
    markdown += "\n어떤 선택을 하시겠습니까? (숫자 입력)"
    
    return markdown
