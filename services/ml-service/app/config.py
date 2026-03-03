from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    openrouter_api_key: str = ""
    model: str = "google/gemini-2.5-pro-preview"
    max_image_size_mb: int = 20
    log_level: str = "INFO"

    class Config:
        env_file = ".env"
        env_prefix = "DENT_"


settings = Settings()
