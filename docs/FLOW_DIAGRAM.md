# 🔄 Self-Correction 재시도 로직 흐름도

## 정상 흐름 (성공 케이스)

```
┌──────────────────┐
│  사용자 질문      │
│ "재고를 분석해줘" │
└────────┬─────────┘
         │
         ▼
┌──────────────────────────────────────┐
│ [Reasoner] LLM 판단                  │
│ ✓ HumanMessage 감지 → 상태 초기화   │
│ ✓ Tool Call 생성: PythonAnalysisRequest
└────────┬─────────────────────────────┘
         │
         ▼
┌──────────────────────────────────────┐
│ [Router] route_reasoner()            │
│ tool_name == "PythonAnalysisRequest" │
│ ▶ return "code_generator"            │
└────────┬─────────────────────────────┘
         │
         ▼
┌──────────────────────────────────────┐
│ [Code Generator] LLM 코드 생성       │
│ ✓ execution_status != "error"        │
│ ✓ 기본 프롬프트로 코드 생성          │
│ ▶ return {"generated_code": "..."}   │
└────────┬─────────────────────────────┘
         │
         ▼
┌──────────────────────────────────────┐
│ [Code Executor] 코드 실행            │
│ try:                                 │
│   exec(generated_code)               │
│   result = local_context["result"]   │
│ ✅ SUCCESS!                          │
│ ▶ execution_status="success"         │
└────────┬─────────────────────────────┘
         │
         ▼
┌──────────────────────────────────────┐
│ [Router] route_after_execution()     │
│ status == "success"                  │
│ ▶ return "success"                   │
└────────┬─────────────────────────────┘
         │
         ▼
┌──────────────────────────────────────┐
│ [Reasoner] 결과 처리 및 요약         │
│ execution_status="success"           │
│ ▶ return {"messages": [AIMessage]}   │
└────────┬─────────────────────────────┘
         │
         ▼
    ✅ 완료 (사용자에게 결과 반환)
```

---

## 에러 발생 및 자동 수정 흐름 (Self-Correction)

```
┌──────────────────┐
│  사용자 질문      │
│ "발주량 계산해줘" │
└────────┬─────────┘
         │
         ▼
    [Reasoner] ──▶ [Router] ──▶ [Code Generator]
         │                            │
         │                            ▼
         │                    생성된 코드:
         │                    result = df_product['price'].sum()
         │
         │◀─────────────────────────────┘
         │
         ▼
    [Code Executor] 실행
    ❌ KeyError: 'price'
    (df_product에 'price' 컬럼 없음)

┌──────────────────────────────────────┐
│ execution_status = "error"           │
│ code_execution_result = "KeyError... │
│ retry_count = 1 (증가!)              │
└────────┬─────────────────────────────┘
         │
         ▼
┌──────────────────────────────────────┐
│ [Router] route_after_execution()     │
│ status == "error" AND retry_count<3  │
│ ▶ return "retry"                     │
└────────┬─────────────────────────────┘
         │
         ▼ (재시도!)
┌──────────────────────────────────────┐
│ [Code Generator] 코드 재생성         │
│ ✓ execution_status == "error"        │
│ ✓ 이전 에러 메시지 포함:             │
│   "[이전 코드 실행 실패]              │
│    이전 코드가 다음 오류로...         │
│    KeyError: 'price'                │
│    이 오류를 해결하도록 코드를       │
│    수정하여 다시 작성해주세요."      │
│                                      │
│ ▶ 수정된 코드:                       │
│   result = df_material_ledger['standard_price'].sum()
└────────┬─────────────────────────────┘
         │
         ▼
    [Code Executor] 재실행
    ✅ SUCCESS! (standard_price 사용)

┌──────────────────────────────────────┐
│ execution_status = "success"         │
│ retry_count = 0 (초기화!)            │
└────────┬─────────────────────────────┘
         │
         ▼ (정상 흐름과 동일)
    [Router] ──▶ [Reasoner] ──▶ ✅ 완료
```

---

## 최대 재시도 초과 흐름 (Failure Case)

