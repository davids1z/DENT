import logging

from .analyzers.ai_generation import AiGenerationAnalyzer
from .analyzers.cnn_forensics import CnnForensicsAnalyzer
from .analyzers.spectral_forensics import SpectralForensicsAnalyzer
from .analyzers.document import DocumentForensicsAnalyzer
from .analyzers.metadata import MetadataAnalyzer
from .analyzers.modification import ModificationAnalyzer
from .analyzers.optical import OpticalForensicsAnalyzer
from .analyzers.semantic import SemanticForensicsAnalyzer
from .base import ForensicReport, ModuleResult
from .fusion import fuse_scores

logger = logging.getLogger(__name__)


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

    async def analyze(
        self,
        file_bytes: bytes,
        filename: str,
        skip_modules: list[str] | None = None,
    ) -> ForensicReport:
        skip = set(skip_modules or [])
        modules: list[ModuleResult] = []
        is_pdf = filename.lower().endswith(".pdf")

        if is_pdf:
            if self._document and self._document.MODULE_NAME not in skip:
                result = await self._document.analyze_document(file_bytes, filename)
                modules.append(result)
        else:
            # Run image analyzers sequentially to avoid memory pressure
            if self._metadata.MODULE_NAME not in skip:
                result = await self._metadata.analyze_image(file_bytes, filename)
                modules.append(result)

            if self._modification.MODULE_NAME not in skip:
                result = await self._modification.analyze_image(file_bytes, filename)
                modules.append(result)

            if self._cnn and self._cnn.MODULE_NAME not in skip:
                result = await self._cnn.analyze_image(file_bytes, filename)
                modules.append(result)

            if self._optical and self._optical.MODULE_NAME not in skip:
                result = await self._optical.analyze_image(file_bytes, filename)
                modules.append(result)

            if self._semantic and self._semantic.MODULE_NAME not in skip:
                result = await self._semantic.analyze_image(file_bytes, filename)
                modules.append(result)

            # Spectral forensics — frequency-domain AI detection (F2D-Net approach)
            if self._spectral and self._spectral.MODULE_NAME not in skip:
                result = await self._spectral.analyze_image(file_bytes, filename)
                modules.append(result)

            # AI generation detection — run last (heaviest models, most memory)
            if self._aigen and self._aigen.MODULE_NAME not in skip:
                result = await self._aigen.analyze_image(file_bytes, filename)
                modules.append(result)

        overall_score, overall_level = fuse_scores(modules)
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

        return ForensicReport(
            overall_risk_score=round(overall_score, 4),
            overall_risk_level=overall_level,
            modules=modules,
            total_processing_time_ms=total_time,
            ela_heatmap_b64=ela_heatmap,
            fft_spectrum_b64=fft_spectrum,
            spectral_heatmap_b64=spectral_heatmap,
        )
