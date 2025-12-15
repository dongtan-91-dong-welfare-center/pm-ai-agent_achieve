"""
설명: LLM 모델 초기화, 도구 바인딩, 시스템 프롬프트 설정을 담당하는 설정 파일

[Role & Responsibility]
- Adapter Pattern: LangGraph의 State(Dict)와 LangChain의 입력(List[BaseMessage]) 간의 불일치를 해결하는 Adapter를 포함합니다.
- Environment Safety: API Key가 없거나 라이브러리가 없는 CI/CD 테스트 환경에서도 코드가 깨지지 않도록 방어 로직을 수행합니다.
"""

import os
from dotenv import load_dotenv

# --------------------------------------------------------------------------
# 1. Safe Imports (테스트 환경 호환성)
# --------------------------------------------------------------------------
# 로컬 개발 환경이 아닌 CI 서버나 경량화 컨테이너에서 라이브러리 부재로 인한 크래시 방지
try:
    from langchain_google_genai import ChatGoogleGenerativeAI

    _HAS_GOOGLE_GENAI = True
except ImportError:
    ChatGoogleGenerativeAI = None  # type: ignore
    _HAS_GOOGLE_GENAI = False

try:
    from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder

    _HAS_PROMPTS = True
except ImportError:
    ChatPromptTemplate = None  # type: ignore
    MessagesPlaceholder = None  # type: ignore
    _HAS_PROMPTS = False

# 라우팅용 Pydantic 모델 & 실행용 함수 도구 Import
from core.state import PythonAnalysisRequest, FinalizeOrderRequest
from tools import AGENT_TOOLS

# 환경 변수 로드 (.env 파일)
load_dotenv()
api_key = os.environ.get("GOOGLE_API_KEY")
model_name = os.environ.get("MODEL", "gemini-2.5-flash")  # 기본값 설정

# --------------------------------------------------------------------------
# 2. LLM Initialization & Adapter (핵심 엔진)
# --------------------------------------------------------------------------

if _HAS_GOOGLE_GENAI and api_key:
    # [설정 핵심] Google Gemini 모델 초기화
    base_llm = ChatGoogleGenerativeAI(
        temperature=0,  # 생산 관리 특성상 창의성보다는 정확성(Determinism) 중시
        model=model_name,
        google_api_key=api_key,
        transport="rest",  # [Mac 호환성] GRPC 대신 REST API 사용 (방화벽/네트워크 이슈 최소화)
    )


    # [Design Pattern] LLM Adapter for LangGraph
    # LangGraph는 노드 간에 State(Dictionary)를 전달하지만,
    # LangChain 모델은 주로 List[BaseMessage]를 입력으로 받습니다.
    # 이 불일치를 해소하기 위해 입력을 변환해주는 래퍼(Wrapper) 클래스입니다.
    class LLMAdapter:
        def __init__(self, llm):
            self._llm = llm

        def bind_tools(self, tools):
            """LangChain의 bind_tools 기능을 그대로 위임"""
            return self._llm.bind_tools(tools)

        def invoke(self, payload=None):
            """
            LangGraph State(Dict)가 들어오면 'messages' 키만 추출하여 LLM에 전달
            """
            # Case 1: LangGraph에서 {"messages": [...], "data": ...} 형태의 Dict 전달 시
            if isinstance(payload, dict) and 'messages' in payload:
                payload = payload['messages']

            # Case 2: 일반적인 List[BaseMessage] 전달 시 그대로 수행
            return self._llm.invoke(payload)

        # 그 외 속성은 원본 LLM 객체로 위임 (Proxy)
        def __getattr__(self, name):
            return getattr(self._llm, name)


    # 실제 사용할 LLM 객체
    llm = LLMAdapter(base_llm)

