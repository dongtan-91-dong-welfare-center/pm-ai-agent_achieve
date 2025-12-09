import os
import requests
import json
from dotenv import load_dotenv

# 1. 시스템 인증서 강제 적용 (필수)
try:
    import pip_system_certs.wrapt_requests
except ImportError:
    pass

load_dotenv()
api_key = os.environ.get("GOOGLE_API_KEY")

if not api_key:
    print("❌ API Key가 없습니다.")
else:
    print(f"🔑 API Key 확인됨. (REST 요청 시도)")

    # 2. Google Gemini REST API 직접 호출
    url = f"https://generativelanguage.googleapis.com/v1beta/models?key={api_key}"

    try:
        response = requests.get(url)

        if response.status_code == 200:
            models = response.json().get('models', [])
            print("\n📋 [사용 가능한 모델 목록 (REST 방식)]")

            valid_models = []
            for m in models:
                # 'generateContent' 기능을 지원하는 모델만 필터링
                if 'generateContent' in m.get('supportedGenerationMethods', []):
                    # "models/gemini-pro" -> "gemini-pro"로 변환하여 출력
                    short_name = m['name'].replace("models/", "")
                    print(f"- {short_name}")
                    valid_models.append(short_name)

            if not valid_models:
                print("⚠️ 사용 가능한 모델이 없습니다.")
        else:
            print(f"❌ 요청 실패: {response.status_code}")
            print(response.text)

    except Exception as e:
        print(f"❌ 연결 오류: {e}")