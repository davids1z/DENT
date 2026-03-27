import asyncio
import io
import logging
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor

from .analyzers.ai_generation import AiGenerationAnalyzer
from .analyzers.clip_ai_detection import ClipAiDetectionAnalyzer
from .analyzers.dinov2_ai_detection import DINOv2AiDetectionAnalyzer
from .analyzers.cnn_forensics import CnnForensicsAnalyzer
from .analyzers.efficientnet_ai_detection import EfficientNetAiDetectionAnalyzer
from .analyzers.safe_ai_detection import SAFEAiDetectionAnalyzer
from .analyzers.community_forensics import CommunityForensicsAnalyzer
from .analyzers.mesorch_forensics import MesorchForensicsAnalyzer
from .analyzers.npr_detection import NprDetectionAnalyzer
from .analyzers.prnu_detection import PrnuDetectionAnalyzer
from .analyzers.spectral_forensics import SpectralForensicsAnalyzer
from .analyzers.document import DocumentForensicsAnalyzer
from .analyzers.metadata import MetadataAnalyzer
from .analyzers.modification import ModificationAnalyzer
from .analyzers.office import OfficeForensicsAnalyzer
from .analyzers.optical import OpticalForensicsAnalyzer
from .analyzers.semantic import SemanticForensicsAnalyzer
from .analyzers.text_ai_detection import TextAiDetectionAnalyzer
from .analyzers.content_validation import ContentValidationAnalyzer
from .analyzers.bfree_detection import BFreeDetectionAnalyzer
from .analyzers.spai_detection import SPAIDetectionAnalyzer
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
        mesorch_enabled: bool = True,
        optical_enabled: bool = True,
        semantic_enabled: bool = True,
        semantic_face_enabled: bool = True,
        semantic_vlm_enabled: bool = True,
        semantic_vlm_model: str = "google/gemini-2.5-pro-preview",
        openrouter_api_key: str = "",
        document_enabled: bool = True,
        document_signature_verification: bool = True,
        aigen_enabled: bool = True,
        efficientnet_ai_enabled: bool = True,
        safe_ai_enabled: bool = True,
        dinov2_ai_enabled: bool = True,
        bfree_enabled: bool = False,
        spai_enabled: bool = False,
        spectral_enabled: bool = True,
        office_enabled: bool = True,
        community_forensics_enabled: bool = True,
        npr_enabled: bool = False,
        clip_ai_enabled: bool = True,
        vae_recon_enabled: bool = True,
        text_ai_enabled: bool = True,
        prnu_enabled: bool = True,
        content_validation_enabled: bool = True,
        content_validation_ocr_lang: str = "hrv+eng",
        embedded_image_forensics_enabled: bool = True,
    ):
        self._embedded_img_enabled = embedded_image_forensics_enabled
        # Thread pool for CPU-bound modules — PyTorch releases GIL during
        # tensor ops, so threads give real parallelism on multi-core CPUs.
        self._executor = ThreadPoolExecutor(max_workers=4)
        self._metadata = MetadataAnalyzer()
        self._modification = ModificationAnalyzer(
            ela_quality=ela_quality, ela_scale=ela_scale
        )
        self._cnn: CnnForensicsAnalyzer | None = (
            CnnForensicsAnalyzer() if cnn_enabled else None
        )
        self._mesorch: MesorchForensicsAnalyzer | None = (
            MesorchForensicsAnalyzer() if mesorch_enabled else None
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
        self._efficientnet: EfficientNetAiDetectionAnalyzer | None = (
            EfficientNetAiDetectionAnalyzer() if efficientnet_ai_enabled else None
        )
        self._safe: SAFEAiDetectionAnalyzer | None = (
            SAFEAiDetectionAnalyzer() if safe_ai_enabled else None
        )
        self._dinov2: DINOv2AiDetectionAnalyzer | None = (
            DINOv2AiDetectionAnalyzer() if dinov2_ai_enabled else None
        )
        self._commfor: CommunityForensicsAnalyzer | None = (
            CommunityForensicsAnalyzer() if community_forensics_enabled else None
        )
        self._bfree: BFreeDetectionAnalyzer | None = (
            BFreeDetectionAnalyzer() if bfree_enabled else None
        )
        self._spai: SPAIDetectionAnalyzer | None = (
            SPAIDetectionAnalyzer() if spai_enabled else None
        )
        self._npr: NprDetectionAnalyzer | None = (
            NprDetectionAnalyzer() if npr_enabled else None
        )
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
        self._content_val: ContentValidationAnalyzer | None = (
            ContentValidationAnalyzer(ocr_lang=content_validation_ocr_lang)
            if content_validation_enabled
            else None
        )

    # ------------------------------------------------------------------
    # PDF Page Preview Rendering
    # ------------------------------------------------------------------

    @staticmethod
    def _render_pdf_pages(
        doc_bytes: bytes, max_pages: int = 5, dpi: int = 150
    ) -> list[str]:
        """Render first N pages of a PDF as base64-encoded JPEG images."""
        import base64
        import fitz

        doc = fitz.open(stream=doc_bytes, filetype="pdf")
        previews: list[str] = []
        try:
            for page_idx in range(min(len(doc), max_pages)):
                page = doc[page_idx]
                pix = page.get_pixmap(dpi=dpi)
                # Use JPEG for smaller payload (~3-5x smaller than PNG)
                img_bytes = pix.tobytes("jpeg")
                previews.append(base64.b64encode(img_bytes).decode())
        finally:
            doc.close()

        logger.info("Rendered %d PDF page previews (%d DPI)", len(previews), dpi)
        return previews

    # ------------------------------------------------------------------
    # PDF Embedded Image Extraction + Visual Forensics
    # ------------------------------------------------------------------

    def _extract_pdf_images(self, doc_bytes: bytes) -> list[bytes]:
        """Extract embedded images from PDF via PyMuPDF.

        Returns up to 10 largest images (>100x100 px) as bytes.
        """
        try:
            import fitz
        except ImportError:
            return []

        images: list[tuple[int, bytes]] = []  # (size, image_bytes)

        try:
            doc = fitz.open(stream=doc_bytes, filetype="pdf")
            seen_xrefs: set[int] = set()

            for page_idx in range(min(len(doc), 20)):
                page = doc[page_idx]
                img_list = page.get_images(full=True)

                for img_info in img_list:
                    xref = img_info[0]
                    if xref in seen_xrefs or xref <= 0:
                        continue
                    seen_xrefs.add(xref)

                    try:
                        base_image = doc.extract_image(xref)
                        if not base_image:
                            continue

                        img_bytes = base_image.get("image")
                        width = base_image.get("width", 0)
                        height = base_image.get("height", 0)

                        # Skip tiny images (icons, logos, decorative)
                        if width < 100 or height < 100:
                            continue
                        if not img_bytes or len(img_bytes) < 500:
                            continue

                        images.append((len(img_bytes), img_bytes))
                    except Exception:
                        continue

            doc.close()
        except Exception as e:
            logger.debug("PDF image extraction error: %s", e)
            return []

        # Return top 10 largest images
        images.sort(key=lambda x: x[0], reverse=True)
        return [img_bytes for _, img_bytes in images[:10]]

    async def _run_embedded_image_forensics(
        self, embedded_images: list[bytes], doc_module: ModuleResult | None
    ) -> None:
        """Run visual forensics on embedded PDF images and add findings to doc module."""
        if not embedded_images or doc_module is None:
            return

        from .base import AnalyzerFinding

        for i, img_bytes in enumerate(embedded_images[:5]):  # Limit to 5 for performance
            img_name = f"embedded_image_{i}"

            # Run ELA (modification detection) on the embedded image
            try:
                ela_result = await self._modification.analyze_image(img_bytes, img_name)
                if ela_result.risk_score >= 0.50:
                    doc_module.findings.append(
                        AnalyzerFinding(
                            code="DOC_EMBEDDED_IMG_ELA_ANOMALY",
                            title=f"ELA anomalija u ugradenoj slici #{i + 1}",
                            description=(
                                f"Error Level Analysis detektirao je anomalije u slici "
                                f"ugradenoj unutar PDF-a (rizik {round(ela_result.risk_score * 100)}%). "
                                f"Moguca manipulacija piksela na fotografiji unutar dokumenta."
                            ),
                            risk_score=ela_result.risk_score * 0.8,  # Slightly dampened
                            confidence=0.75,
                            evidence={
                                "image_index": i,
                                "ela_risk": round(ela_result.risk_score, 3),
                                "image_size_bytes": len(img_bytes),
                            },
                        )
                    )
            except Exception as e:
                logger.debug("ELA on embedded image %d failed: %s", i, e)

            # Run spectral forensics if available
            if self._spectral:
                try:
                    spectral_result = await self._spectral.analyze_image(img_bytes, img_name)
                    if spectral_result.risk_score >= 0.50:
                        doc_module.findings.append(
                            AnalyzerFinding(
                                code="DOC_EMBEDDED_IMG_SPECTRAL_ANOMALY",
                                title=f"Spektralna anomalija u ugradenoj slici #{i + 1}",
                                description=(
                                    f"Spektralna analiza frekvencijskog prostora ukazuje na "
                                    f"moguce AI-generiran sadrzaj ili manipulaciju u ugradenoj slici."
                                ),
                                risk_score=spectral_result.risk_score * 0.7,
                                confidence=0.70,
                                evidence={
                                    "image_index": i,
                                    "spectral_risk": round(spectral_result.risk_score, 3),
                                },
                            )
                        )
                except Exception as e:
                    logger.debug("Spectral on embedded image %d failed: %s", i, e)

        # Recalculate doc module risk score after adding new findings
        if doc_module.findings:
            positive = [f.risk_score for f in doc_module.findings if f.risk_score > 0]
            negative = [f.risk_score for f in doc_module.findings if f.risk_score < 0]
            new_risk = (max(positive) if positive else 0.0) + sum(negative)
            doc_module.risk_score = max(0.0, min(1.0, new_risk))
            doc_module.risk_score100 = round(doc_module.risk_score * 100)

    def _count_active_modules(self, skip: set, file_category: str) -> int:
        """Count how many modules will actually run (for progress tracking)."""
        if file_category == "pdf":
            count = 0
            if self._document and self._document.MODULE_NAME not in skip:
                count += 1
            if self._text_ai and self._text_ai.MODULE_NAME not in skip:
                count += 1
            if self._content_val and self._content_val.MODULE_NAME not in skip:
                count += 1
            if self._embedded_img_enabled:
                count += 1  # Embedded image forensics step
            return count
        if file_category in ("docx", "xlsx"):
            count = 0
            if self._office and self._office.MODULE_NAME not in skip:
                count += 1
            if self._text_ai and self._text_ai.MODULE_NAME not in skip:
                count += 1
            if self._content_val and self._content_val.MODULE_NAME not in skip:
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
        if self._npr and self._npr.MODULE_NAME not in skip:
            count += 1
        if self._prnu and self._prnu.MODULE_NAME not in skip:
            count += 1
        # Group 2 (sequential)
        if self._cnn and self._cnn.MODULE_NAME not in skip:
            count += 1
        if self._mesorch and self._mesorch.MODULE_NAME not in skip:
            count += 1
        if self._semantic and self._semantic.MODULE_NAME not in skip:
            count += 1
        if self._commfor and self._commfor.MODULE_NAME not in skip:
            count += 1
        if self._efficientnet and self._efficientnet.MODULE_NAME not in skip:
            count += 1
        if self._safe and self._safe.MODULE_NAME not in skip:
            count += 1
        if self._dinov2 and self._dinov2.MODULE_NAME not in skip:
            count += 1
        if self._bfree and self._bfree.MODULE_NAME not in skip:
            count += 1
        if self._spai and self._spai.MODULE_NAME not in skip:
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
        if self._mesorch:
            self._mesorch._ensure_models()
            logger.info("Mesorch model ready")
        if self._aigen:
            self._aigen._ensure_models()
            logger.info("AI generation models ready")
        if self._efficientnet:
            self._efficientnet._ensure_models()
            logger.info("EfficientNet-B4 AI detector ready")
        if self._safe:
            self._safe._ensure_models()
            logger.info("SAFE AI detector ready")
        if self._dinov2:
            self._dinov2._ensure_models()
            logger.info("DINOv2 AI detector ready")
        if self._bfree:
            self._bfree._ensure_models()
            logger.info("B-Free AI detector ready")
        if self._spai:
            self._spai._ensure_models()
            logger.info("SPAI spectral AI detector ready")
        if self._commfor:
            self._commfor._ensure_models()
            logger.info("Community Forensics model ready")
        if self._npr:
            self._npr._ensure_models()
            logger.info("NPR model ready")
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
            if self._content_val and self._content_val.MODULE_NAME not in skip:
                doc_tasks.append((
                    self._content_val.MODULE_NAME,
                    asyncio.ensure_future(self._content_val.analyze_document(file_bytes, filename)),
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

            # ── Embedded image forensics (ELA + spectral on PDF images) ──
            if self._embedded_img_enabled:
                try:
                    embedded_images = self._extract_pdf_images(file_bytes)
                    if embedded_images:
                        logger.info(
                            "Extracted %d embedded images from PDF, running visual forensics",
                            len(embedded_images),
                        )
                        # Find document_forensics module to append findings
                        doc_mod = next(
                            (m for m in modules if m.module_name == "document_forensics"),
                            None,
                        )
                        await self._run_embedded_image_forensics(embedded_images, doc_mod)
                except Exception as e:
                    logger.debug("Embedded image forensics error: %s", e)
                _report_progress("embedded_image_forensics")

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
            if self._content_val and self._content_val.MODULE_NAME not in skip:
                office_tasks.append((
                    self._content_val.MODULE_NAME,
                    asyncio.ensure_future(self._content_val.analyze_document(file_bytes, filename)),
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
            import time as _time
            _wall_start = _time.perf_counter()

            # ── ALL modules in PARALLEL via thread pool ────────────────
            # PyTorch releases GIL during tensor ops, so ThreadPoolExecutor
            # gives real CPU parallelism on multi-core servers.
            # Total time ≈ max(slowest module) instead of sum(all modules).
            all_analyzers: list[tuple[str, object]] = []

            # Lightweight modules
            if self._metadata.MODULE_NAME not in skip:
                all_analyzers.append((self._metadata.MODULE_NAME, self._metadata))
            if self._modification.MODULE_NAME not in skip:
                all_analyzers.append((self._modification.MODULE_NAME, self._modification))
            if self._optical and self._optical.MODULE_NAME not in skip:
                all_analyzers.append((self._optical.MODULE_NAME, self._optical))
            if self._spectral and self._spectral.MODULE_NAME not in skip:
                all_analyzers.append((self._spectral.MODULE_NAME, self._spectral))
            if self._clip_ai and self._clip_ai.MODULE_NAME not in skip:
                all_analyzers.append((self._clip_ai.MODULE_NAME, self._clip_ai))
            if self._npr and self._npr.MODULE_NAME not in skip:
                all_analyzers.append((self._npr.MODULE_NAME, self._npr))
            if self._prnu and self._prnu.MODULE_NAME not in skip:
                all_analyzers.append((self._prnu.MODULE_NAME, self._prnu))
            # Heavy ML modules (previously Group 2 — sequential)
            if self._cnn and self._cnn.MODULE_NAME not in skip:
                all_analyzers.append((self._cnn.MODULE_NAME, self._cnn))
            if self._mesorch and self._mesorch.MODULE_NAME not in skip:
                all_analyzers.append((self._mesorch.MODULE_NAME, self._mesorch))
            if self._semantic and self._semantic.MODULE_NAME not in skip:
                all_analyzers.append((self._semantic.MODULE_NAME, self._semantic))
            if self._aigen and self._aigen.MODULE_NAME not in skip:
                all_analyzers.append((self._aigen.MODULE_NAME, self._aigen))
            if self._efficientnet and self._efficientnet.MODULE_NAME not in skip:
                all_analyzers.append((self._efficientnet.MODULE_NAME, self._efficientnet))
            if self._safe and self._safe.MODULE_NAME not in skip:
                all_analyzers.append((self._safe.MODULE_NAME, self._safe))
            if self._dinov2 and self._dinov2.MODULE_NAME not in skip:
                all_analyzers.append((self._dinov2.MODULE_NAME, self._dinov2))
            if self._bfree and self._bfree.MODULE_NAME not in skip:
                all_analyzers.append((self._bfree.MODULE_NAME, self._bfree))
            if self._spai and self._spai.MODULE_NAME not in skip:
                all_analyzers.append((self._spai.MODULE_NAME, self._spai))
            if self._commfor and self._commfor.MODULE_NAME not in skip:
                all_analyzers.append((self._commfor.MODULE_NAME, self._commfor))
            if self._vae_recon and self._vae_recon.MODULE_NAME not in skip:
                all_analyzers.append((self._vae_recon.MODULE_NAME, self._vae_recon))

            if all_analyzers:
                loop = asyncio.get_event_loop()

                async def _run_module(name: str, analyzer) -> tuple[str, ModuleResult | Exception]:
                    try:
                        result = await loop.run_in_executor(
                            self._executor,
                            lambda: asyncio.run(analyzer.analyze_image(file_bytes, filename)),
                        )
                        return name, result
                    except Exception as e:
                        return name, e

                tasks = [_run_module(name, analyzer) for name, analyzer in all_analyzers]
                results = await asyncio.gather(*tasks)

                for mod_name, result in results:
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
                    "All %d modules complete (parallel thread pool)",
                    len(all_analyzers),
                )

        overall_score, overall_score_100, overall_level, verdict_probs = fuse_scores(modules)
        # Use wall clock time for images (modules run in parallel).
        # For documents, sum is correct (sequential execution).
        if file_category not in ("pdf", "docx", "xlsx"):
            total_time = int((_time.perf_counter() - _wall_start) * 1000)
        else:
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

        # ── PDF page previews (render first 5 pages as PNG) ──
        page_previews: list[str] | None = None
        if file_category == "pdf":
            try:
                page_previews = self._render_pdf_pages(file_bytes, max_pages=5, dpi=150)
            except Exception as e:
                logger.debug("PDF page preview rendering failed: %s", e)

        return ForensicReport(
            overall_risk_score=round(overall_score, 4),
            overall_risk_score100=overall_score_100,
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
            verdict_probabilities=verdict_probs,
            page_previews_b64=page_previews,
        )