else:
    # [Test Fallback] API Key가 없거나 라이브러리가 없는 경우 사용할 더미 LLM
    print("Warning: Running with DummyLLM (No API Key or Library found).")


    class DummyLLM:
        def __init__(self):
            self._bound_tools = []
            self._response = "안녕하세요. (Dummy LLM 응답: API Key를 확인해주세요)"

        def bind_tools(self, tools):
            self._bound_tools = tools
            return self

        def invoke(self, payload=None):
            """테스트용 고정 응답 반환"""
            return self._response


    llm = DummyLLM()

# --------------------------------------------------------------------------
# 3. Tool Binding (기능 장착)
# --------------------------------------------------------------------------

# A. AGENT_TOOLS: 실제로 실행되는 함수들 (재고 조회, 파일 생성 등) -> tools.py
# B. Pydantic Models: 실행되지 않고 라우팅 경로만 결정하는 구조체 -> state.py
# 이 둘을 합쳐서 LLM이 선택할 수 있는 '전체 도구 목록'을 만듭니다.
all_tools = AGENT_TOOLS + [PythonAnalysisRequest, FinalizeOrderRequest]

# LLM에게 도구 목록을 인지시킴 (Function Calling 활성화)
llm_with_tools = llm.bind_tools(all_tools)

# --------------------------------------------------------------------------
# 4. System Prompt & Chain (페르소나 설정)
# --------------------------------------------------------------------------

# Reasoner(두뇌) 노드가 사용할 메인 프롬프트
SYSTEM_PROMPT = """
당신은 15년 경력의 생산 관리 전문가 AI Agent입니다.
사용자의 질문을 분석하여 적절한 도구를 선택하거나 답변을 제공하십시오.

### 🚨 도구 선택의 절대 규칙 (Critical Tool Selection Rules)
1. **정형 리포트 우선 (Standard Reports First)**:
   - 질문에 **"월말 마감", "발주 현황", "공급업체 평가"** 등의 리포트 생성 또는 분석 요청이 포함되어 있다면, **절대 코드를 생성(`PythonAnalysisRequest`)하지 마십시오.**
   - 대신 반드시 아래의 전용 도구 중 하나를 사용해야 합니다. 이 도구들은 **분석과 파일 생성을 동시에 수행**합니다.
     - `generate_monthly_purchase_closing_report` (월말 마감 분석 및 생성)
     - `generate_po_status_report` (발주 현황 분석 및 생성)
     - `generate_supplier_evaluation_report` (공급업체 평가 분석 및 생성)

2. **비정형 분석 (Ad-hoc Analysis)**:
   - 위 3가지 정형 리포트에 해당하지 않는 **새로운 유형의 데이터 분석 질문**(예: "A자재의 최근 가격 추이를 그래프로 보여줘")일 때만 `PythonAnalysisRequest`를 사용하십시오.

3. **발주/저장 요청**:
   - 사용자가 "발주해줘", "저장해줘"라고 확정을 지으면 `FinalizeOrderRequest`를 호출하세요.

### 🛠️ 행동 지침 (Action Rules)
1. **일반 대화**: 단순한 인사나 프로세스 설명은 도구 없이 직접 답변하세요.
2. **데이터 보안**: 수백 건의 원본 데이터를 채팅창에 쏟아내지 말고, 도구가 반환하는 요약 정보나 파일 경로를 제공하세요.
"""

# Prompt Template 구성
if _HAS_PROMPTS and ChatPromptTemplate is not None:
    prompt_template = ChatPromptTemplate.from_messages([
        ("system", SYSTEM_PROMPT),
        MessagesPlaceholder(variable_name="messages"),  # 대화 기록 주입 위치
    ])

    # [Chain 생성] Prompt -> LLM (Tools Bound)
    # 이 객체가 agent_nodes.py의 reasoner 노드에서 호출됩니다.
    try:
        chain_prompt_llm = prompt_template | llm_with_tools
    except Exception:
        chain_prompt_llm = None
else:
    prompt_template = None
    chain_prompt_llm = None