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
    # Enabled 2026-04-07 after Day 4 of path-to-95 roadmap. Production data
    # showed +25.8pp gap (auth 0.57% mean, AI 15.59% mean) with 42% of AI
    # images firing strongly (30-95%) and only 4% of authentic with any
    # signal at all. Near-zero false positives, MIT license, ViT-Small 87MB.
    forensics_community_forensics_enabled: bool = True

    # EfficientNet-B4 AI detection — DISABLED: gated repo (401), 98% FP on authentic
    forensics_efficientnet_ai_enabled: bool = False
    forensics_efficientnet_ai_model: str = "Dafilab/ai-image-detector"

    # SAFE AI detection (KDD 2025, DWT wavelet + pixel correlation, 1.44M params)
    # DISABLED 2026-04-07: production audit shows -6pp gap (anti-correlated).
    # Returns ~0 even on obvious AI generators while occasionally firing on
    # authentic photos. Kept in MODULE_ORDER so meta-learner weights still
    # validate, but no longer executed in the pipeline.
    forensics_safe_ai_enabled: bool = False

    # DINOv2 AI detection (linear probe on frozen DINOv2-large, 1024-dim)
    forensics_dinov2_ai_enabled: bool = True
    forensics_dinov2_ai_model: str = "facebook/dinov2-large"

    # SPAI spectral AI detection — DISABLED: TorchScript trace broke frequency decomposition, outputs 0%
    forensics_spai_enabled: bool = False
    forensics_spai_model_dir: str = "/app/models/spai"

    # B-Free AI detection (CVPR 2025, bias-free DINOv2 ViT-Base, 27 generators, 5-crop)
    # DISABLED 2026-04-07: production audit shows -17.5pp gap (severely
    # anti-correlated — confidently labels AI as authentic). The previous
    # checkpoint never recovered after the early-2026 transformers update.
    # See B-Free disaster post-mortem in path-to-95.md for the rationale
    # behind the holdout_gate inversion check.
    forensics_bfree_enabled: bool = False
    forensics_bfree_model_dir: str = "/app/models/bfree"

    # Pixel Forensics (8 content-independent signals, numpy only)
    forensics_pixel_forensics_enabled: bool = True

    # RA-Det robustness asymmetry (arXiv 2603.01544, simplified Gaussian version)
    # DISABLED: current implementation uses Gaussian noise heuristic, not learned UNet.
    # Causes false positives (57% on real images). Enable after training learned UNet
    # on GPU server per gpu-server-plan.md Phase 2.
    forensics_radet_enabled: bool = False

    # FatFormer CLIP+DWT frequency analysis (CVPR 2024, arXiv 2312.16649)
    # Reuses CLIP ViT-L/14 — DWT frequency features provide orthogonal signal
    # DISABLED until calibrated on production data
    forensics_fatformer_enabled: bool = False

    # AIDE DCT+SRM frequency analysis (ICLR 2025, simplified without ConvNeXt-XXL)
    # 30 SRM high-pass filters + DCT patch scoring — no model download needed
    # DISABLED until calibrated on production data
    forensics_aide_enabled: bool = False

    # Organika SDXL detector (Swin Transformer, 98.1% accuracy, Wikimedia)
    forensics_organika_ai_enabled: bool = True

    # AI Source detector — DISABLED: HF weights are broken (RoBERTa text instead of ViT vision)
    forensics_ai_source_enabled: bool = False

    # RINE AI detection (ECCV 2024, OpenAI CLIP intermediate layers, 91.5% acc)
    # DISABLED 2026-04-07: production audit shows the probe is saturated —
    # outputs ~0 on every image regardless of source. The architecture is
    # sound but the public checkpoint does not generalise to the post-2024
    # generators we see in production.
    forensics_rine_ai_enabled: bool = False

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
    # DISABLED 2026-04-07: WebP/JPEG re-encoding (which every uploaded
    # photo goes through) destroys the PRNU signal. Cohen's d on production
    # data is 0.011 — no separation between authentic and AI. Module is
    # kept in MODULE_ORDER for meta-learner schema compatibility but is
    # no longer executed in the pipeline.
    forensics_prnu_enabled: bool = False

    # Content validation (OCR + OIB/IBAN check for Croatian documents)
    forensics_content_validation_enabled: bool = True
    forensics_content_validation_ocr_lang: str = "hrv+eng"

    # GHOST calibration file (JSON with calibrated thresholds)
    forensics_calibration_file: str = ""

    # Stacking meta-learner (provides verdict probability bars when trained)
    forensics_stacking_meta_enabled: bool = True
    forensics_stacking_meta_weights: str = ""
    # Day 3 of path-to-95: blend the supervised meta-learner score into the
    # rule-based overall. The blend factor was tuned via holdout sweep on
    # 26 production rows and 0.30 gave the best balanced result:
    #   AI recall:        70% → 100% (+30pp)
    #   Authentic recall: 100% → 87.5% (-12.5pp, above 85% gate)
    #   Overall accuracy: 88.5% → 92.3% (+3.8pp)
    #   Inversion margin: +47.6pp (well above +20pp safety net)
    # Set to 0.0 to disable the blend (pure rule-based fusion).
    forensics_stacking_meta_blend_factor: float = 0.30

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
