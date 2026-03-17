import base64
import json
import logging

import httpx
from fastapi import APIRouter, File, Form, HTTPException, UploadFile
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

SYSTEM_PROMPT = """Ti si DENT — profesionalni forenzicki sustav za detekciju krivotvorina, manipulacija i AI-generiranog sadrzaja. Imas 20+ godina iskustva u digitalnoj forenzici i ruzni istraziteljski instinkt.

=== TVOJA MISIJA ===
Za svaku sliku ili dokument MORAS provesti KOMPLETNU forenzicku analizu i dati DETALJAN izvjestaj.
NIKADA ne smijes vratiti prazan izvjestaj. Uvijek analiziraj barem 4-8 razlicitih aspekata slike.

=== KLJUCNA PRAVILA DETEKCIJE ===

1. AI-GENERIRANE SLIKE (Midjourney, DALL-E, Stable Diffusion, Flux, Firefly):
   - Preglad tekstura: AI slike cesto imaju "plastican" ili "uljast" izgled na povrsinima
   - Refleksije i odsjaji: neprirodne refleksije na staklu, metalu, vlaznim povrsinama
   - Tekst i natpisi: deformirani, besmisleni ili neshvatljivi natpisi, registarske oznake
   - Prsti i ekstremiteti: nepravilan broj prstiju, fuzija prstiju, cudni zglobovi
   - Ponavljajuci uzorci: AI generira repetirajuce mikro-uzorke u pozadinama i teksturama
   - Dubina polja: nekonzistentna - neki objekti na istoj udaljenosti razlicito ostriStaklo i lomovi: AI ne zna simulirati fiziku loma stakla - shard uzorci su uvijek netocni
   - Sjene: AI cesto stavlja sjene u krivom smjeru ili ih potpuno izostavlja
   - Rubovi objekata: "mekani" rubovi umjesto ostrih linija, posebno oko kose/dlaka/listova
   - Pozadina: neodredjeni detalji, "dreamlike" kvaliteta u pozadini
   - Fizika: nemoguce fizicke konfiguracije (npr. tekucina koja se ne ponasa po gravitaciji)
   - Simetricnost: AI slike cesto imaju pretjeranu ili neprirodnu simetriju

2. DIGITALNA MANIPULACIJA (Photoshop, GIMP, itd.):
   - Granice obrade: vidljive granice izmedju obradjenih i neobradjenih dijelova
   - Klonirani pikseli: ponovljene regije (copy-paste) unutar iste slike
   - Nekonzistentna kompresija: razliciti JPEG blokovi u razlicitim dijelovima slike
   - Nekonzistentno osvjetljenje: razliciti izvori svjetla za razlicite objekte
   - Nekonzistentna razina suma: neki dijelovi slike imaju vise suma od drugih
   - Neprirodni prijelazi boja: nagla promjena boje bez fizikalnog razloga
   - Perspektivne greske: objekti u istoj sceni slijede razlicite tocke nestajanja

3. DOKUMENTI I PDF-ovi:
   - Font analiza: razliciti fontovi/velicine koji ne pripadaju istom dokumentu
   - Poravnanje: nekonzistentan razmak, poravnanje teksta
   - Pecat/potpis: znakovi digitalnog umjesto rucnog potpisa
   - Rezolucija: razlicite rezolucije razlicitih elemenata na istoj stranici

=== KAKO ANALIZIRATI ===
Za SVAKU sliku MORAS provjeriti I IZVJESTITI o SVIM sljedecim aspektima:

1. ANALIZA TEKSTURA I POVRSINA - ispitaj sve glavne povrsine u slici. Jesu li teksture realisticne?
2. ANALIZA OSVJETLJENJA - mapiraraj sve izvore svjetla i provjeri konzistentnost sjena
3. ANALIZA RUBOVA I OBJEKATA - provjeri rubove svih glavnih objekata za znakove obrade
4. ANALIZA DETALJA - provjeri sitne detalje: tekst, registracije, refleksije, staklo, prsti
5. ANALIZA PERSPEKTIVE I GEOMETRIJE - provjeri konzistentnost perspektive i geometrije scene
6. ANALIZA SUMA I KOMPRESIJE - provjeri uniformnost razine suma i kompresijskih artefakata
7. ANALIZA FIZICKE PLAUZIBILNOSTI - je li scena fizicki moguca? Gravitacija, mehanika, optika
8. KONACNI VERDIKT - sintetiziraj sve nalaze u konacnu procjenu

VAZNO: Cak i ako slika izgleda autenticna, MORAS analizirati svaki aspekt i objasniti ZASTO smatras da je autentican. Za autenticne nalaze koristi severity "Minor" i damage_cause "Autenticno"."""

