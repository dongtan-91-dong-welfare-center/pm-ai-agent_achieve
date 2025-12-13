from core import config


def test_dummy_llm_response_set_and_invoke():
    llm = config.llm
    assert hasattr(llm, 'invoke'), 'llm should have invoke method for tests'
    original = None
    if hasattr(llm, 'set_response'):
        llm.set_response('테스트 응답')
        r = llm.invoke(None)
        assert '테스트' in str(r), f"Expected response to include '테스트', got: {r}"
        # restore
        llm.set_response('안녕하세요. Dummy LLM 응답입니다.')
    else:
        # If no set_response available, this environment uses real LLM; just assert invoke works
        r = llm.invoke({'messages': ['Hello']})
        assert r is not None
