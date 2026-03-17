import base64
import json
import logging

import httpx
from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import ValidationError

from ..config import settings
from ..schemas import (
    AnalysisResponse,
    BoundingBox,
    DamageResult,
    ImageData,
    MultiImageRequest,
    RepairLineItem,
)

router = APIRouter()
logger = logging.getLogger(__name__)

# Valid enum values that match C# domain exactly
VALID_DAMAGE_TYPES = {
    "Scratch", "Dent", "Crack", "PaintDamage", "BrokenGlass",
    "Rust", "BodyDeformation", "BumperDamage", "LightDamage",
    "TireDamage", "MirrorDamage", "Other",
}

VALID_CAR_PARTS = {
    "FrontBumper", "RearBumper", "Hood", "Trunk",
    "FrontLeftDoor", "FrontRightDoor", "RearLeftDoor", "RearRightDoor",
    "FrontLeftFender", "FrontRightFender", "RearLeftFender", "RearRightFender",
    "Roof", "Windshield", "RearWindow",
    "SideWindowLeft", "SideWindowRight",
    "SideMirrorLeft", "SideMirrorRight",
    "HeadlightLeft", "HeadlightRight",
    "TaillightLeft", "TaillightRight",
    "WheelFrontLeft", "WheelFrontRight", "WheelRearLeft", "WheelRearRight",
    "Undercarriage", "Other",
}

VALID_SEVERITIES = {"Minor", "Moderate", "Severe", "Critical"}
VALID_SAFETY_RATINGS = {"Safe", "Warning", "Critical"}
VALID_REPAIR_CATEGORIES = {"Replace", "Repair", "Polish"}
VALID_LABOR_TYPES = {"Body", "Refinish", "Glass", "Mechanical"}

SYSTEM_PROMPT = """Ti si vrhunski forenzicki analiticar digitalnih medija s 20+ godina iskustva u detekciji krivotvorina, manipulacija i AI-generiranog sadrzaja.

=== TVOJ NAJVAZNIJI PRINCIP: PRECIZNA FORENZICKA ANALIZA ===
- Analiziraj sliku ili dokument za znakove digitalne manipulacije, AI generiranja ili krivotvorenja
- Trazi: nekonzistentnosti u osvjetljenju, sjene, perspektivi, teksturi, rubovima, kompresijskim artefaktima
- Trazi: znakove AI generiranja (ponavljajuci uzorci, neprirodne teksture, anomalije u detaljima poput prstiju/teksta/odsjaja)
- Trazi: znakove montaze (copy-paste regije, klonirane oblasti, neuskladjeni sumovi)
- Trazi: metadata anomalije (neobicni software, nedostajuci EXIF, sumnjivi kreativni alati)
- Ako slika izgleda autenticna, JASNO to navedi - ne izmisljaj probleme
- Bounding box MORA biti postavljen TOCNO na sumnjivo podrucje
- NE prijavljuj nalaze koje ne mozes JASNO argumentirati - nula lazno pozitivnih"""