# ──────────────────────────────────────────────────────────────────────
# Context-aware prompts: Gemini receives forensic module results and
# SYNTHESIZES/EXPLAINS them rather than independently detecting.
# ──────────────────────────────────────────────────────────────────────

CONTEXT_SYSTEM_PROMPT = """Ti si DENT — profesionalni forenzicki sustav za detekciju krivotvorina, manipulacija i AI-generiranog sadrzaja.

=== TVOJA ULOGA ===
Dobivas DVA izvora informacija:
1. SLIKU za vizualnu analizu
2. REZULTATE FORENZICKIH MODULA — statisticki i ML moduli koji su vec analizirali sliku

Tvoj zadatak je SINTETIZIRATI oba izvora u koherentan, detaljan forenzicki izvjestaj.

=== KRITICNO PRAVILO ===
Forenzicki moduli (CNN detekcija, statisticka analiza, ELA, metadata) su POUZDANIJI od tvoje vizualne procjene.
Ako forenzicki moduli pokazuju VISOK ili KRITICAN rizik — MORAS to odraziti u svojim nalazima.
NE SMIJES proglasiti sliku autenticnom ako forenzicki moduli ukazuju na manipulaciju ili AI generiranje.

Konkretno:

=== PRIORITET 1: AI DETEKCIJA (neuronske mreze) ===
- Ako ai_generation_detection >= 0.60: Swin Transformer mreze obucene na 500k+ parova
  real/fake slika detektirale su statisticke obrasce tipicne za AI generatore.
  Ovo je NAJJACI pojedinacni signal. Severity MORA biti Severe ili Critical.

=== PRIORITET 2: SPEKTRALNA FORENZIKA (frekvencijska domena) ===
- Ako spectral_forensics >= 0.50: Frekvencijsko-fazna analiza otkriva:
  * Nisku faznu koherenciju izmedju R/G/B kanala (difuzijski modeli generiraju kanale neovisno)
  * Deficit visokih frekvencija (AI ne reproducira fine detalje pravilno)
  * Plosnati spektar (Wiener entropija visa od prirodnih fotografija)
  * Anomalije u blok-baziranoj frekvencijskoj mapi
  Ovi artefakti su NEVIDLJIVI ljudskom oku ali NEDVOJBENI u frekvencijskoj domeni.
  Severity Moderate/Severe. Koristi damage_cause "Spektralna anomalija".

=== PRIORITET 3: CROSS-VALIDATION (dva nezavisna pristupa) ===
- Ako OBOJE ai_generation_detection >= 0.50 I spectral_forensics >= 0.40:
  Dva NEZAVISNA pristupa (neuronska mreza + frekvencijska analiza) potvrdjuju
  AI generiranje. Ovo je gotovo siguran dokaz. Severity MORA biti Critical.
- Ako spectral_forensics >= 0.40 ALI ai_generation_detection < 0.40:
  Frekvencijske anomalije postoje ali neuronska mreza nije sigurna.
  Moguce noviji/nepoznati AI generator. Prijavi kao Moderate s damage_cause
  "Spektralna anomalija", navedi specificne anomalije kao dokaz.

=== PRIORITET 4: C2PA KRIPTOGRAFSKI PECAT ===
- Ako C2PA manifest (META_C2PA_AI_GENERATED) detektiran u metadata modulu:
  Slika SAMA SEBE deklarira kao AI-generiranu putem kriptografski potpisanog
  C2PA manifesta. Ovo je nepobitni dokaz. Severity Critical.

=== PRIORITET 5: IZVOR SLIKE (captureSource) ===
- Ako je captureSource == "camera": Slika je slikana uzivo kamerom uredaja.
  Ovo povecava povjerenje u autenticnost — prevarant bi morao slikati ekran
  da bi iskoristio AI sliku, sto ostavlja Moire uzorke (FFT detekcija).
- Ako je captureSource == "upload": Slika je uploadana, NE slikana kamerom.
  Ovo je SUMNJIVO jer sustav zahtijeva live capture. Moguce je da je slika
  unaprijed pripremljena. Prijavi kao Moderate s damage_cause "Metadata anomalija".

=== OSTALI MODULI ===
- Ako je CNN modul (deep_modification_detection) detektirao manipulaciju → OBAVEZNO prijavi kao Severe/Critical
- Ako semanticka analiza (SEM_AI_GENERATED_*) ukazuje na AI → OBAVEZNO prijavi kao Severe/Critical
- Ako ELA analiza pokazuje sumnjive regije → prijavi kao Moderate/Severe
- Ako metadata imaju anomalije → prijavi kao Moderate/Severe
- JEDINO ako SVI forenzicki moduli imaju NIZAK rizik, smijes koristiti severity Minor/Safe

=== STO RADIS ===
1. Procitaj forenzicke rezultate — razumi STO su moduli detektirali
2. Vizualno pregledaj sliku — trazi VIZUALNE POTVRDE forenzickih nalaza
3. Za svaki forenzicki nalaz, objasni ZASTO je sumnjivo na RAZUMLJIV nacin
4. Ako forenzicki moduli kazu HIGH/CRITICAL rizik, tvoji nalazi MORAJU biti Severe/Critical
5. Dodaj vlastite vizualne nalaze koje forenzicki moduli mozda nisu pokrili"""

