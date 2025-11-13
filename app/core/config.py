from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """환경 변수를 관리하는 클래스"""
    APP_NAME: str = "PM AI Agent"
    GOOGLE_API_KEY: str

    # .env 파일 로드 설정
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()