ANALYSIS_PROMPT = """FORENZICKA ANALIZA AUTENTICNOSTI

=== KORAK 1: PRVA PROCJENA ===
Pogledaj sliku i utvrdi: je li ovo fotografija, screenshot, dokument, ili nesto drugo?
Ima li ocitih znakova AI generiranja ili manipulacije na prvi pogled?

=== KORAK 2: DETALJNA ANALIZA ===
Provjeri sljedece aspekte:
1. OSVJETLJENJE I SJENE - jesu li konzistentni? Ima li nemogucih izvora svjetla?
2. RUBOVI I PRIJELAZI - ima li neprirodnih rezova, zamagljenih rubova oko objekata?
3. TEKSTURE - ponavljaju li se uzorci? Jesu li teksture neprirodne za stvarni svijet?
4. DETALJI - prsti, tekst, odsjaji, refleksije - jesu li fizikalno moguce?
5. KOMPRESIJA - ima li neocekivanih artefakata koji sugeriraju visestruko spremanje?
6. PERSPEKTIVA - je li geometrija konzistentna u cijeloj slici?
7. SUMOVI - je li razina suma konzistentna preko cijele slike ili su vidljive granice?

=== KORAK 3: POZICIONIRAJ BOUNDING BOX ===
Za svako sumnjivo podrucje:
- x,y = gornji lijevi kut sumnjivog podrucja (0.0-1.0), w,h = sirina i visina
- Bounding box MORA obuhvatiti SAMO sumnjivo podrucje

=== KATEGORIJE NALAZA (za damage_cause polje) ===
- "AI generiranje" - znakovi AI-generiranog sadrzaja
- "Digitalna manipulacija" - rucna obrada u Photoshopu ili slicnom alatu
- "Copy-paste krivotvorina" - klonirane regije unutar slike
- "Rekompresijski artefakti" - sumnjivi JPEG artefakti
- "Nekonzistentno osvjetljenje" - razlike u osvjetljenju koje sugeriraju montazu
- "Metadata anomalija" - nekonzistentni metapodaci
- "Deepfake indikator" - znakovi deepfake manipulacije
- "Sumnjiva tekstura" - neprirodne teksture tipicne za AI
- "Perspektivna anomalija" - nekonzistentna perspektiva
- "Autenticno" - nalaz koji potvrduje autenticnost elementa

=== OBAVEZAN JSON FORMAT ===
Odgovori ISKLJUCIVO validnim JSON-om, bez objasnjenja ili markdowna:

{
  "vehicle_info": {
    "make": null,
    "model": null,
    "year": null,
    "color": null
  },
  "damages": [
    {
      "damage_type": "Other",
      "car_part": "Other",
      "severity": "ENUM: Minor|Moderate|Severe|Critical (Minor=niska sumnja, Moderate=umjerena, Severe=visoka, Critical=kriticna sumnja na krivotvorinu)",
      "description": "Detaljan opis nalaza na HRVATSKOM. 2-3 recenice. Objasni STO tocno vidis i ZASTO je sumnjivo.",
      "confidence": 0.92,
      "bounding_box": {"x": 0.3, "y": 0.4, "w": 0.15, "h": 0.1},
      "source_image_index": 0,
      "damage_cause": "Kategorija nalaza iz gornjeg popisa",
      "safety_rating": "ENUM: Safe|Warning|Critical (Safe=autenticno, Warning=sumnjivo, Critical=krivotvoreno)",
      "material_type": null,
      "repair_method": null,
      "repair_operations": null,
      "repair_category": null,
      "estimated_cost_min": null,
      "estimated_cost_max": null,
      "labor_hours": null,
      "parts_needed": null,
      "repair_line_items": []
    }
  ],
  "overall_assessment": {
    "summary": "Forenzicki izvjestaj na HRVATSKOM u 3-5 recenica. Ukratko opisi rezultat analize autenticnosti.",
    "structural_integrity": "Procjena integriteta slike/dokumenta na HRVATSKOM",
    "total_cost_min": null,
    "total_cost_max": null,
    "is_driveable": null,
    "urgency_level": "ENUM: Low|Medium|High|Critical (razina hitnosti pregleda)",
    "labor_total": null,
    "parts_total": null,
    "materials_total": null,
    "gross_total": null
  }
}

=== KRITICNA PRAVILA ===
1. damage_type UVIJEK stavi "Other" (koristimo damage_cause za kategoriju nalaza)
2. car_part UVIJEK stavi "Other" (nije relevantno za forenziku)
3. severity mapira razinu sumnje: Minor=niska, Moderate=umjerena, Severe=visoka, Critical=kriticna
4. safety_rating mapira verdikt: Safe=autenticno, Warning=sumnjivo, Critical=krivotvoreno
5. bounding_box koordinate MORAJU biti 0.0-1.0 i TOCNO na sumnjivom podrucju
6. source_image_index: 0 za prvu sliku, 1 za drugu, itd.
7. Svi opisi MORAJU biti na HRVATSKOM
8. NE prijavljuj nalaze koje ne mozes JASNO argumentirati - nula lazno pozitivnih
9. Ako slika izgleda potpuno autenticna, vrati PRAZAN damages array
10. UVIJEK vrati validan JSON
11. damage_cause MORA biti jedna od definiranih kategorija nalaza
12. Troskovi (estimated_cost_min/max, labor_total, itd.) UVIJEK null - nisu relevantni"""


def get_media_type(filename: str) -> str:
    ext = filename.lower().rsplit(".", 1)[-1] if "." in filename else ""
    return {
        "jpg": "image/jpeg",
        "jpeg": "image/jpeg",
        "png": "image/png",
        "webp": "image/webp",
        "gif": "image/gif",
    }.get(ext, "image/jpeg")


def sanitize_enum(value: str, valid_set: set, default: str = "Other") -> str:
    """Ensure the value exactly matches one of the valid enum values."""
    if value in valid_set:
        return value
    for v in valid_set:
        if v.lower() == value.lower().replace(" ", "").replace("_", "").replace("-", "").replace("/", ""):
            return v
    return default


