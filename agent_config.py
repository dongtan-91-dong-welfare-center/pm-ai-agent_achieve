# agent_config.py
import os
from dotenv import load_dotenv
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder

# 로컬 도구 및 상태 모델 임포트
from tools import calculate_gross_requirement, get_current_stock, check_long_term_stock_criteria
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
# 실제 실행되는 Tool + 라우팅용 가상 Tool
base_tools = [
    calculate_gross_requirement,
    get_current_stock,
    check_long_term_stock_criteria
]
# LLM에게 보여줄 전체 도구 리스트
all_tools = base_tools + [PythonAnalysisRequest, FinalizeOrderRequest]

# LLM에 도구 바인딩
llm_with_tools = llm.bind_tools(all_tools)

# 프롬프트 템플릿
SYSTEM_PROMPT = """
당신은 15년 경력의 생산 관리 전문가 AI Agent입니다.
Functions.csv와 ADR 문서에 정의된 규칙을 엄격히 준수하십시오.
모르는 정보는 지어내지 말고 도구를 사용하여 데이터를 조회하십시오.
답변은 한국어로 작성하며, 수치가 포함된 경우 명확한 근거를 제시하십시오.
"""

prompt_template = ChatPromptTemplate.from_messages([
    ("system", SYSTEM_PROMPT),
    MessagesPlaceholder(variable_name="messages"),
])

# 체인 생성 (Reasoner에서 사용)
chain_prompt_llm = prompt_template | llm_with_tools