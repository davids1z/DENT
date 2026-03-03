import base64
import json
import logging

import anthropic
from fastapi import APIRouter, File, HTTPException, UploadFile

from ..config import settings
from ..schemas import AnalysisResponse, DamageResult

router = APIRouter()
logger = logging.getLogger(__name__)

ANALYSIS_PROMPT = """You are an expert automotive damage assessor. Analyze this image of a vehicle and provide a detailed damage assessment.

You MUST respond with valid JSON only, no other text. Use this exact structure:

{
  "vehicle_info": {
    "make": "string or null",
    "model": "string or null",
    "year": "integer or null",
    "color": "string or null"
  },
  "damages": [
    {
      "damage_type": "one of: Scratch, Dent, Crack, PaintDamage, BrokenGlass, Rust, BodyDeformation, BumperDamage, LightDamage, TireDamage, MirrorDamage, Other",
      "car_part": "one of: FrontBumper, RearBumper, Hood, Trunk, FrontLeftDoor, FrontRightDoor, RearLeftDoor, RearRightDoor, FrontLeftFender, FrontRightFender, RearLeftFender, RearRightFender, Roof, Windshield, RearWindow, SideWindowLeft, SideWindowRight, SideMirrorLeft, SideMirrorRight, HeadlightLeft, HeadlightRight, TaillightLeft, TaillightRight, WheelFrontLeft, WheelFrontRight, WheelRearLeft, WheelRearRight, Undercarriage, Other",
      "severity": "one of: Minor, Moderate, Severe, Critical",
      "description": "Detailed description of the damage in 1-2 sentences",
      "confidence": 0.95,
      "repair_method": "Description of recommended repair method",
      "estimated_cost_min": 100,
      "estimated_cost_max": 300,
      "labor_hours": 2.0,
      "parts_needed": "List of parts needed, or null if none"
    }
  ],
  "overall_assessment": {
    "summary": "2-3 sentence overall assessment of the vehicle damage",
    "total_cost_min": 100,
    "total_cost_max": 500,
    "is_driveable": true,
    "urgency_level": "one of: Low, Medium, High, Critical"
  }
}

Cost estimates should be in EUR. Be thorough and identify ALL visible damage. If you cannot identify the vehicle make/model, set those fields to null. If the image does not show a vehicle or vehicle damage, set damages to an empty array and explain in the summary."""


def get_media_type(filename: str) -> str:
    ext = filename.lower().rsplit(".", 1)[-1] if "." in filename else ""
    return {
        "jpg": "image/jpeg",
        "jpeg": "image/jpeg",
        "png": "image/png",
        "webp": "image/webp",
        "gif": "image/gif",
    }.get(ext, "image/jpeg")


@router.post("/analyze", response_model=AnalysisResponse)
async def analyze_image(file: UploadFile = File(...)):
    if not settings.anthropic_api_key:
        raise HTTPException(status_code=500, detail="Anthropic API key not configured")

    contents = await file.read()
    size_mb = len(contents) / (1024 * 1024)

    if size_mb > settings.max_image_size_mb:
        raise HTTPException(
            status_code=413,
            detail=f"Image too large: {size_mb:.1f}MB (max {settings.max_image_size_mb}MB)",
        )

    image_b64 = base64.b64encode(contents).decode("utf-8")
    media_type = get_media_type(file.filename or "image.jpg")

    try:
        client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

        message = client.messages.create(
            model=settings.claude_model,
            max_tokens=4096,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": media_type,
                                "data": image_b64,
                            },
                        },
                        {"type": "text", "text": ANALYSIS_PROMPT},
                    ],
                }
            ],
        )

        response_text = message.content[0].text
        # Extract JSON from response (handle markdown code blocks)
        if "```json" in response_text:
            response_text = response_text.split("```json")[1].split("```")[0].strip()
        elif "```" in response_text:
            response_text = response_text.split("```")[1].split("```")[0].strip()

        data = json.loads(response_text)

        vehicle = data.get("vehicle_info", {})
        assessment = data.get("overall_assessment", {})
        damages_raw = data.get("damages", [])

        damages = []
        for d in damages_raw:
            damages.append(
                DamageResult(
                    damage_type=d.get("damage_type", "Other"),
                    car_part=d.get("car_part", "Other"),
                    severity=d.get("severity", "Moderate"),
                    description=d.get("description", ""),
                    confidence=d.get("confidence", 0.8),
                    repair_method=d.get("repair_method"),
                    estimated_cost_min=d.get("estimated_cost_min"),
                    estimated_cost_max=d.get("estimated_cost_max"),
                    labor_hours=d.get("labor_hours"),
                    parts_needed=d.get("parts_needed"),
                )
            )

        return AnalysisResponse(
            success=True,
            vehicle_make=vehicle.get("make"),
            vehicle_model=vehicle.get("model"),
            vehicle_year=vehicle.get("year"),
            vehicle_color=vehicle.get("color"),
            summary=assessment.get("summary"),
            total_estimated_cost_min=assessment.get("total_cost_min"),
            total_estimated_cost_max=assessment.get("total_cost_max"),
            is_driveable=assessment.get("is_driveable"),
            urgency_level=assessment.get("urgency_level"),
            damages=damages,
        )

    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse Claude response: {e}")
        return AnalysisResponse(success=False, error_message=f"Failed to parse AI response: {e}")
    except anthropic.APIError as e:
        logger.error(f"Claude API error: {e}")
        return AnalysisResponse(success=False, error_message=f"AI service error: {e}")
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        return AnalysisResponse(success=False, error_message=str(e))
