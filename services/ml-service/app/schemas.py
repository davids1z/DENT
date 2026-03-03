from pydantic import BaseModel


class DamageResult(BaseModel):
    damage_type: str
    car_part: str
    severity: str
    description: str
    confidence: float
    repair_method: str | None = None
    estimated_cost_min: float | None = None
    estimated_cost_max: float | None = None
    labor_hours: float | None = None
    parts_needed: str | None = None


class AnalysisResponse(BaseModel):
    success: bool
    error_message: str | None = None
    vehicle_make: str | None = None
    vehicle_model: str | None = None
    vehicle_year: int | None = None
    vehicle_color: str | None = None
    summary: str | None = None
    total_estimated_cost_min: float | None = None
    total_estimated_cost_max: float | None = None
    is_driveable: bool | None = None
    urgency_level: str | None = None
    damages: list[DamageResult] = []
