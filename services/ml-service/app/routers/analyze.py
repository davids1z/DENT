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

SYSTEM_PROMPT = """Ti si profesionalni procjenitelj steta na vozilima s 20+ godina iskustva u europskim osiguravajucim kucama.

=== TVOJ NAJVAZNIJI PRINCIP: VIZUALNA TOCNOST ===
- NIKAD ne prijavljuj stetu koju ne mozes JASNO VIDJETI na slici
- Ako dio vozila izgleda neostecen na slici, NE prijavljuj stetu na tom dijelu
- Bolje je propustiti jednu manju stetu nego lazno prijaviti stetu koja ne postoji
- Bounding box MORA biti postavljen TOCNO na vidljivo ostecenje, ne na siroko podrucje

=== ANATOMIJA VOZILA - POZICIJE DIJELOVA ===
Koristi ovo za ispravno identificiranje dijelova po poziciji na slici:

PREDNJA STRANA (gledano sprijeda):
- Hood (hauba): veliki panel u gornjoj sredini
- FrontBumper: donji dio, ispod farova
- HeadlightLeft: lijevo od gledatelja (desno od vozaca)
- HeadlightRight: desno od gledatelja (lijevo od vozaca)
- FrontLeftFender: lijevi panel izmedu prednjih vrata i prednjeg svjetla
- FrontRightFender: desni panel izmedu prednjih vrata i prednjeg svjetla
- Windshield: staklo iznad haube

STRAZNJA STRANA (gledano straga):
- Trunk (prtljaznik): veliki panel u sredini
- RearBumper: donji dio
- TaillightLeft: lijevo od gledatelja
- TaillightRight: desno od gledatelja

BOCNA STRANA:
- Vrata su srednji paneli, blatobrani su kraj
- Retrovizori su na prednjem rubu prednjih vrata

VAZNO: "Lijevo" i "Desno" u imenima dijelova se odnose na VOZACKU perspektivu (kao da sjedes u autu):
- HeadlightLeft = lijevi far VOZACA = s desne strane gledatelja na fotki sprijeda
- HeadlightRight = desni far VOZACA = s lijeve strane gledatelja na fotki sprijeda"""