def parse_bounding_box(raw: dict | None) -> BoundingBox | None:
    """Parse and validate bounding box coordinates."""
    if not raw or not isinstance(raw, dict):
        return None
    try:
        x = float(raw.get("x", 0))
        y = float(raw.get("y", 0))
        w = float(raw.get("w", 0))
        h = float(raw.get("h", 0))
        image_index = int(raw.get("image_index", 0))
        x = max(0.0, min(1.0, x))
        y = max(0.0, min(1.0, y))
        w = max(0.01, min(1.0 - x, w))
        h = max(0.01, min(1.0 - y, h))
        return BoundingBox(x=x, y=y, w=w, h=h, image_index=image_index)
    except (ValueError, TypeError):
        return None


def parse_repair_line_items(raw_items: list | None) -> list[RepairLineItem]:
    """Parse repair line items from AI response."""
    if not raw_items or not isinstance(raw_items, list):
        return []
    items = []
    for item in raw_items:
        if not isinstance(item, dict):
            continue
        try:
            items.append(RepairLineItem(
                line_number=int(item.get("line_number", len(items) + 1)),
                part_name=str(item.get("part_name", "")),
                operation=str(item.get("operation", "Repair")),
                labor_type=sanitize_enum(
                    str(item.get("labor_type", "Body")), VALID_LABOR_TYPES, "Body"
                ),
                labor_hours=float(item.get("labor_hours", 0)),
                part_type=str(item.get("part_type", "Existing")),
                quantity=int(item.get("quantity", 1)),
                unit_cost=float(item["unit_cost"]) if item.get("unit_cost") is not None else None,
                total_cost=float(item["total_cost"]) if item.get("total_cost") is not None else None,
            ))
        except (ValueError, TypeError, KeyError):
            continue
    return items


def _extract_json(response_text: str) -> dict:
    """Extract JSON from response, handling markdown code blocks."""
    text = response_text.strip()
    if "```json" in text:
        text = text.split("```json")[1].split("```")[0].strip()
    elif "```" in text:
        text = text.split("```")[1].split("```")[0].strip()
    return json.loads(text)


def _parse_response(data: dict) -> AnalysisResponse:
    """Parse the AI JSON response into an AnalysisResponse."""
    vehicle = data.get("vehicle_info", {})
    assessment = data.get("overall_assessment", {})
    damages_raw = data.get("damages", [])

    damages = []
    for d in damages_raw:
        # Extract source_image_index and inject into bounding_box data
        source_idx = int(d.get("source_image_index", 0))
        bb_raw = d.get("bounding_box")
        if bb_raw and isinstance(bb_raw, dict):
            bb_raw["image_index"] = source_idx

        damages.append(
            DamageResult(
                damage_type=sanitize_enum(d.get("damage_type", "Other"), VALID_DAMAGE_TYPES),
                car_part=sanitize_enum(d.get("car_part", "Other"), VALID_CAR_PARTS),
                severity=sanitize_enum(d.get("severity", "Moderate"), VALID_SEVERITIES, "Moderate"),
                description=d.get("description", ""),
                confidence=d.get("confidence", 0.8),
                repair_method=d.get("repair_method"),
                estimated_cost_min=d.get("estimated_cost_min"),
                estimated_cost_max=d.get("estimated_cost_max"),
                labor_hours=d.get("labor_hours"),
                parts_needed=d.get("parts_needed"),
                bounding_box=parse_bounding_box(bb_raw),
                damage_cause=d.get("damage_cause"),
                safety_rating=sanitize_enum(
                    d.get("safety_rating", "Safe"), VALID_SAFETY_RATINGS, "Safe"
                ) if d.get("safety_rating") else None,
                material_type=d.get("material_type"),
                repair_operations=d.get("repair_operations"),
                repair_category=sanitize_enum(
                    d.get("repair_category", "Repair"), VALID_REPAIR_CATEGORIES, "Repair"
                ) if d.get("repair_category") else None,
                repair_line_items=parse_repair_line_items(d.get("repair_line_items")),
            )
        )

    return AnalysisResponse(
        success=True,
        vehicle_make=vehicle.get("make"),
        vehicle_model=vehicle.get("model"),
        vehicle_year=vehicle.get("year"),
        vehicle_color=vehicle.get("color"),
        summary=assessment.get("summary"),
        structural_integrity=assessment.get("structural_integrity"),
        total_estimated_cost_min=assessment.get("total_cost_min"),
        total_estimated_cost_max=assessment.get("total_cost_max"),
        is_driveable=assessment.get("is_driveable"),
        urgency_level=assessment.get("urgency_level"),
        damages=damages,
        labor_total=assessment.get("labor_total"),
        parts_total=assessment.get("parts_total"),
        materials_total=assessment.get("materials_total"),
        gross_total=assessment.get("gross_total"),
    )


