from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    # Supabase
    supabase_url: str = ""
    supabase_service_key: str = ""

    # LLM Keys
    groq_api_key: str = ""
    google_api_key: str = ""
    anthropic_api_key: str = ""

    # Adzuna Job Search API (free — register at developer.adzuna.com)
    adzuna_app_id: str = ""
    adzuna_api_key: str = ""

    # App
    secret_key: str = "change-me-in-production-32chars!!"
    allowed_origins: str = "http://localhost:5173"
    min_match_score: float = 80.0   # Only apply if match >= 80%

    class Config:
        env_file = ".env"
        case_sensitive = False


@lru_cache()
def get_settings() -> Settings:
    return Settings()
