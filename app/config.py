from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "sqlite:///./local.db"
    jwt_secret: str = "dev-secret-change-me"
    jwt_algorithm: str = "HS256"
    jwt_expires_minutes: int = 60 * 24 * 7  # 7 days
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"
    cookie_secure: bool = False  # set True in production (HTTPS)

    class Config:
        env_file = ".env"


settings = Settings()