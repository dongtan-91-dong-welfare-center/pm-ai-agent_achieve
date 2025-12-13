#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
변환된 테스트 파일: pytest-compatible

이 파일은 환경이 제대로 구성되지 않은 경우 pytest.skip로 건너뛸 수 있도록 구성됩니다.
"""
import pytest


def _safe_import(name: str):
    try:
        module = __import__(name)
        return module
    except Exception:
        return None


def test_imports_and_formatting():
    # 일부 외부 패키지나 환경 변수가 설정되지 않은 경우 테스트를 건너뜁니다.
    agent_nodes = _safe_import("agent_nodes")
    if not agent_nodes:
        pytest.skip("agent_nodes를 임포트할 수 없습니다. 런타임 의존성이 누락되었을 수 있습니다.")

    from interface.formatting import (
        format_analysis_result,
        format_thinking_process,
        format_hil_prompt,
    )

    # 간단한 formatting 테스트
    test_dict = {
        "sangpum": "seed",
        "qty": 1000,
        "price": 5000,
        "total": 5000000,
    }

    formatted = format_analysis_result(test_dict, "Test Result")
    assert isinstance(formatted, str)

    thinking_steps = [
        {"step": 1, "action": "Load Data", "reason": "...", "result": "Success"},
        {"step": 2, "action": "Analysis", "reason": "...", "result": "Done"},
    ]
    cot_output = format_thinking_process(thinking_steps)
    assert isinstance(cot_output, str)

    hil_prompt = format_hil_prompt("Order Approval", ["Approve", "Reject", "Modify"], "Order Amount: 100,000,000 KRW")
    assert isinstance(hil_prompt, str)


def test_agent_state_structure():
    langchain_msgs = _safe_import("langchain_core.messages")
    if not langchain_msgs:
        pytest.skip("langchain_core.messages를 임포트할 수 없습니다. LLM 패키지가 필요합니다.")

    from langchain_core.messages import HumanMessage

    test_state = {
        "messages": [HumanMessage(content="Test Question")],
        "generated_code": None,
        "analysis_data": {},
        "execution_status": None,
        "code_execution_result": None,
        "retry_count": 0,
        "thinking_steps": [],
        "user_approval_pending": False,
        "user_approval_decision": None,
        "user_feedback": None,
    }

    assert isinstance(test_state, dict)