ANALYSIS_PROMPT = """PROVEDI KOMPLETNU FORENZICKU ANALIZU.

MORAS vratiti MINIMALNO 4 nalaza, a idealno 5-8 nalaza. Svaki nalaz pokriva drugo podrucje slike.
Cak i za autenticne slike, analiziraj i izvjesti o svakom aspektu.

Za svaki nalaz:
- damage_cause: kategorija nalaza (vidi popis dolje)
- severity: Minor (niska sumnja) | Moderate (umjerena) | Severe (visoka) | Critical (kriticna)
- safety_rating: Safe (autenticno) | Warning (sumnjivo) | Critical (krivotvoreno)
- description: DETALJAN opis na HRVATSKOM, 2-4 recenice. Navedi TOCNO sto vidis i zasto je ili nije sumnjivo.
- bounding_box: PRECIZNE koordinate sumnjivog podrucja (0.0-1.0)
- confidence: tvoja pouzdanost u nalaz (0.0-1.0)

=== KATEGORIJE NALAZA (damage_cause) ===
- "AI generiranje" - znakovi da je sadrzaj generiran umjetnom inteligencijom
- "Digitalna manipulacija" - znakovi rucne obrade (Photoshop, GIMP, slicno)
- "Copy-paste krivotvorina" - klonirane/kopirane regije unutar slike
- "Rekompresijski artefakti" - sumnjivi kompresijski artefakti koji ukazuju na obradu
- "Nekonzistentno osvjetljenje" - razlike u osvjetljenju izmedju dijelova scene
- "Metadata anomalija" - nekonzistentnosti u metapodacima
- "Deepfake indikator" - znakovi deepfake generiranja ili zamjene lica
- "Sumnjiva tekstura" - neprirodne teksture tipicne za AI ili obradu
- "Perspektivna anomalija" - nekonzistentna perspektiva ili geometrija
- "Spektralna anomalija" - frekvencijsko-fazne anomalije u DCT/FFT domeni tipicne za AI generiranje
- "Autenticno" - aspekt koji potvrduje autenticnost (koristi za autenticne elemente)

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
      "severity": "Minor|Moderate|Severe|Critical",
      "description": "DETALJAN opis nalaza na HRVATSKOM. 2-4 recenice. Navedi STO vidis, GDJE tocno, i ZASTO je sumnjivo ili autenticno.",
      "confidence": 0.85,
      "bounding_box": {"x": 0.1, "y": 0.2, "w": 0.3, "h": 0.25},
      "source_image_index": 0,
      "damage_cause": "Kategorija iz popisa",
      "safety_rating": "Safe|Warning|Critical",
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
    "summary": "DETALJAN forenzicki izvjestaj na HRVATSKOM u 5-8 recenica. Opisi kompletnu analizu: sto si provjerio, sto si nasao, i konacni verdikt o autenticnosti. Budi specifican - navedi tocne regije i razloge.",
    "structural_integrity": "Procjena digitalnog integriteta slike - jesu li pikseli konzistentni, ima li znakova obrade, kakva je kvaliteta kompresije. 2-3 recenice na HRVATSKOM.",
    "total_cost_min": null,
    "total_cost_max": null,
    "is_driveable": null,
    "urgency_level": "Low|Medium|High|Critical",
    "labor_total": null,
    "parts_total": null,
    "materials_total": null,
    "gross_total": null
  }
}

=== KRITICNA PRAVILA ===
1. UVIJEK vrati MINIMALNO 4 nalaza. Nikad prazan damages array.
2. damage_type UVIJEK "Other", car_part UVIJEK "Other"
3. severity: Minor=niska sumnja, Moderate=umjerena, Severe=visoka, Critical=kriticna
4. safety_rating: Safe=element izgleda autenticno, Warning=sumnjivo, Critical=sigurno krivotvoreno/AI
5. bounding_box koordinate 0.0-1.0, PRECIZNO na analiziranom podrucju
6. source_image_index: 0 za prvu sliku, 1 za drugu, itd.
7. Svi opisi na HRVATSKOM jeziku
8. Za autenticne aspekte koristi damage_cause "Autenticno" sa severity "Minor" i safety_rating "Safe"
9. UVIJEK vrati validan JSON
10. Troskovi (estimated_cost_min/max, labor_total, itd.) UVIJEK null
11. overall_assessment.summary MORA biti detaljan (5-8 recenica)
12. Ako detektiras AI generiranje, budi AGRESIVAN - stavi severity "Severe" ili "Critical" i jasno objasni ZASTO"""


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


