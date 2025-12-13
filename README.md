# 생산 관리 AI Agent (Production Management AI Agent)

이 프로젝트는 **제조 및 공급망 관리(SCM)** 분야의 효율성을 극대화하기 위해 설계된 **LangGraph 기반의 지능형 AI 에이전트**입니다.
복잡한 자재 소요량 계획(MRP), 발주 예측, 월말 마감 리포트 작성 등의 업무를 **LLM의 추론 능력**과 **Python의 정교한 연산 능력**을 결합하여 자동화합니다.

## 🤷‍♂️ 기술 스택

* **Language**: Python 3.13+
* **AI Engine**: LangChain, LangGraph
* **LLM**: Google Gemini 2.5 Flash (via `langchain-google-genai`)
* **User Interface**: Streamlit
* **Data Processing**: Pandas, NumPy, OpenPyXL
* **Environment**: Dotenv, Poetry (Dependency Management)

## 📂 폴더 구조

프로젝트는 **Layered Architecture**를 채택하여 역할과 책임을 명확히 분리했습니다.

```plaintext
pm-ai-agent/
├── 📄 main.py               # [Entry Point] Streamlit 애플리케이션 진입점
├── 📂 core/                 # [AI Brain] AI 엔진 및 워크플로우 제어
│   ├── 📄 graph.py          # LangGraph 워크플로우 정의 (Nodes & Edges)
│   ├── 📄 nodes.py          # 실행 노드 (Reasoner, CodeGenerator, Executor)
│   ├── 📄 state.py          # 상태 관리 (AgentState, Pydantic Models)
│   └── 📄 config.py         # LLM 설정 및 어댑터
├── 📂 interface/            # [Frontend] UI 컴포넌트 및 시각화
│   └── 📄 components.py     # 사이드바, 퀵 버튼, 채팅 UI 로직
├── 📂 tools/                # [Domain Logic] 비즈니스 로직 및 도구 모음
│   ├── 📄 order_tools.py    # MRP, 발주 예측, 소요량 전개
│   ├── 📄 stock_tools.py    # 재고 조회, 장기 재고 분석
│   ├── 📄 report_tools.py   # 엑셀/Markdown 리포트 생성기
│   ├── 📄 button_tools.py   # UI 버튼 트리거 전용 함수 (즉시 실행)
│   └── 📄 shared_logic.py   # 공통 연산 로직 (오버리지, 올림 처리 등)
├── 📂 data_loader/          # [ETL] 마스터 데이터 파싱 및 적재
├── 📂 data/                 # [Raw Data] 원본 CSV/Excel 파일 (Git 제외)
└── 📂 output/               # [Artifacts] 생성된 리포트 저장소 (Git 제외)
````

## 🔧 아키텍처

본 시스템은 \*\*보안(Security)\*\*과 \*\*정확성(Accuracy)\*\*을 최우선으로 설계되었습니다.

1.  **Schema-Only Prompting (Adr-007)**:

      * LLM에게는 데이터의 \*\*구조(Schema)\*\*만 전달하고, 실제 민감한 데이터(Row Data)는 전송하지 않습니다.
      * LLM은 데이터를 처리하는 **Python 코드**를 생성하고, 실제 실행은 로컬 샌드박스에서 수행됩니다.

2.  **Deterministic Tools (Adr-008)**:

      * 오버리지(Loss) 계산, 소요량 전개 등 복잡하고 규정 준수가 필요한 로직은 LLM이 아닌 \*\*사전 정의된 Python 함수(`tools/`)\*\*로 구현하여 결과의 신뢰성을 보장합니다.

3.  **Human-in-the-Loop (HIL)**:

      * 최종 발주 확정과 같은 중요한 의사결정 단계에서는 사용자의 **승인/반려** 절차를 거치도록 LangGraph의 `interrupt_before` 기능을 활용합니다.

## 🚀 주요 기능

1.  **자재 소요량 전개 및 발주 예측**:
      * 생산 계획과 BOM을 기반으로 부족 자재를 식별하고, 오버리지(Loss) 규칙을 적용하여 정확한 발주량을 제안합니다.
2.  **월말 구매 마감 리포트 자동화**:
      * 구매 상세 내역을 분석하여 **Summary(내자/외자, 원료/자재)**, **Top Items(주요 지출 품목)**, **Error Log(마스터 누락)** 시트를 포함한 엑셀 리포트를 생성합니다.
3.  **공급업체 평가 관리**:
      * 입고 내역과 부적합 데이터를 매칭하여 납기 준수율(LT)과 부적합 여부를 자동으로 판별합니다.
4.  **지능형 데이터 분석**:
      * 자연어 질문("A자재의 현재 재고는?", "장기 재고 현황 보여줘")을 이해하고 데이터를 시각화(Chart/Table)합니다.

## 📊 실행 흐름

1.  **Input**: 사용자 질문 또는 퀵 버튼 클릭 (Streamlit UI)
2.  **Reasoning**: LLM이 사용자 의도를 파악하고 도구 호출 여부 결정 (`core/nodes.py`)
3.  **Execution**:
      * *도구 사용 시*: `tools/` 패키지의 함수 실행 (재고 조회, 리포트 생성)
      * *분석 필요 시*: `Code Generator`가 Python 코드를 작성하고 `Code Executor`가 실행
4.  **Refinement**: 실행 오류 발생 시 Self-Correction(재시도) 수행
5.  **Output**: 최종 답변 및 엑셀 파일/차트 생성

## ⚙️ 환경 설정

1.  **필수 요건**: Python 3.13 이상
2.  **가상 환경 설정 및 패키지 설치**:
    ```bash
    pip install poetry
    poetry install
    ```
3.  **환경 변수 설정**:
      * `.env` 파일을 생성하고 Google API Key를 입력합니다.
    <!-- end list -->
    ```text
    GOOGLE_API_KEY=your_api_key_here
    MODEL=gemini-2.5-flash
    ```
4.  **실행**:
    ```bash
    streamlit run main.py
    ```

## 📊 테스트

  * **단위 테스트**: `tests/` 폴더 내에 주요 로직(오버리지, MRP)에 대한 검증 코드가 포함되어 있습니다.
  * **데이터 검증**: `ui_components.py`의 '데이터 탐색기'를 통해 로드된 마스터 데이터의 정합성을 실시간으로 확인할 수 있습니다.

## 💡 프로젝트 관리

  * **Version Control**: Git & GitHub Flow
  * **Documentation**: ADR(Architecture Decision Records)을 통해 주요 기술적 의사결정 이력을 관리합니다.

## 🔧 추후 개선 사항

  * RDBMS (PostgreSQL) 마이그레이션
  * Docker 기반 배포 환경 구축
  * CI/CD 파이프라인 자동화

## 📌 주의사항

  * **데이터 보안**: `/data` 및 `/output` 폴더는 `.gitignore`에 등록되어 외부로 유출되지 않도록 관리해야 합니다.
  * **API Key**: API Key가 포함된 `.env` 파일이 커밋되지 않도록 주의하십시오.

<!-- end list -->

````