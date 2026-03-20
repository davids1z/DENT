import asyncio
import logging
from collections.abc import Callable

from .analyzers.ai_generation import AiGenerationAnalyzer
from .analyzers.clip_ai_detection import ClipAiDetectionAnalyzer
from .analyzers.cnn_forensics import CnnForensicsAnalyzer
from .analyzers.prnu_detection import PrnuDetectionAnalyzer
from .analyzers.spectral_forensics import SpectralForensicsAnalyzer
from .analyzers.document import DocumentForensicsAnalyzer
from .analyzers.metadata import MetadataAnalyzer
from .analyzers.modification import ModificationAnalyzer
from .analyzers.office import OfficeForensicsAnalyzer
from .analyzers.optical import OpticalForensicsAnalyzer
from .analyzers.semantic import SemanticForensicsAnalyzer
from .analyzers.text_ai_detection import TextAiDetectionAnalyzer
from .analyzers.vae_reconstruction import VaeReconstructionAnalyzer
from .base import ForensicReport, ModuleResult
from .fusion import fuse_scores
from .triage import triage_file

logger = logging.getLogger(__name__)

# Type alias for progress callbacks: (module_name, cumulative_progress_pct)
ProgressCallback = Callable[[str, float], None] | None


class ForensicPipeline:
    def __init__(
        self,
        ela_quality: int = 95,
        ela_scale: int = 20,
        cnn_enabled: bool = True,
        optical_enabled: bool = True,
        semantic_enabled: bool = True,
        semantic_face_enabled: bool = True,
        semantic_vlm_enabled: bool = True,
        semantic_vlm_model: str = "google/gemini-2.5-pro-preview",
        openrouter_api_key: str = "",
        document_enabled: bool = True,
        document_signature_verification: bool = True,
        aigen_enabled: bool = True,
        spectral_enabled: bool = True,
        office_enabled: bool = True,
        clip_ai_enabled: bool = True,
        vae_recon_enabled: bool = True,
        text_ai_enabled: bool = True,
        prnu_enabled: bool = True,
    ):
        self._metadata = MetadataAnalyzer()
        self._modification = ModificationAnalyzer(
            ela_quality=ela_quality, ela_scale=ela_scale
        )
        self._cnn: CnnForensicsAnalyzer | None = (
            CnnForensicsAnalyzer() if cnn_enabled else None
        )
        self._optical: OpticalForensicsAnalyzer | None = (
            OpticalForensicsAnalyzer() if optical_enabled else None
        )
        self._semantic: SemanticForensicsAnalyzer | None = (
            SemanticForensicsAnalyzer(
                face_enabled=semantic_face_enabled,
                vlm_enabled=semantic_vlm_enabled,
                vlm_model=semantic_vlm_model,
                openrouter_api_key=openrouter_api_key,
            )
            if semantic_enabled
            else None
        )
        self._document: DocumentForensicsAnalyzer | None = (
            DocumentForensicsAnalyzer(
                signature_verification=document_signature_verification,
            )
            if document_enabled
            else None
        )
        self._spectral: SpectralForensicsAnalyzer | None = (
            SpectralForensicsAnalyzer() if spectral_enabled else None
        )
        self._aigen: AiGenerationAnalyzer | None = (
            AiGenerationAnalyzer() if aigen_enabled else None
        )
        self._office: OfficeForensicsAnalyzer | None = (
            OfficeForensicsAnalyzer() if office_enabled else None
        )
        # ── New AI detection modules ─────────────────────────────────
        self._clip_ai: ClipAiDetectionAnalyzer | None = (
            ClipAiDetectionAnalyzer() if clip_ai_enabled else None
        )
        self._vae_recon: VaeReconstructionAnalyzer | None = (
            VaeReconstructionAnalyzer() if vae_recon_enabled else None
        )
        self._text_ai: TextAiDetectionAnalyzer | None = (
            TextAiDetectionAnalyzer() if text_ai_enabled else None
        )
        self._prnu: PrnuDetectionAnalyzer | None = (
            PrnuDetectionAnalyzer() if prnu_enabled else None
        )

    def _count_active_modules(self, skip: set, file_category: str) -> int:
        """Count how many modules will actually run (for progress tracking)."""
        if file_category == "pdf":
            count = 0
            if self._document and self._document.MODULE_NAME not in skip:
                count += 1
            if self._text_ai and self._text_ai.MODULE_NAME not in skip:
                count += 1
            return count
        if file_category in ("docx", "xlsx"):
            count = 0
            if self._office and self._office.MODULE_NAME not in skip:
                count += 1
            if self._text_ai and self._text_ai.MODULE_NAME not in skip:
                count += 1
            return count
        # Image modules
        count = 0
        # Group 1 (parallel)
        if self._metadata.MODULE_NAME not in skip:
            count += 1
        if self._modification.MODULE_NAME not in skip:
            count += 1
        if self._optical and self._optical.MODULE_NAME not in skip:
            count += 1
        if self._spectral and self._spectral.MODULE_NAME not in skip:
            count += 1
        if self._clip_ai and self._clip_ai.MODULE_NAME not in skip:
            count += 1
        if self._prnu and self._prnu.MODULE_NAME not in skip:
            count += 1
        # Group 2 (sequential)
        if self._cnn and self._cnn.MODULE_NAME not in skip:
            count += 1
        if self._semantic and self._semantic.MODULE_NAME not in skip:
            count += 1
        if self._aigen and self._aigen.MODULE_NAME not in skip:
            count += 1
        if self._vae_recon and self._vae_recon.MODULE_NAME not in skip:
            count += 1
        return count

    def warmup_models(self) -> None:
        """Pre-load all ML models into memory at startup.
        This avoids the cold-start penalty on the first real request."""
        logger.info("Warming up forensic models...")
        if self._cnn:
            self._cnn._ensure_models()
            logger.info("CNN models ready")
        if self._aigen:
            self._aigen._ensure_models()
            logger.info("AI generation models ready")
        if self._clip_ai:
            self._clip_ai._ensure_models()
            logger.info("CLIP AI detection model ready")
        if self._vae_recon:
            self._vae_recon._ensure_models()
            logger.info("VAE reconstruction model ready")
        if self._text_ai:
            self._text_ai._ensure_models()
            logger.info("Text AI detection models ready")
        logger.info("Forensic model warmup complete")

    async def analyze(
        self,
        file_bytes: bytes,
        filename: str,
        skip_modules: list[str] | None = None,
        progress_callback: ProgressCallback = None,
    ) -> ForensicReport:
        skip = set(skip_modules or [])
        modules: list[ModuleResult] = []

        # ── Universal file triage (magic bytes) ──────────────────
        file_category, detected_mime = triage_file(file_bytes, filename)
        logger.info("File triage: %s → category=%s mime=%s", filename, file_category, detected_mime)

        # Count total modules to run (for progress tracking)
        total_steps = self._count_active_modules(skip, file_category)
        completed_steps = 0

        def _report_progress(module_name: str) -> None:
            nonlocal completed_steps
            completed_steps += 1
            if progress_callback:
                pct = completed_steps / max(total_steps, 1)
                progress_callback(module_name, round(pct, 2))

        if file_category == "pdf":
            # Run document forensics + text AI detection in parallel
            doc_tasks: list[tuple[str, asyncio.Task]] = []
            if self._document and self._document.MODULE_NAME not in skip:
                doc_tasks.append((
                    self._document.MODULE_NAME,
                    asyncio.ensure_future(self._document.analyze_document(file_bytes, filename)),
                ))
            if self._text_ai and self._text_ai.MODULE_NAME not in skip:
                doc_tasks.append((
                    self._text_ai.MODULE_NAME,
                    asyncio.ensure_future(self._text_ai.analyze_document(file_bytes, filename)),
                ))
            if doc_tasks:
                results = await asyncio.gather(
                    *[t for _, t in doc_tasks], return_exceptions=True
                )
                for (mod_name, _), result in zip(doc_tasks, results):
                    if isinstance(result, Exception):
                        logger.error("Module %s failed: %s", mod_name, result)
                        modules.append(ModuleResult(
                            module_name=mod_name, module_label=mod_name,
                            risk_score=0.0, risk_level="Low", error=str(result),
                        ))
                    else:
                        modules.append(result)
                    _report_progress(mod_name)

        elif file_category in ("docx", "xlsx"):
            # Run office forensics + text AI detection in parallel
            office_tasks: list[tuple[str, asyncio.Task]] = []
            if self._office and self._office.MODULE_NAME not in skip:
                office_tasks.append((
                    self._office.MODULE_NAME,
                    asyncio.ensure_future(self._office.analyze_document(file_bytes, filename)),
                ))
            if self._text_ai and self._text_ai.MODULE_NAME not in skip:
                office_tasks.append((
                    self._text_ai.MODULE_NAME,
                    asyncio.ensure_future(self._text_ai.analyze_document(file_bytes, filename)),
                ))
            if office_tasks:
                results = await asyncio.gather(
                    *[t for _, t in office_tasks], return_exceptions=True
                )
                for (mod_name, _), result in zip(office_tasks, results):
                    if isinstance(result, Exception):
                        logger.error("Module %s failed: %s", mod_name, result)
                        modules.append(ModuleResult(
                            module_name=mod_name, module_label=mod_name,
                            risk_score=0.0, risk_level="Low", error=str(result),
                        ))
                    else:
                        modules.append(result)
                    _report_progress(mod_name)

        else:  # image (default)
            # ── Group 1: Lightweight modules — run in PARALLEL ────────
            # These are CPU-light/medium and independent of each other.
            group1_tasks: list[tuple[str, asyncio.Task]] = []

            if self._metadata.MODULE_NAME not in skip:
                group1_tasks.append((
                    self._metadata.MODULE_NAME,
                    asyncio.ensure_future(self._metadata.analyze_image(file_bytes, filename)),
                ))
            if self._modification.MODULE_NAME not in skip:
                group1_tasks.append((
                    self._modification.MODULE_NAME,
                    asyncio.ensure_future(self._modification.analyze_image(file_bytes, filename)),
                ))
            if self._optical and self._optical.MODULE_NAME not in skip:
                group1_tasks.append((
                    self._optical.MODULE_NAME,
                    asyncio.ensure_future(self._optical.analyze_image(file_bytes, filename)),
                ))
            if self._spectral and self._spectral.MODULE_NAME not in skip:
                group1_tasks.append((
                    self._spectral.MODULE_NAME,
                    asyncio.ensure_future(self._spectral.analyze_image(file_bytes, filename)),
                ))
            # CLIP AI detection — lightweight forward pass, can run in parallel
            if self._clip_ai and self._clip_ai.MODULE_NAME not in skip:
                group1_tasks.append((
                    self._clip_ai.MODULE_NAME,
                    asyncio.ensure_future(self._clip_ai.analyze_image(file_bytes, filename)),
                ))
            # PRNU sensor noise — pure numpy/scipy, CPU-lightweight
            if self._prnu and self._prnu.MODULE_NAME not in skip:
                group1_tasks.append((
                    self._prnu.MODULE_NAME,
                    asyncio.ensure_future(self._prnu.analyze_image(file_bytes, filename)),
                ))

            # Await all Group 1 tasks concurrently
            if group1_tasks:
                task_objects = [t for _, t in group1_tasks]
                results = await asyncio.gather(*task_objects, return_exceptions=True)

                for (mod_name, _task), result in zip(group1_tasks, results):
                    if isinstance(result, Exception):
                        logger.error("Module %s failed: %s", mod_name, result)
                        modules.append(ModuleResult(
                            module_name=mod_name,
                            module_label=mod_name,
                            risk_score=0.0,
                            risk_level="Low",
                            error=str(result),
                        ))
                    else:
                        modules.append(result)
                    _report_progress(mod_name)

                logger.info(
                    "Group 1 (parallel) complete: %d modules in parallel",
                    len(group1_tasks),
                )

            # ── Group 2: Heavy ML modules — run SEQUENTIALLY ─────────
            # These consume significant memory; running them in parallel
            # would risk OOM on the CPU-only server.
            if self._cnn and self._cnn.MODULE_NAME not in skip:
                result = await self._cnn.analyze_image(file_bytes, filename)
                modules.append(result)
                _report_progress(self._cnn.MODULE_NAME)

            if self._semantic and self._semantic.MODULE_NAME not in skip:
                result = await self._semantic.analyze_image(file_bytes, filename)
                modules.append(result)
                _report_progress(self._semantic.MODULE_NAME)

            # AI generation detection — heaviest models, run last
            if self._aigen and self._aigen.MODULE_NAME not in skip:
                result = await self._aigen.analyze_image(file_bytes, filename)
                modules.append(result)
                _report_progress(self._aigen.MODULE_NAME)

            # VAE reconstruction error — requires SD VAE (~2GB RAM)
            if self._vae_recon and self._vae_recon.MODULE_NAME not in skip:
                result = await self._vae_recon.analyze_image(file_bytes, filename)
                modules.append(result)
                _report_progress(self._vae_recon.MODULE_NAME)

        overall_score, overall_score_100, overall_level = fuse_scores(modules)
        total_time = sum(m.processing_time_ms for m in modules)

        # Extract ELA heatmap if available, fall back to CNN heatmap
        ela_heatmap = self._modification.ela_heatmap_b64
        if ela_heatmap is None and self._cnn is not None:
            ela_heatmap = self._cnn.cnn_heatmap_b64

        # Extract FFT spectrum from optical analyzer
        fft_spectrum = (
            self._optical.fft_spectrum_b64 if self._optical else None
        )

        # Extract spectral heatmap from spectral forensics
        spectral_heatmap = (
            self._spectral.spectral_heatmap_b64 if self._spectral else None
        )

        # ── Extract C2PA status from metadata findings ────────────
        c2pa_status: str | None = "not_found"
        c2pa_issuer: str | None = None
        meta_modules = [m for m in modules if m.module_name == "metadata_analysis"]
        if meta_modules:
            for f in meta_modules[0].findings:
                if f.code == "META_C2PA_VALID":
                    c2pa_status = "valid"
                    c2pa_issuer = (f.evidence or {}).get("issuer")
                elif f.code == "META_C2PA_AI_GENERATED":
                    c2pa_status = "ai_generated"
                    c2pa_issuer = (f.evidence or {}).get("issuer")
                elif f.code == "META_C2PA_INVALID_SIGNATURE":
                    c2pa_status = "invalid"

        # ── Extract source generator attribution from AI gen ──────
        predicted_source: str | None = None
        source_confidence: int = 0
        aigen_modules = [m for m in modules if m.module_name == "ai_generation_detection"]
        if aigen_modules:
            for f in aigen_modules[0].findings:
                ev = f.evidence or {}
                if ev.get("predicted_generator"):
                    predicted_source = ev["predicted_generator"]
                    source_confidence = round((ev.get("generator_confidence", 0)) * 100)
                    break

        return ForensicReport(
            overall_risk_score=round(overall_score, 4),
            overall_risk_score_100=overall_score_100,
            overall_risk_level=overall_level,
            modules=modules,
            total_processing_time_ms=total_time,
            ela_heatmap_b64=ela_heatmap,
            fft_spectrum_b64=fft_spectrum,
            spectral_heatmap_b64=spectral_heatmap,
            predicted_source=predicted_source,
            source_confidence=source_confidence,
            c2pa_status=c2pa_status,
            c2pa_issuer=c2pa_issuer,
        )
