from abc import ABC, abstractmethod
from enum import Enum

from pydantic import BaseModel


class RiskLevel(str, Enum):
    LOW = "Low"
    MEDIUM = "Medium"
    HIGH = "High"
    CRITICAL = "Critical"


class AnalyzerFinding(BaseModel):
    code: str
    title: str
    description: str
    risk_score: float
    confidence: float
    evidence: dict | None = None


class ModuleResult(BaseModel):
    module_name: str
    module_label: str
    risk_score: float
    risk_score100: int = 0
    risk_level: RiskLevel
    findings: list[AnalyzerFinding] = []
    processing_time_ms: int = 0
    error: str | None = None
    # Per-result heatmaps and visual artefacts. The 2026-04-07 audit
    # discovered that several analyzers (modification.py, cnn_forensics.py,
    # spectral_forensics.py, optical.py) were storing heatmaps as instance
    # state on `self`, then re-reading them after the per-request task had
    # already finished. With MAX_CONCURRENT_ANALYSES > 1, request B could
    # overwrite request A's heatmap during the brief window between
    # "store on self" and "read from self in pipeline.py", silently
    # serving the wrong heatmap to the wrong user. Production runs at
    # MAX_CONCURRENT_ANALYSES=1 so the bug never bit, but the dev compose
    # uses 2 and the latent risk is unacceptable for a forensic tool.
    # Now every analyzer puts its heatmap directly on the ModuleResult,
    # so the bytes travel with the request through the future-pool and
    # cannot be cross-contaminated.
    heatmaps: dict[str, str] = {}


class ForensicReport(BaseModel):
    overall_risk_score: float
    overall_risk_score100: int = 0
    overall_risk_level: RiskLevel
    modules: list[ModuleResult] = []
    total_processing_time_ms: int = 0
    ela_heatmap_b64: str | None = None
    fft_spectrum_b64: str | None = None
    spectral_heatmap_b64: str | None = None
    ai_region_heatmap_b64: str | None = None
    copy_move_heatmap_b64: str | None = None
    # Source generator attribution
    predicted_source: str | None = None
    source_confidence: int = 0
    # C2PA provenance (promoted from metadata findings)
    c2pa_status: str | None = None  # "valid" | "invalid" | "ai_generated" | "not_found"
    c2pa_issuer: str | None = None
    # 3-class meta-learner probabilities
    verdict_probabilities: dict[str, float] | None = None
    # PDF page previews (base64-encoded PNG images)
    page_previews_b64: list[str] | None = None
    # Perceptual hash for duplicate/similarity detection (16-char hex)
    perceptual_hash: str | None = None
    # CLIP embedding for semantic similarity (base64-encoded float16 768-dim)
    clip_embedding_b64: str | None = None


class CrossImageFinding(BaseModel):
    code: str
    title: str
    description: str
    risk_score: float
    confidence: float
    affected_files: list[int] = []  # SortOrder indices
    evidence: dict | None = None


class CrossImageReport(BaseModel):
    findings: list[CrossImageFinding] = []
    group_risk_modifier: float = 0.0
    processing_time_ms: int = 0


class BatchGroupResponse(BaseModel):
    per_file_reports: list[ForensicReport] = []
    cross_image_report: CrossImageReport = CrossImageReport()


class BaseAnalyzer(ABC):
    MODULE_NAME: str = ""
    MODULE_LABEL: str = ""

    @abstractmethod
    async def analyze_image(self, image_bytes: bytes, filename: str) -> ModuleResult:
        ...

    @abstractmethod
    async def analyze_document(self, doc_bytes: bytes, filename: str) -> ModuleResult:
        ...

    def _risk_level(self, score: float) -> RiskLevel:
        if score >= 0.75:
            return RiskLevel.CRITICAL
        if score >= 0.50:
            return RiskLevel.HIGH
        if score >= 0.25:
            return RiskLevel.MEDIUM
        return RiskLevel.LOW

    def _make_result(
        self,
        findings: list[AnalyzerFinding],
        processing_time_ms: int = 0,
        error: str | None = None,
    ) -> ModuleResult:
        if error:
            return ModuleResult(
                module_name=self.MODULE_NAME,
                module_label=self.MODULE_LABEL,
                risk_score=0.0,
                risk_score100=0,
                risk_level=RiskLevel.LOW,
                findings=[],
                processing_time_ms=processing_time_ms,
                error=error,
            )

        if not findings:
            return ModuleResult(
                module_name=self.MODULE_NAME,
                module_label=self.MODULE_LABEL,
                risk_score=0.0,
                risk_score100=0,
                risk_level=RiskLevel.LOW,
                findings=[],
                processing_time_ms=processing_time_ms,
            )

        # Separate positive-risk findings from risk-reducing ones (e.g. valid C2PA)
        positive = [f.risk_score for f in findings if f.risk_score > 0]
        negative = [f.risk_score for f in findings if f.risk_score < 0]

        risk_score = max(positive) if positive else 0.0
        # Apply risk reductions from trust signals (e.g. C2PA valid = -0.10)
        risk_score = risk_score + sum(negative)
        risk_score = max(0.0, min(1.0, risk_score))

        return ModuleResult(
            module_name=self.MODULE_NAME,
            module_label=self.MODULE_LABEL,
            risk_score=risk_score,
            risk_score100=round(risk_score * 100),
            risk_level=self._risk_level(risk_score),
            findings=findings,
            processing_time_ms=processing_time_ms,
        )
