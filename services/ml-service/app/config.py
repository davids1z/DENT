from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    anthropic_api_key: str = ""
    claude_model: str = "claude-sonnet-4-20250514"
    max_image_size_mb: int = 20
    log_level: str = "INFO"

    class Config:
        env_file = ".env"
        env_prefix = "DENT_"


settings = Settings()
