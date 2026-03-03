from pydantic import BaseModel


class BoundingBox(BaseModel):
    x: float  # left edge, 0-1 percentage of image width
    y: float  # top edge, 0-1 percentage of image height
    w: float  # width, 0-1 percentage
    h: float  # height, 0-1 percentage
    image_index: int = 0  # which image this box belongs to (0-based)


class RepairLineItem(BaseModel):
    line_number: int
    part_name: str
    operation: str  # Repair, Replace, Refinish, Blend, Remove/Install, Check/Adjust
    labor_type: str  # Body, Refinish, Glass, Mechanical
    labor_hours: float
    part_type: str = "Existing"  # OEM, Aftermarket, Used, Existing
    quantity: int = 1
    unit_cost: float | None = None
    total_cost: float | None = None


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
    # Forensic fields
    bounding_box: BoundingBox | None = None
    damage_cause: str | None = None
    safety_rating: str | None = None  # Safe, Warning, Critical
    material_type: str | None = None
    repair_operations: str | None = None  # detailed step-by-step
    repair_category: str | None = None  # Replace, Repair, Polish
    # Structured repair line items
    repair_line_items: list[RepairLineItem] = []


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
    structural_integrity: str | None = None
    damages: list[DamageResult] = []
    # Structured totals
    labor_total: float | None = None
    parts_total: float | None = None
    materials_total: float | None = None
    gross_total: float | None = None


# Multi-image request models
class ImageData(BaseModel):
    data: str  # base64 encoded
    media_type: str
    filename: str


class MultiImageRequest(BaseModel):
    images: list[ImageData]
    vehicle_make: str | None = None
    vehicle_model: str | None = None
    vehicle_year: int | None = None
    mileage: int | None = None