```
시도 1: ❌ 에러 발생 (retry_count=1)
    ↓ [Router] → retry
시도 2: ❌ 다른 에러 (retry_count=2)
    ↓ [Router] → retry
시도 3: ❌ 또 다른 에러 (retry_count=3)
    ↓ [Router] → retry
시도 4: ❌ 계속 실패 (retry_count=4)
    ↓ [Router] route_after_execution()
    retry_count(4) >= MAX_RETRIES(3)
    ▶ return "max_retries"
    ↓
[Reasoner] 실패 보고:
"작업을 수행하는 도중 오류가 발생했습니다.\n(내용: ...)"
↓
❌ 사용자에게 실패 메시지 반환
```

---

## 상태 초기화 흐름 (State Reset)

```
[Turn 1] 사용자 질문 1 (분석 요청)
    ▶ [Reasoner] execution_status=None, retry_count=0
    ▶ [Code Generator] → [Code Executor] (성공 또는 실패)
    ▶ execution_status="success" 또는 "error"

[Turn 2] 사용자 질문 2 (새로운 분석 요청)
    │
    ▼
[Reasoner] HumanMessage 감지!
    ▶ "새로운 턴 시작: 상태 초기화"
    ▶ execution_status = None (이전 상태 삭제)
    ▶ retry_count = 0 (초기화)
    ▶ analysis_data = {} (이전 데이터 삭제)
    ▼
새로운 턴으로 깨끗하게 시작!
```

---

## 라우팅 결정 트리

```
last_message.tool_calls 있음?
│
├─ YES
│  └─ tool_name?
│     ├─ "PythonAnalysisRequest"
│     │  └─ return "code_generator" ← 복잡한 분석
│     ├─ "FinalizeOrderRequest"
│     │  └─ return "finalize_order" ← 최종 발주
│     └─ 기타 (재고 조회, BOM 등)
│        └─ return "tools" ← 일반 도구
│
└─ NO
   └─ return "__end__" ← 종료 (일반 대화)
```

---

## 코드 실행 환경 컨텍스트

```python
# global_context (코드에서 접근 가능한 변수)
{
    "pd": pd,                          # pandas 라이브러리
    "np": np,                          # numpy 라이브러리
    "tools": tools,                    # tools.py 모듈
    "DB": tools.DB,                    # 마스터 데이터 (딕셔너리)
    
    # 단축 변수 (예: df_product)
    "df_product": DataFrame,
    "df_material_ledger": DataFrame,
    "df_batch_stock": DataFrame,
    ...
}

# local_context (코드 실행 후 결과 추출)
result = local_context.get("result", None)  # 반드시 정의되어야 함
```

---

## 에러 타입별 처리 시나리오

| 에러 타입 | 예시 | 재시도 여부 |
|---------|------|---------|
| **문법 에러** | `SyntaxError` | ✅ 가능 (코드 재생성) |
| **KeyError** | `df.loc['없는_컬럼']` | ✅ 가능 (컬럼명 수정) |
| **TypeError** | `'int' + 'str'` | ✅ 가능 (타입 변환) |
| **값 에러** | `int('abc')` | ✅ 가능 (로직 수정) |
| **메모리 에러** | 대규모 연산 | ❌ 불가능 (데이터 문제) |
| **타임아웃** | 무한 루프 | ❌ 불가능 (시간 제약) |

---

## 주요 상태 값

```python
execution_status:
  None      # 초기 상태
  "success" # 성공
  "error"   # 실패
  "done"    # 처리 완료 (루프 탈출)

retry_count:
  0         # 첫 시도 또는 성공 후 초기화
  1, 2, 3   # 재시도 카운트
  4+        # MAX_RETRIES 초과 → max_retries로 라우팅

code_execution_result:
  "성공"             # 성공 메시지
  "KeyError: ..."    # 에러 메시지 (자세함)
  ""                 # 미설정
```

---

## 체크포인트 (Interrupt Point)

```
graph.compile(
    checkpointer=memory,
    interrupt_before=["finalize_order"]  # ← 여기서 사용자 승인 대기
)

프로세스:
1. [Code Executor] 완료
2. [Reasoner] 결과 요약
3. ⏸️ [Finalize Order 직전] 멈춤 (체크포인트)
4. 사용자가 "네, 발주해주세요"라고 입력
5. ▶️ [Finalize Order] 실행
6. 완료
```