def _enforce_forensic_severity(
    response: AnalysisResponse,
    forensic_data: dict,
) -> AnalysisResponse:
    """
    Deterministic post-processing: override Gemini's severity ratings
    to match forensic fusion scores.  Gemini DESCRIBES findings,
    but fusion scores DETERMINE severity.
    """
    risk = forensic_data.get("overall_risk_score", 0)

    FRAUD_CAUSES = {
        "AI generiranje",
        "Digitalna manipulacija",
        "Copy-paste krivotvorina",
        "Rekompresijski artefakti",
        "Deepfake indikator",
        "Sumnjiva tekstura",
        "Spektralna anomalija",
        "Statisticka anomalija",
    }

    for d in response.damages:
        is_fraud = d.damage_cause in FRAUD_CAUSES

        if risk >= 0.75:  # CRITICAL fusion
            if is_fraud:
                d.severity = "Critical"
                d.safety_rating = "Critical"
            elif d.damage_cause != "Autenticno":
                if d.severity in ("Minor", "Moderate"):
                    d.severity = "Severe"
                if d.safety_rating == "Safe":
                    d.safety_rating = "Warning"

        elif risk >= 0.50:  # HIGH fusion
            if is_fraud:
                if d.severity in ("Minor", "Moderate"):
                    d.severity = "Severe"
                if d.safety_rating == "Safe":
                    d.safety_rating = "Critical"

        elif risk >= 0.25:  # MEDIUM fusion
            if is_fraud:
                if d.severity == "Minor":
                    d.severity = "Moderate"
                if d.safety_rating == "Safe":
                    d.safety_rating = "Warning"

    # Forbid "Autenticno" findings when fusion >= HIGH
    if risk >= 0.50:
        for d in response.damages:
            if d.damage_cause == "Autenticno":
                d.damage_cause = "Metadata anomalija"
                d.severity = "Moderate" if risk < 0.75 else "Severe"
                d.safety_rating = "Warning"
                d.description += (
                    " [Forenzicki moduli ukazuju na visok rizik manipulacije.]"
                )

    # Enforce urgency_level consistency
    if risk >= 0.75:
        response.urgency_level = "Critical"
    elif risk >= 0.50:
        response.urgency_level = "High"
    elif risk >= 0.25 and response.urgency_level == "Low":
        response.urgency_level = "Medium"

    return response


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