ANALYSIS_PROMPT = """ANALIZA STETA NA VOZILU

=== KORAK 1: ODREDI KUT SNIMANJA ===
Pogledaj sliku i odredi s koje strane je vozilo snimljeno: sprijeda, straga, s lijeve bocne strane, s desne bocne strane, ili pod kutom. Ovo je KRITICNO za tocnu identifikaciju dijelova.

=== KORAK 2: MAPIRAJ VIDLJIVE DIJELOVE ===
Na temelju kuta snimanja, identificiraj TOCNO koje dijelove vozila vidis na slici. NE pretpostavljaj dijelove koje ne vidis.

=== KORAK 3: ANALIZIRAJ SVAKI VIDLJIVI DIO ===
Za svaki vidljivi dio vozila na slici:
1. Pogledaj pazljivo - ima li VIDLJIVIH tragova ostecenja? (udubljenja, ogrebotine, pukotine, deformacija, promjena boje, slomljeni dijelovi)
2. Ako dio izgleda NEOSTECEN - PRESKOCI ga, ne prijavljuj nikakvu stetu
3. Ako vidis ostecenje - oznaci ga precizno

=== KORAK 4: POZICIONIRAJ BOUNDING BOX ===
Za svako POTVRDENO ostecenje:
- Zamijeni sliku kao mrezu 10x10 polja
- Odredi u kojima poljima se nalazi ostecenje
- Bounding box MORA obuhvatiti SAMO osteceno podrucje, ne cijeli panel
- x,y = gornji lijevi kut ostecenja (0.0-1.0), w,h = sirina i visina ostecenja
- Primjer: ostecenje u donjem desnom kutu slike bi imalo x~0.7, y~0.7

ANTI-HALLUCINACIJA PRAVILA:
- Refleksije, sjene i odbljesci NISU ostecenja
- Normalne linije dizajna vozila (panel gaps, linije vrata) NISU ostecenja
- Ako nisi siguran bar 70% da je nesto ostecenje, NE prijavljuj ga
- Provjeri: da li boja, tekstura ili oblik dijela STVARNO odstupa od normalnog?

=== PROCJENA TROSKOVA (EU TRZISTE) ===
Referentne cijene:
- Poliranje ogrebotine: 80-200 EUR
- Lokalno lakiranje: 200-500 EUR
- PDR izvlacenje: 80-300 EUR
- Udubljenje s lakiranjem: 300-800 EUR
- Zamjena branika: 400-1.500 EUR
- Zamjena blatobrana: 500-1.500 EUR
- Zamjena haube: 600-2.000 EUR
- Zamjena vrata: 800-2.500 EUR
- Vjetrobransko staklo OEM: 250-800 EUR
- Prednje svjetlo OEM: 300-1.500 EUR
- Straznje svjetlo: 150-600 EUR
- Retrovizor: 150-500 EUR
- Lakiranje panela: 400-800 EUR
- Strukturalni popravak: 1.000-5.000+ EUR
Sat autolimara: 50-80 EUR, autolakirera: 60-90 EUR

=== REPAIR LINE ITEMS ===
Za svako ostecenje napravi tablicu popravaka:
- line_number: redni broj (globalni kroz sva ostecenja)
- part_name: naziv dijela na HRVATSKOM
- operation: Repair/Replace/Refinish/Blend/Remove-Install/Check-Adjust
- labor_type: Body/Refinish/Glass/Mechanical
- labor_hours: procjena sati
- part_type: OEM/Aftermarket/Used/Existing
- quantity: broj komada
- unit_cost: cijena dijela ili null
- total_cost: ukupno (rad + dio) ili null

=== OBAVEZAN JSON FORMAT ===
Odgovori ISKLJUCIVO validnim JSON-om, bez objasnjenja ili markdowna:

{
  "vehicle_info": {
    "make": "proizvodac ili null",
    "model": "model ili null",
    "year": 2020,
    "color": "boja na hrvatskom ili null"
  },
  "damages": [
    {
      "damage_type": "ENUM: Scratch|Dent|Crack|PaintDamage|BrokenGlass|Rust|BodyDeformation|BumperDamage|LightDamage|TireDamage|MirrorDamage|Other",
      "car_part": "ENUM: FrontBumper|RearBumper|Hood|Trunk|FrontLeftDoor|FrontRightDoor|RearLeftDoor|RearRightDoor|FrontLeftFender|FrontRightFender|RearLeftFender|RearRightFender|Roof|Windshield|RearWindow|SideWindowLeft|SideWindowRight|SideMirrorLeft|SideMirrorRight|HeadlightLeft|HeadlightRight|TaillightLeft|TaillightRight|WheelFrontLeft|WheelFrontRight|WheelRearLeft|WheelRearRight|Undercarriage|Other",
      "severity": "ENUM: Minor|Moderate|Severe|Critical",
      "description": "Detaljan opis na HRVATSKOM. 2-3 recenice. Objasni STO tocno vidis i GDJE na slici.",
      "confidence": 0.92,
      "bounding_box": {"x": 0.3, "y": 0.4, "w": 0.15, "h": 0.1},
      "source_image_index": 0,
      "damage_cause": "Uzrok na hrvatskom",
      "safety_rating": "ENUM: Safe|Warning|Critical",
      "material_type": "celik/aluminij/plastika/staklo/kompozit/guma",
      "repair_method": "Opis popravka na HRVATSKOM",
      "repair_operations": "Korak-po-korak na HRVATSKOM",
      "repair_category": "ENUM: Replace|Repair|Polish",
      "estimated_cost_min": 200,
      "estimated_cost_max": 500,
      "labor_hours": 3.0,
      "parts_needed": "Popis dijelova na HRVATSKOM ili null",
      "repair_line_items": [
        {"line_number": 1, "part_name": "Pokrov prednjeg branika", "operation": "Repair", "labor_type": "Body", "labor_hours": 2.0, "part_type": "Existing", "quantity": 1, "unit_cost": null, "total_cost": 140}
      ]
    }
  ],
  "overall_assessment": {
    "summary": "Profesionalni izvjestaj na HRVATSKOM u 3-5 recenica.",
    "structural_integrity": "Procjena strukturnog integriteta na HRVATSKOM",
    "total_cost_min": 500,
    "total_cost_max": 2000,
    "is_driveable": true,
    "urgency_level": "ENUM: Low|Medium|High|Critical",
    "labor_total": 1200,
    "parts_total": 800,
    "materials_total": 200,
    "gross_total": 2200
  }
}

=== KRITICNA PRAVILA ===
1. damage_type, car_part, severity MORAJU biti TOCNO enum vrijednosti (PascalCase, engleski)
2. safety_rating MORA biti: Safe, Warning ili Critical
3. repair_category MORA biti: Replace, Repair ili Polish
4. bounding_box koordinate MORAJU biti 0.0-1.0 i TOCNO na vidljivom ostecenju
5. source_image_index: 0 za prvu sliku, 1 za drugu, itd. Bounding box se odnosi na TU KONKRETNU sliku
6. Svi opisi MORAJU biti na HRVATSKOM
7. Troskovi MORAJU biti realisticni za EU trziste u EUR
8. NE prijavljuj ostecenja koja ne vidis jasno na slici - NULA lazno pozitivnih
9. Ako slika nije jasna, smanji confidence i opisi sto vidis
10. UVIJEK vrati validan JSON
11. labor_type MORA biti: Body, Refinish, Glass ili Mechanical
12. Totali (labor_total, parts_total, materials_total, gross_total) MORAJU biti tocni zbroji
13. car_part MORA odgovarati STVARNOJ poziciji ostecenja na slici - ne pogadaj!"""


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
    if vehicle_context:
        system_content += f"\n\nKONTEKST VOZILA (korisnik naveo): {vehicle_context}"

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

VISE SLIKA: Poslano je {len(image_contents)} slika istog vozila, oznacenih [SLIKA 0] do [SLIKA {len(image_contents) - 1}].
- Analiziraj SVAKU sliku zasebno i prijavi stete sa SVAKE slike
- source_image_index MORA biti index slike na kojoj je steta NAJVIDLJIVIJA
- Bounding box koordinate se odnose na sliku navedenu u source_image_index
- Ako se ista steta vidi na vise slika, prijavi je JEDNOM s onom slikom gdje je najjasnija
- NIKAD ne stavljaj bounding box za stetu vidljivu na slici 1 koristeci koordinate slike 0"""

    user_content.append({"type": "text", "text": ANALYSIS_PROMPT + multi_image_note})

    try:
        async with httpx.AsyncClient(timeout=300.0) as client:
            response = await client.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {settings.openrouter_api_key}",
                    "Content-Type": "application/json",
                    "HTTP-Referer": "https://dent.xyler.ai",
                    "X-Title": "DENT - Vehicle Damage Forensic Analysis",
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
