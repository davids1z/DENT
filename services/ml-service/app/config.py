from pydantic_settings import BaseSettings


class Settings(BaseSettings):
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

    # Semantic forensics (AI detection, face liveness)
    forensics_semantic_enabled: bool = True
    forensics_semantic_face_enabled: bool = True

    # Spectral forensics (F2D-Net frequency-domain AI detection)
    forensics_spectral_enabled: bool = True

    # AI generation detection (Swin Transformer ensemble)
    forensics_aigen_enabled: bool = True
    forensics_aigen_methods: str = "sdxl,vit"

    # Community Forensics — DISABLED: only covers open-source SD variants, 4% on modern AI
    forensics_community_forensics_enabled: bool = False

    # EfficientNet-B4 AI detection — DISABLED: gated repo (401), 98% FP on authentic
    forensics_efficientnet_ai_enabled: bool = False
    forensics_efficientnet_ai_model: str = "Dafilab/ai-image-detector"

    # SAFE AI detection (KDD 2025, DWT wavelet + pixel correlation, 1.44M params)
    forensics_safe_ai_enabled: bool = True

    # DINOv2 AI detection (linear probe on frozen DINOv2-large, 1024-dim)
    forensics_dinov2_ai_enabled: bool = True
    forensics_dinov2_ai_model: str = "facebook/dinov2-large"

    # SPAI spectral AI detection — DISABLED: TorchScript trace broke frequency decomposition, outputs 0%
    forensics_spai_enabled: bool = False
    forensics_spai_model_dir: str = "/app/models/spai"

    # B-Free AI detection (CVPR 2025, bias-free DINOv2 ViT-Base, 27 generators, 5-crop)
    forensics_bfree_enabled: bool = True
    forensics_bfree_model_dir: str = "/app/models/bfree"

    # Pixel Forensics (8 content-independent signals, numpy only)
    forensics_pixel_forensics_enabled: bool = True

    # RA-Det robustness asymmetry (arXiv 2603.01544, simplified Gaussian version)
    # Reuses DINOv2-large — no extra model download, ~120ms/image on GPU
    forensics_radet_enabled: bool = True

    # FatFormer CLIP+DWT frequency analysis (CVPR 2024, arXiv 2312.16649)
    # Reuses CLIP ViT-L/14 — DWT frequency features provide orthogonal signal
    forensics_fatformer_enabled: bool = True

    # AIDE DCT+SRM frequency analysis (ICLR 2025, simplified without ConvNeXt-XXL)
    # 30 SRM high-pass filters + DCT patch scoring — no model download needed
    forensics_aide_enabled: bool = True

    # Organika SDXL detector (Swin Transformer, 98.1% accuracy, Wikimedia)
    forensics_organika_ai_enabled: bool = True

    # AI Source detector — DISABLED: HF weights are broken (RoBERTa text instead of ViT vision)
    forensics_ai_source_enabled: bool = False

    # RINE AI detection (ECCV 2024, OpenAI CLIP intermediate layers, 91.5% acc)
    forensics_rine_ai_enabled: bool = True

    # SigLIP AI detection (fine-tuned SigLIP, 92.9M params, 99.23% accuracy)
    forensics_siglip_ai_enabled: bool = False

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

    # Stacking meta-learner (provides verdict probability bars when trained)
    forensics_stacking_meta_enabled: bool = True
    forensics_stacking_meta_weights: str = ""

    # Per-module timeout (seconds)
    forensics_module_timeout_seconds: int = 120

    # Concurrency / scaling settings
    thread_pool_size: int = 8  # ThreadPoolExecutor workers for parallel module execution
    max_concurrent_analyses: int = 3  # Max pipeline analyses running simultaneously
    uvicorn_workers: int = 1  # Number of uvicorn/gunicorn worker processes

    # Evidence / timestamp settings (Phase 8)
    evidence_enabled: bool = True
    evidence_tsa_url: str = "https://freetsa.org/tsr"

    class Config:
        env_file = ".env"
        env_prefix = "DENT_"


settings = Settings()