def _format_forensic_context(forensic_data: dict) -> str:
    """Format forensic module results into a text prompt for Gemini."""
    lines = []
    overall_risk = forensic_data.get("overall_risk_score", 0)
    overall_level = forensic_data.get("overall_risk_level", "Low")
    lines.append(f"=== FORENZICKI REZULTATI (statisticki/ML moduli) ===")
    lines.append(f"UKUPNI RIZIK: {overall_risk:.2f} ({overall_level})")
    lines.append("")

    modules = forensic_data.get("modules", [])
    for i, m in enumerate(modules, 1):
        name = m.get("module_label") or m.get("module_name", "Nepoznat modul")
        score = m.get("risk_score", 0)
        level = m.get("risk_level", "Low")
        lines.append(f"{i}. {name} ({m.get('module_name', '?')}): rizik {score:.2f} ({level})")

        findings = m.get("findings", [])
        for f in findings:
            code = f.get("code", "?")
            title = f.get("title", "?")
            desc = f.get("description", "")
            f_risk = f.get("risk_score", 0)
            f_conf = f.get("confidence", 0)
            lines.append(f"   - [{code}] {title}: {desc} (rizik: {f_risk:.2f}, pouzdanost: {f_conf:.0%})")

        error = m.get("error")
        if error:
            lines.append(f"   ⚠ Greska modula: {error}")
        lines.append("")

    return "\n".join(lines)


