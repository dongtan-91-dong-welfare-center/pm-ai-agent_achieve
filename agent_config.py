import os
from dotenv import load_dotenv
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder

# (기존 tools.py의 함수들은 여기서 바인딩하지 않고, agent_nodes.py의 code_executor에서 직접 import해서 씁니다.)
# from tools import calculate_gross_requirement, get_current_stock, check_long_term_stock_criteria
# 라우팅을 위한 구조체(Pydantic 모델)을 import
from agent_state import PythonAnalysisRequest, FinalizeOrderRequest

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

# 도구(Tools) 리스트업

# 실제 실행되는 Tool
# base_tools = [
#     calculate_gross_requirement,
#     get_current_stock,
#     check_long_term_stock_criteria
# ]

# 라우팅용 가상 Tool
router_tools = [PythonAnalysisRequest, FinalizeOrderRequest]

# LLM에 도구 바인딩
llm_with_tools = llm.bind_tools(router_tools)

# 프롬프트 템플릿
SYSTEM_PROMPT = """
당신은 15년 경력의 생산 관리 전문가 AI Agent (Main Router)입니다.
사용자의 질문을 듣고 적절한 작업 경로를 선택하는 것이 당신의 임무입니다.

### 행동 지침
1. **분석/계산/조회 요청**: 
   - 재고 조회, 발주량 계산, 데이터 분석 등이 필요하면 **반드시 `PythonAnalysisRequest` 도구를 호출**하십시오.
   - 직접 답변하려 하지 마십시오.

2. **발주/저장 요청**: 
   - 사용자가 분석 결과를 보고 "발주해줘", "저장해줘"라고 하면 `FinalizeOrderRequest`를 호출하십시오.

3. **일반 대화**: 
   - 단순한 인사나 프로세스 설명은 도구 없이 직접 답변하십시오.
"""

prompt_template = ChatPromptTemplate.from_messages([
    ("system", SYSTEM_PROMPT),
    MessagesPlaceholder(variable_name="messages"),
])

# 체인 생성 (Reasoner에서 사용)
chain_prompt_llm = prompt_template | llm_with_tools