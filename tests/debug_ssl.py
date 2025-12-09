import os
import sys
from dotenv import load_dotenv

# 1. pip-system-certs 적용 확인
try:
    import pip_system_certs.wrapt_requests

    print("✅ pip-system-certs: Installed & Active")
except ImportError:
    print("❌ pip-system-certs: NOT Installed (설치 필요: pip install pip-system-certs)")

# 환경 변수 로드
load_dotenv()
api_key = os.environ.get("GOOGLE_API_KEY")

if not api_key:
    print("❌ Error: GOOGLE_API_KEY not found in .env")
    sys.exit(1)

print(f"🔑 API Key Loaded: {api_key[:5]}...")

try:
    from langchain_google_genai import ChatGoogleGenerativeAI

    # 2. REST 모드 강제 설정 테스트
    print("\nAttempting connection with transport='rest'...")
    llm = ChatGoogleGenerativeAI(
        model="gemini-1.5-flash",  # 또는 사용 중인 모델명
        google_api_key=api_key,
        transport="rest"  # <--- 핵심 설정
    )

    # 3. 간단한 호출 시도
    result = llm.invoke("Hello, are you working via REST?")
    print(f"\n🎉 Success! Response: {result.content}")
    print("✅ REST connection established successfully.")

except Exception as e:
    print(f"\n❌ Connection Failed: {e}")
    print("\n[진단 결과]")
    if "ssl_transport_security" in str(e) or "handshake failed" in str(e).lower():
        print("👉 여전히 gRPC가 사용되고 있습니다. transport='rest'가 무시되었습니다.")
    else:
        print("👉 SSL 인증서 또는 네트워크 문제입니다.")
