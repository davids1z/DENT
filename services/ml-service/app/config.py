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

    # Mesorch tampering detection (AAAI 2025, DCT dual-backbone, JPEG F1=0.774)
    forensics_mesorch_enabled: bool = True

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

    # Community Forensics AI detection (CVPR 2025, ViT-Small, 4803 generators)
    forensics_community_forensics_enabled: bool = True

    # EfficientNet-B4 AI detection (fast CNN, 19.3M params, 0.5-1s CPU)
    forensics_efficientnet_ai_enabled: bool = True
    forensics_efficientnet_ai_model: str = "Dafilab/ai-image-detector"

    # SAFE AI detection (KDD 2025, pixel correlation, 1.44M params, <15ms CPU)
    forensics_safe_ai_enabled: bool = True

    # DINOv2 AI detection (linear probe on frozen DINOv2-base, 97.2% on Flux)
    forensics_dinov2_ai_enabled: bool = True
    forensics_dinov2_ai_model: str = "facebook/dinov2-base"

    # NPR AI detection (CVPR 2024, upsampling artifact detection, 1.44M params)
    # Disabled: 0.023 separation (noise), gives 1.00 on authentic JPEGs
    forensics_npr_enabled: bool = False

    # CLIP AI detection (UniversalFakeDetect style)
    forensics_clip_ai_enabled: bool = True
    forensics_clip_ai_model: str = "openai/clip-vit-large-patch14"

    # VAE reconstruction error detection (DIRE/CO-SPY style)
    forensics_vae_recon_enabled: bool = True
    forensics_vae_recon_model: str = "stabilityai/sd-vae-ft-mse"

    # Text AI detection (for documents: PDF, DOCX, XLSX)
    forensics_text_ai_enabled: bool = True
    forensics_text_ai_classifier: str = "fakespot-ai/roberta-base-ai-text-detection-v1"
    forensics_text_ai_perplexity_model: str = "distilgpt2"
    forensics_text_ai_gptzero_api_key: str = ""

    # Document forensics (PDF analysis)
    forensics_document_enabled: bool = True
    forensics_document_signature_verification: bool = True
    forensics_document_embedded_image_forensics: bool = True

    # Office document forensics (DOCX/XLSX analysis)
    forensics_office_enabled: bool = True

    # PRNU sensor noise analysis (camera fingerprinting)
    forensics_prnu_enabled: bool = True

    # Content validation (OCR + OIB/IBAN check for Croatian documents)
    forensics_content_validation_enabled: bool = True
    forensics_content_validation_ocr_lang: str = "hrv+eng"

    # GHOST calibration file (JSON with calibrated thresholds)
    forensics_calibration_file: str = ""

    # Stacking meta-learner (replaces hand-crafted fusion rules when trained)
    forensics_stacking_meta_enabled: bool = False
    forensics_stacking_meta_weights: str = ""

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
