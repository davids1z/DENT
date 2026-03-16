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
    risk_level: RiskLevel
    findings: list[AnalyzerFinding] = []
    processing_time_ms: int = 0
    error: str | None = None


class ForensicReport(BaseModel):
    overall_risk_score: float
    overall_risk_level: RiskLevel
    modules: list[ModuleResult] = []
    total_processing_time_ms: int = 0
    ela_heatmap_b64: str | None = None
    fft_spectrum_b64: str | None = None


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
            risk_level=self._risk_level(risk_score),
            findings=findings,
            processing_time_ms=processing_time_ms,
        )
