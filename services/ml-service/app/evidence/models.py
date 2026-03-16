from __future__ import annotations

from pydantic import BaseModel


class TimestampRequest(BaseModel):
    evidence_hash: str  # hex-encoded SHA-256


class TimestampResponse(BaseModel):
    success: bool
    timestamp_token: str | None = None  # Base64-encoded DER
    timestamped_at: str | None = None  # ISO 8601
    tsa_url: str | None = None
    error: str | None = None


class CustodyEvent(BaseModel):
    event: str
    timestamp: str
    hash: str | None = None
    details: str | None = None


class DamageItem(BaseModel):
    damage_type: str = ""
    car_part: str = ""
    severity: str = ""
    description: str = ""
    confidence: float = 0.0
    repair_method: str | None = None
    estimated_cost_min: float | None = None
    estimated_cost_max: float | None = None
    damage_cause: str | None = None
    safety_rating: str | None = None


class ForensicModuleItem(BaseModel):
    module_name: str = ""
    module_label: str = ""
    risk_score: float = 0.0
    risk_level: str = "Low"
    findings: list[dict] = []


class AgentDecisionItem(BaseModel):
    outcome: str = "HumanReview"
    confidence: float = 0.0
    summary_hr: str = ""
    stp_eligible: bool = False
    fraud_indicators: list[str] = []
    recommended_actions: list[str] = []


class ImageHashItem(BaseModel):
    file_name: str = ""
    sha256: str = ""


class ReportRequest(BaseModel):
    inspection_id: str = ""
    created_at: str = ""
    completed_at: str | None = None
    # Vehicle
    vehicle_make: str | None = None
    vehicle_model: str | None = None
    vehicle_year: int | None = None
    vehicle_color: str | None = None
    # Costs
    total_estimated_cost_min: float | None = None
    total_estimated_cost_max: float | None = None
    gross_total: float | None = None
    currency: str = "EUR"
    labor_total: float | None = None
    parts_total: float | None = None
    materials_total: float | None = None
    # Condition
    is_driveable: bool | None = None
    urgency_level: str | None = None
    structural_integrity: str | None = None
    summary: str | None = None
    # Decision
    decision_outcome: str | None = None
    decision_reason: str | None = None
    # Forensic summary
    fraud_risk_score: float | None = None
    fraud_risk_level: str | None = None
    forensic_modules: list[ForensicModuleItem] = []
    # Agent
    agent_decision: AgentDecisionItem | None = None
    # Damages
    damages: list[DamageItem] = []
    # Evidence integrity
    evidence_hash: str | None = None
    image_hashes: list[ImageHashItem] = []
    forensic_result_hash: str | None = None
    agent_decision_hash: str | None = None
    chain_of_custody: list[CustodyEvent] = []
    timestamp_token: str | None = None
    timestamped_at: str | None = None
    timestamp_authority: str | None = None


# Certificate uses same schema
CertificateRequest = ReportRequest
