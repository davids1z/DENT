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

    # Semantic forensics (AI detection, face liveness, VLM analysis)
    forensics_semantic_enabled: bool = True
    forensics_semantic_face_enabled: bool = True
    forensics_semantic_vlm_enabled: bool = True
    forensics_semantic_vlm_model: str = "google/gemini-2.5-pro-preview"

    # Spectral forensics (F2D-Net frequency-domain AI detection)
    forensics_spectral_enabled: bool = True

    # AI generation detection (Swin Transformer ensemble)
    forensics_aigen_enabled: bool = True
    forensics_aigen_methods: str = "sdxl,vit"

    # Document forensics (PDF analysis)
    forensics_document_enabled: bool = True
    forensics_document_signature_verification: bool = True

    # Agent settings (Phase 7)
    agent_enabled: bool = True
    agent_model: str = ""
    agent_stp_cost_threshold: float = 500.0
    agent_escalation_cost_threshold: float = 3000.0
    agent_stp_max_forensic_risk: float = 0.25
    agent_escalation_forensic_risk: float = 0.75

    # Evidence / timestamp settings (Phase 8)
    evidence_enabled: bool = True
    evidence_tsa_url: str = "https://freetsa.org/tsr"

    class Config:
        env_file = ".env"
        env_prefix = "DENT_"


settings = Settings()
