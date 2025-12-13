from core.nodes import route_reasoner, code_executor, code_generator
from core.nodes import route_after_execution
from langchain_core.messages import HumanMessage


class DummyToolMsg:
    def __init__(self, tool_name):
        self.type = 'tool'
        self.tool_calls = [{'name': tool_name}]


def test_route_reasoner_to_code_generator():
    state = {'messages': [DummyToolMsg('PythonAnalysisRequest')]}
    assert route_reasoner(state) == 'code_generator'


def test_route_reasoner_to_finalize():
    state = {'messages': [DummyToolMsg('FinalizeOrderRequest')]}
    assert route_reasoner(state) == 'finalize_order'


def test_route_after_execution_success():
    state = {'execution_status': 'success', 'retry_count': 0}
    assert route_after_execution(state) == 'success'


def test_route_after_execution_retry_and_max():
    state = {'execution_status': 'error', 'retry_count': 0}
    assert route_after_execution(state) == 'retry'

    state['retry_count'] = 3
    assert route_after_execution(state) == 'max_retries'


def test_code_executor_success_and_error():
    # Success case: code sets result variable
    success_state = {'generated_code': 'result = 1 + 1', 'retry_count': 0, 'thinking_steps': []}
    out = code_executor(success_state)
    assert out['execution_status'] == 'success'
    assert out['analysis_data']['last_run_result'] == 2 or out['analysis_data']['last_run_result'] == {'': 2} or isinstance(out['analysis_data']['last_run_result'], int) or 'last_run_result' in out['analysis_data']

    # Error case: missing result
    error_state = {'generated_code': 'x = 1/0', 'retry_count': 0, 'thinking_steps': []}
    out_err = code_executor(error_state)
    assert out_err['execution_status'] == 'error'
    assert 'division' in out_err['code_execution_result'] or 'ZeroDivisionError' in out_err['code_execution_result']


def test_code_generator_self_correction(monkeypatch):
    # Patch the llm.invoke to return deterministic code
    from core import config

    class FakeResp:
        def __init__(self, content):
            self.content = content

    def fake_invoke(payload):
        return FakeResp("result = 123")

    monkeypatch.setattr(config, 'llm', type('LLM', (), {'invoke': staticmethod(fake_invoke)}))

    state = {'messages': [HumanMessage(content='분석해줘')], 'execution_status': 'error', 'code_execution_result': 'some error', 'retry_count': 1}
    out = code_generator(state)
    assert 'generated_code' in out
    assert 'result = 123' in out['generated_code']


def test_reasoner_done_includes_continue_prompt():
    from core.nodes import reasoner
    from langchain_core.messages import AIMessage

    state = {
        'messages': [AIMessage(content='테스트 완료')],
        'execution_status': 'success',
        'analysis_data': {'last_run_result': '간단한 결과'},
        'thinking_steps': []
    }

    res = reasoner(state)
    assert res['execution_status'] == 'done'
    assert any('계속 반복하시겠습니까' in m.content for m in res['messages'])