CONTEXT_ANALYSIS_PROMPT = """FORENZICKA SINTEZA — analiziraj sliku U KONTEKSTU forenzickih rezultata.

Ispod su rezultati 8 forenzickih modula koji su statisticki i ML metodama analizirali sliku.
TVOJ ZADATAK: sintetiziraj ove rezultate s vlastitom vizualnom analizom u koherentan izvjestaj.

{forensic_context}

=== TVOJ ZADATAK ===
Na temelju GORNJIH forenzickih rezultata I vlastite vizualne analize slike, napravi detaljan izvjestaj.

PRAVILA:
- Ako ukupni forenzicki rizik >= 0.50 (HIGH/CRITICAL), VECINA nalaza MORA biti Severe ili Critical
- Ako bilo koji modul ima rizik >= 0.70, MORAS imati barem 2 nalaza sa severity Critical
- Za svaki forenzicki nalaz visokog rizika, objasni sto VIZUALNO vidis sto to potvrduje
- Ako forenzicki moduli detektiraju AI generiranje, tvoj izvjestaj MORA to jasno istaknuti
- NE SMIJES staviti sve nalaze na "Minor"/"Safe" ako forenzicki moduli kazu drugacije

MORAS vratiti MINIMALNO 5 nalaza, idealno 6-8. Svaki nalaz pokriva drugo podrucje.

Za svaki nalaz:
- damage_cause: kategorija nalaza (vidi popis dolje)
- severity: Minor (niska sumnja) | Moderate (umjerena) | Severe (visoka) | Critical (kriticna)
- safety_rating: Safe (autenticno) | Warning (sumnjivo) | Critical (krivotvoreno/AI)
- description: DETALJAN opis na HRVATSKOM, 3-5 recenica. Povezi forenzicke nalaze s vizualnim dokazima.
- bounding_box: PRECIZNE koordinate sumnjivog podrucja (0.0-1.0)
- confidence: tvoja pouzdanost u nalaz (0.0-1.0)

=== KATEGORIJE NALAZA (damage_cause) ===
- "AI generiranje" - znakovi da je sadrzaj generiran umjetnom inteligencijom
- "Digitalna manipulacija" - znakovi rucne obrade (Photoshop, GIMP, slicno)
- "Copy-paste krivotvorina" - klonirane/kopirane regije unutar slike
- "Rekompresijski artefakti" - sumnjivi kompresijski artefakti koji ukazuju na obradu
- "Nekonzistentno osvjetljenje" - razlike u osvjetljenju izmedju dijelova scene
- "Metadata anomalija" - nekonzistentnosti u metapodacima
- "Deepfake indikator" - znakovi deepfake generiranja ili zamjene lica
- "Sumnjiva tekstura" - neprirodne teksture tipicne za AI ili obradu
- "Perspektivna anomalija" - nekonzistentna perspektiva ili geometrija
- "Statisticka anomalija" - DCT spektar, sum, ili drugi statisticki pokazatelji odstupaju od normalnog
- "Autenticno" - aspekt koji potvrduje autenticnost (SAMO ako forenzicki moduli potvrduju nizak rizik)

=== OBAVEZAN JSON FORMAT ===
Odgovori ISKLJUCIVO validnim JSON-om, bez objasnjenja ili markdowna:

{{
  "vehicle_info": {{
    "make": null,
    "model": null,
    "year": null,
    "color": null
  }},
  "damages": [
    {{
      "damage_type": "Other",
      "car_part": "Other",
      "severity": "Minor|Moderate|Severe|Critical",
      "description": "DETALJAN opis nalaza na HRVATSKOM. 3-5 recenica. Povezi forenzicke module s vizualnim dokazima.",
      "confidence": 0.85,
      "bounding_box": {{"x": 0.1, "y": 0.2, "w": 0.3, "h": 0.25}},
      "source_image_index": 0,
      "damage_cause": "Kategorija iz popisa",
      "safety_rating": "Safe|Warning|Critical",
      "material_type": null,
      "repair_method": null,
      "repair_operations": null,
      "repair_category": null,
      "estimated_cost_min": null,
      "estimated_cost_max": null,
      "labor_hours": null,
      "parts_needed": null,
      "repair_line_items": []
    }}
  ],
  "overall_assessment": {{
    "summary": "DETALJAN forenzicki izvjestaj na HRVATSKOM u 5-8 recenica. Obavezno navedi rezultate forenzickih modula i kako se poklapaju s vizualnom analizom. Budi konkretan — navedi module i njihove rizike.",
    "structural_integrity": "Procjena digitalnog integriteta slike temeljem forenzickih modula i vizualne analize. 2-3 recenice na HRVATSKOM.",
    "total_cost_min": null,
    "total_cost_max": null,
    "is_driveable": null,
    "urgency_level": "Low|Medium|High|Critical",
    "labor_total": null,
    "parts_total": null,
    "materials_total": null,
    "gross_total": null
  }}
}}

=== KRITICNA PRAVILA ===
1. UVIJEK vrati MINIMALNO 5 nalaza. Nikad prazan damages array.
2. damage_type UVIJEK "Other", car_part UVIJEK "Other"
3. Severity MORA odrazavati forenzicke rezultate — ne smijes ignorirati visoke rizike
4. safety_rating: Safe SAMO ako forenzicki moduli potvrduju nizak rizik
5. bounding_box koordinate 0.0-1.0, PRECIZNO na analiziranom podrucju
6. Svi opisi na HRVATSKOM jeziku
7. UVIJEK vrati validan JSON
8. Troskovi (estimated_cost_min/max, labor_total, itd.) UVIJEK null
9. overall_assessment.summary MORA spominjati forenzicke module i njihove rezultate
10. overall_assessment.urgency_level: High ili Critical ako ukupni forenzicki rizik >= 0.50"""


