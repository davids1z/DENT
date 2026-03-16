import logging

from .analyzers.cnn_forensics import CnnForensicsAnalyzer
from .analyzers.metadata import MetadataAnalyzer
from .analyzers.modification import ModificationAnalyzer
from .analyzers.optical import OpticalForensicsAnalyzer
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
            logger.info("PDF forensics not yet implemented, skipping")
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

        return ForensicReport(
            overall_risk_score=round(overall_score, 4),
            overall_risk_level=overall_level,
            modules=modules,
            total_processing_time_ms=total_time,
            ela_heatmap_b64=ela_heatmap,
            fft_spectrum_b64=fft_spectrum,
        )