async def _call_openrouter(
    image_contents: list[tuple[str, str]],  # list of (base64_data, media_type)
    vehicle_context: str = "",
) -> AnalysisResponse:
    """Call OpenRouter API with one or more images."""
    if not settings.openrouter_api_key:
        raise HTTPException(status_code=500, detail="OpenRouter API key not configured")

    system_content = SYSTEM_PROMPT

    # Build user content: label each image with its index, then analysis prompt
    user_content = []
    for idx, (b64_data, media_type) in enumerate(image_contents):
        if len(image_contents) > 1:
            user_content.append({
                "type": "text",
                "text": f"[SLIKA {idx} - source_image_index={idx}]",
            })
        user_content.append({
            "type": "image_url",
            "image_url": {"url": f"data:{media_type};base64,{b64_data}"},
        })

    multi_image_note = ""
    if len(image_contents) > 1:
        multi_image_note = f"""

VISE SLIKA: Poslano je {len(image_contents)} slika, oznacenih [SLIKA 0] do [SLIKA {len(image_contents) - 1}].
- Analiziraj SVAKU sliku zasebno za znakove manipulacije
- source_image_index MORA biti index slike na kojoj je nalaz NAJVIDLJIVIJI
- Bounding box koordinate se odnose na sliku navedenu u source_image_index
- Ako se isti nalaz vidi na vise slika, prijavi ga JEDNOM s onom slikom gdje je najjasniji
- NIKAD ne stavljaj bounding box za nalaz vidljiv na slici 1 koristeci koordinate slike 0"""

    user_content.append({"type": "text", "text": ANALYSIS_PROMPT + multi_image_note})

    try:
        async with httpx.AsyncClient(timeout=300.0) as client:
            response = await client.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {settings.openrouter_api_key}",
                    "Content-Type": "application/json",
                    "HTTP-Referer": "https://dent.xyler.ai",
                    "X-Title": "DENT - Fraud Detection & Forensic Analysis",
                },
                json={
                    "model": settings.model,
                    "max_tokens": 16000,
                    "temperature": 0.1,
                    "messages": [
                        {"role": "system", "content": system_content},
                        {"role": "user", "content": user_content},
                    ],
                },
            )

        response.raise_for_status()
        result = response.json()
        response_text = result["choices"][0]["message"]["content"]
        data = _extract_json(response_text)
        return _parse_response(data)

    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse AI response: {e}")
        logger.error(f"Raw response: {response_text[:500]}")
        return AnalysisResponse(success=False, error_message=f"Failed to parse AI response: {e}")
    except httpx.HTTPStatusError as e:
        logger.error(f"OpenRouter API error: {e.response.status_code} - {e.response.text}")
        return AnalysisResponse(success=False, error_message=f"AI service error: {e.response.status_code}")
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        return AnalysisResponse(success=False, error_message=str(e))


@router.post("/analyze", response_model=AnalysisResponse)
async def analyze_image(file: UploadFile = File(...)):
    """Single-image analysis endpoint (backward compatible)."""
    contents = await file.read()
    size_mb = len(contents) / (1024 * 1024)

    if size_mb > settings.max_image_size_mb:
        raise HTTPException(
            status_code=413,
            detail=f"Image too large: {size_mb:.1f}MB (max {settings.max_image_size_mb}MB)",
        )

    image_b64 = base64.b64encode(contents).decode("utf-8")
    media_type = get_media_type(file.filename or "image.jpg")

    return await _call_openrouter([(image_b64, media_type)])


@router.post("/analyze-multi", response_model=AnalysisResponse)
async def analyze_multi_images(request: MultiImageRequest):
    """Multi-image analysis endpoint with vehicle context."""
    if not request.images:
        raise HTTPException(status_code=400, detail="No images provided")
    if len(request.images) > 8:
        raise HTTPException(status_code=400, detail="Maximum 8 images allowed")

    # Build vehicle context string
    vehicle_context = ""
    if request.vehicle_make:
        vehicle_context = f"{request.vehicle_make}"
        if request.vehicle_model:
            vehicle_context += f" {request.vehicle_model}"
        if request.vehicle_year:
            vehicle_context += f" ({request.vehicle_year})"
        if request.mileage:
            vehicle_context += f", kilometraza: {request.mileage} km"

    image_contents = [(img.data, img.media_type) for img in request.images]

    return await _call_openrouter(image_contents, vehicle_context)