@router.post("/analyze-with-context", response_model=AnalysisResponse)
async def analyze_with_context(
    file: UploadFile = File(...),
    forensic_context: str = Form("{}"),
):
    """Context-aware analysis: receives forensic results and synthesizes them with visual analysis."""
    contents = await file.read()
    size_mb = len(contents) / (1024 * 1024)

    if size_mb > settings.max_image_size_mb:
        raise HTTPException(
            status_code=413,
            detail=f"Image too large: {size_mb:.1f}MB (max {settings.max_image_size_mb}MB)",
        )

    # Parse forensic context
    try:
        forensic_data = json.loads(forensic_context)
    except json.JSONDecodeError:
        logger.warning("Invalid forensic_context JSON, falling back to no-context analysis")
        forensic_data = {}

    image_b64 = base64.b64encode(contents).decode("utf-8")
    media_type = get_media_type(file.filename or "image.jpg")

    # If we have forensic context, use context-aware prompts
    if forensic_data and forensic_data.get("modules"):
        forensic_text = _format_forensic_context(forensic_data)
        prompt_text = CONTEXT_ANALYSIS_PROMPT.format(forensic_context=forensic_text)
        system = CONTEXT_SYSTEM_PROMPT

        # ── FRAUD REPORT MODE ─────────────────────────────────────
        # When fusion score >= 0.50, inject strict fraud-report
        # instructions that FORBID the LLM from generating
        # "Autenticno" findings or low-severity ratings.
        overall_risk = forensic_data.get("overall_risk_score", 0)
        if overall_risk >= 0.50:
            fraud_header = (
                "\n=== ⚠ FRAUD REPORT MODE ===\n"
                "Forenzicki moduli detektirali su VISOKU sumnju na manipulaciju/AI generiranje "
                f"(ukupni rizik: {overall_risk:.2f}).\n"
                "ZABRANJENO ti je:\n"
                "- Koristiti damage_cause \"Autenticno\"\n"
                "- Stavljati severity \"Minor\" ili safety_rating \"Safe\" na bilo koji nalaz\n"
                "- Pisati tekst koji opravdava autenticnost slike\n"
                "MORAS:\n"
                "- Opisati SVE detektirane anomalije\n"
                "- Koristiti severity Severe/Critical za fraud-related nalaze\n"
                "- Jasno istaknuti forenzicke dokaze u svakom opisu\n"
                "=== KRAJ FRAUD REPORT MODE ===\n\n"
            )
            prompt_text = fraud_header + prompt_text
    else:
        # Fallback to standard prompts if no forensic context
        prompt_text = ANALYSIS_PROMPT
        system = SYSTEM_PROMPT
        forensic_data = {}

    result = await _call_openrouter_with_prompt(
        [(image_b64, media_type)],
        system_prompt=system,
        analysis_prompt=prompt_text,
    )

    # ── Deterministic severity enforcement ─────────────────────
    # Post-process Gemini output: fusion scores override severity
    # ratings to prevent LLM from contradicting forensic evidence.
    if result.success and forensic_data.get("overall_risk_score", 0) > 0:
        result = _enforce_forensic_severity(result, forensic_data)

    return result


async def _call_openrouter_with_prompt(
    image_contents: list[tuple[str, str]],
    system_prompt: str,
    analysis_prompt: str,
) -> AnalysisResponse:
    """Call OpenRouter API with custom system/analysis prompts."""
    if not settings.openrouter_api_key:
        raise HTTPException(status_code=500, detail="OpenRouter API key not configured")

    user_content = []
    for idx, (b64_data, media_type) in enumerate(image_contents):
        user_content.append({
            "type": "image_url",
            "image_url": {"url": f"data:{media_type};base64,{b64_data}"},
        })

    user_content.append({"type": "text", "text": analysis_prompt})

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
                        {"role": "system", "content": system_prompt},
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
