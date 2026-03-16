from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    openrouter_api_key: str = ""
    model: str = "google/gemini-2.5-pro-preview"
    max_image_size_mb: int = 20
    log_level: str = "INFO"

    # Forensic analysis settings
    forensics_enabled: bool = True
    forensics_ela_quality: int = 95
    forensics_ela_scale: int = 20
    forensics_c2pa_enabled: bool = True

    # CNN deep learning forensics
    forensics_cnn_enabled: bool = True
    forensics_cnn_methods: str = "catnet,trufor"
    forensics_model_cache_dir: str = "/app/models"

    # Optical forensics (Moire / screen recapture detection)
    forensics_optical_enabled: bool = True

    class Config:
        env_file = ".env"
        env_prefix = "DENT_"


settings = Settings()
