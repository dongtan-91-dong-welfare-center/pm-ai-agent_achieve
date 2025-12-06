import os
from dotenv import load_dotenv
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder

from agent_state import PythonAnalysisRequest, FinalizeOrderRequest
from tools import get_stock_status, generate_purchase_prediction, calculate_gross_requirement, analyze_long_term_stock

# 환경 변수 로드
load_dotenv()
api_key = os.environ.get("GOOGLE_API_KEY")
model_name = os.environ.get("MODEL")

if not api_key:
    raise ValueError("GOOGLE_API_KEY 환경변수가 설정되지 않았습니다.")

# 기본 LLM 설정
llm = ChatGoogleGenerativeAI(
    temperature=0,
    model=model_name,
    google_api_key=api_key
)

# 실제 실행되는 도구 목록
base_tools = [
    get_stock_status,
    generate_purchase_prediction,
    calculate_gross_requirement,
    analyze_long_term_stock,
]

# 라우팅용 도구 (Pydantic 모델) 추가
all_tools = base_tools + [PythonAnalysisRequest, FinalizeOrderRequest]

# LLM에 도구 바인딩
llm_with_tools = llm.bind_tools(all_tools)

# Reasoner 프롬프트
SYSTEM_PROMPT = """
당신은 15년 경력의 생산 관리 전문가 AI Agent입니다.
사용자의 질문을 분석하여 적절한 작업 경로를 선택하는 것이 임무입니다.

### 행동 지침
1. **분석/계산 요청**: 재고 조회, 발주량 계산, 데이터 분석이 필요하면 `PythonAnalysisRequest`를 호출하세요.
2. **발주/저장 요청**: 사용자가 "발주해줘", "저장해줘"라고 하면 `FinalizeOrderRequest`를 호출하세요.
3. **일반 대화**: 단순한 인사나 프로세스 설명은 도구 없이 직접 답변하세요.
"""

prompt_template = ChatPromptTemplate.from_messages([
    ("system", SYSTEM_PROMPT),
    MessagesPlaceholder(variable_name="messages"),
])

# 체인 생성 (reasoner에서 사용)
chain_prompt_llm = prompt_template | llm_with_tools