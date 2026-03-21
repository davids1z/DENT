import asyncio
import base64
import json
import logging
import unicodedata

import httpx
from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import ValidationError

from ..config import settings
from ..forensics.fusion import _AI_DETECTOR_MODULES
from ..forensics.fusion import DEFAULT_WEIGHTS
from ..forensics.thresholds import get_registry
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


# ──────────────────────────────────────────────────────────────────────
# Unicode-safe text helpers
# ──────────────────────────────────────────────────────────────────────

def _normalize_text(s: str) -> str:
    """Strip diacritics (č→c, ž→z, …) and lowercase for robust matching."""
    nfkd = unicodedata.normalize("NFKD", s)
    return "".join(c for c in nfkd if not unicodedata.combining(c)).strip().lower()


def _is_authentic_cause(cause: str | None) -> bool:
    """Return True if *cause* is any spelling/diacritic variant of 'Autentično'."""
    if not cause:
        return False
    n = _normalize_text(cause)
    return n in {"autenticno", "autenticna", "authentic", "autenticni",
                 "autentican", "autenticnost"}


def _text_contradicts_forensics(text: str) -> bool:
    """Return True if *text* contains phrases that contradict high-risk forensic results."""
    n = _normalize_text(text)
    contradictions = [
        # Direct authenticity claims
        "autenticna", "autenticno", "autenticna fotografija",
        "nema sumnje", "nema manipulacije", "prava fotografija",
        "originalna", "originalna fotografija", "autenticna slika",
        "nema znakova manipulacije", "nema znakova krivotvorenja",
        "slika je autenticna", "fotografija je autenticna",
        # Semantic authenticity claims Gemini uses to bypass keyword check
        "ne pokazuju znakove ai generiranja",
        "ne pokazuju znakove ai",
        "konzistentni s fotografijom",
        "potvrduje autenticnost",
        "dodatno potvrduje autenticnost",
        "dokaz o stvarnoj fotografiji",
        "snazan dokaz da se radi o stvarnoj",
        "iskljucuje mogucnost digitalnog",
        "ne pokazuju anomalije",
        "ne otkriva nikakve anomalije",
        "nema nikakvih naznaka",
        "u potpunosti konzistentne",
        "u potpunosti konzistentni",
        "u potpunosti konzistentno",
        "fizicki plauzibilne",
        "fizicki plausibilne",
        "fizicki tocni",
        "bez plasticnog ili uljastog izgleda",
        "bez tragova mekih rubova",
        "bez tragova digitalnog",
        "iskljucuje mogucnost",
        "snazno upucuje na jedinstven",
    ]
    return any(c in n for c in contradictions)


def _normalize_forensic_keys(data: dict) -> dict:
    """Normalize forensic data keys from camelCase (C# API) to snake_case.

    The C# API deserializes the ForensicReport (snake_case from Python)
    into C# objects and re-serializes as camelCase. This helper ensures
    _format_forensic_context and _enforce_forensic_severity work
    regardless of which convention arrives.
    """
    _TOP = {
        "overallRiskScore": "overall_risk_score",
        "overallRiskLevel": "overall_risk_level",
        "totalProcessingTimeMs": "total_processing_time_ms",
        "elaHeatmapB64": "ela_heatmap_b64",
        "fftSpectrumB64": "fft_spectrum_b64",
        "spectralHeatmapB64": "spectral_heatmap_b64",
    }
    _MOD = {
        "moduleName": "module_name",
        "moduleLabel": "module_label",
        "riskScore": "risk_score",
        "riskLevel": "risk_level",
        "processingTimeMs": "processing_time_ms",
    }
    _FINDING = {
        "riskScore": "risk_score",
    }

    out = {_TOP.get(k, k): v for k, v in data.items()}

    if "modules" in out:
        modules = []
        for m in out["modules"]:
            mod = {_MOD.get(k, k): v for k, v in m.items()}
            if "findings" in mod:
                mod["findings"] = [
                    {_FINDING.get(k, k): v for k, v in f.items()}
                    for f in mod["findings"]
                ]
            modules.append(mod)
        out["modules"] = modules

    return out

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

=== KRITICNO UPOZORENJE O AI SLIKAMA ===
Moderni AI generatori (DALL-E 3, Midjourney v6, Stable Diffusion XL, Flux)
stvaraju FOTOREALISTICNE slike koje cak i eksperti tesko vizualno razlikuju
od pravih fotografija. NE OSLANJAJ SE na vizualni dojam za procjenu
autenticnosti — FORENZICKI MODULI su jedini pouzdani izvor informacija.

=== PRIORITET 1: AI DETEKCIJA — 5 NEZAVISNIH DETEKTORA ===
Sustav ima 5 specijaliziranih AI detektora. Svaki koristi RAZLICITU metodu:

1. ai_generation_detection (Swin Transformer): Obucen na 500k+ parova real/fake.
   >= 0.55: Severity MORA biti Severe ili Critical.

2. clip_ai_detection (CLIP ViT-L/14): Koristi pretrained CLIP embeddings.
   >= 0.45: Nezavisan signal od Swin detektora. Severity Moderate/Severe.

3. prnu_detection (PRNU senzorski sum): Provjerava digitalni otisak kamere.
   >= 0.50: Slika NEMA pravi senzorski sum kamere. Severity Moderate/Severe.

4. vae_reconstruction (VAE rekonstrukcija): Mjeri koliko lako VAE rekonstruira sliku.
   >= 0.50: AI slike se lakse rekonstruiraju. Severity Moderate/Severe.

5. spectral_forensics (Frekvencijska analiza): Analizira frekvencijski spektar.
   >= 0.40: Deficit visokih frekvencija, plosnati spektar. Severity Moderate/Severe.

PRAVILO: Ako BILO KOJI od ovih detektora >= 0.50, NE SMIJES proglasiti sliku autenticnom!

=== PRIORITET 2: CROSS-VALIDATION (vise detektora) ===
- Ako 2+ AI detektora >= 0.50: Gotovo SIGURAN dokaz AI generiranja. Severity Critical.
- Ako 3+ AI detektora >= 0.50: NEPOBITNO. Severity Critical za sve nalaze.
- Ako samo 1 detektor >= 0.50: Prijavi kao Severe, nije potpuno sigurno ali ozbiljno.

=== PRIORITET 3: C2PA KRIPTOGRAFSKI PECAT ===
- Ako C2PA manifest (META_C2PA_AI_GENERATED) detektiran u metadata modulu:
  Slika SAMA SEBE deklarira kao AI-generiranu putem kriptografski potpisanog
  C2PA manifesta. Ovo je nepobitni dokaz. Severity Critical.

=== PRIORITET 4: IZVOR SLIKE (captureSource) ===
- captureSource == "camera": Slikana kamerom, vece povjerenje.
- captureSource == "upload": Uploadana, potencijalno sumnjivo.
  Prijavi kao Moderate s damage_cause "Metadata anomalija".

=== OSTALI MODULI ===
- CNN modul (deep_modification_detection): manipulacija → Severe/Critical
- Semanticka analiza (SEM_AI_GENERATED_*): AI indikatori → Severe/Critical
- ELA analiza: sumnjive regije → Moderate/Severe
- Metadata anomalije → Moderate/Severe
- JEDINO ako SVI moduli imaju NIZAK rizik (<= 0.30), smijes koristiti Minor/Safe

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
        "pdf": "application/pdf",
        "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
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
    capture_source: str | None = None,
) -> AnalysisResponse:
    """
    Deterministic post-processing: override Gemini's severity ratings
    to match forensic fusion scores.  Gemini DESCRIBES findings,
    but fusion scores DETERMINE severity.

    Upload images get stricter thresholds (lowered by 0.15) because
    they bypass live camera anti-fraud controls.
    """
    try:
        risk = float(forensic_data.get("overall_risk_score", 0) or 0)
    except (TypeError, ValueError):
        risk = 0.0
    # Fallback: compute risk from modules if top-level is missing
    if risk == 0:
        modules = forensic_data.get("modules", [])
        if modules:
            scores = []
            for m in modules:
                if not m.get("error"):
                    try:
                        scores.append(float(m.get("risk_score", 0) or 0))
                    except (TypeError, ValueError):
                        pass
            if scores:
                risk = max(scores)
                logger.info("enforce: overall_risk_score was 0, computed from max module: %.2f", risk)
    logger.info(
        "enforce_forensic_severity: risk=%.2f, capture_source=%s, damages=%d, urgency_before=%s",
        risk, capture_source, len(response.damages), response.urgency_level,
    )

    # Upload images get stricter thresholds
    is_upload = capture_source == "upload"
    reg = get_registry()
    t_critical = reg.enforcement.upload_critical if is_upload else reg.enforcement.critical
    t_high = reg.enforcement.upload_high if is_upload else reg.enforcement.high
    t_medium = reg.enforcement.upload_medium if is_upload else reg.enforcement.medium

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

        if risk >= t_critical:  # CRITICAL fusion
            if is_fraud:
                d.severity = "Critical"
                d.safety_rating = "Critical"
            elif not _is_authentic_cause(d.damage_cause):
                if d.severity in ("Minor", "Moderate"):
                    d.severity = "Severe"
                if d.safety_rating == "Safe":
                    d.safety_rating = "Warning"

        elif risk >= t_high:  # HIGH fusion
            if is_fraud:
                if d.severity in ("Minor", "Moderate"):
                    d.severity = "Severe"
                if d.safety_rating == "Safe":
                    d.safety_rating = "Critical"

        elif risk >= t_medium:  # MEDIUM fusion
            if is_fraud:
                if d.severity == "Minor":
                    d.severity = "Moderate"
                if d.safety_rating == "Safe":
                    d.safety_rating = "Warning"

    # Forbid "Autenticno" findings when fusion >= HIGH
    if risk >= t_high:
        for d in response.damages:
            if _is_authentic_cause(d.damage_cause):
                d.damage_cause = "Metadata anomalija"
                d.severity = "Moderate" if risk < t_critical else "Severe"
                d.safety_rating = "Warning"
                d.description += (
                    " [Forenzicki moduli ukazuju na visok rizik manipulacije.]"
                )

    # ── AI-specific "Autenticno" override (defence-in-depth) ─────────
    # Even if the fusion score is below t_high, individual AI detectors
    # that fire with risk >= 0.45 must block "Autenticno" findings.
    modules = forensic_data.get("modules", [])
    any_ai_high = any(
        m.get("risk_score", 0) >= reg.enforcement.ai_detector_override
        for m in modules
        if m.get("module_name") in _AI_DETECTOR_MODULES
    )
    if any_ai_high:
        for d in response.damages:
            if _is_authentic_cause(d.damage_cause):
                d.damage_cause = "AI generiranje"
                d.severity = "Severe"
                d.safety_rating = "Critical"
                d.description += (
                    " [AI detekcijski moduli identificirali su sinteticki sadrzaj.]"
                )

    # Enforce urgency_level consistency
    old_urgency = response.urgency_level
    if risk >= t_critical:
        response.urgency_level = "Critical"
    elif risk >= t_high:
        response.urgency_level = "High"
    elif risk >= t_medium and response.urgency_level == "Low":
        response.urgency_level = "Medium"

    # ── HARD BLOCK: No "Safe" findings when risk >= t_high ──────────
    # The LLM may assign safety_rating="Safe" to findings with
    # innocuous damage_cause values (e.g., "Osvjetljenje").  When the
    # forensic fusion says the image is suspicious, NO finding may
    # remain "Safe".
    if risk >= t_high:
        for d in response.damages:
            if d.safety_rating == "Safe":
                d.safety_rating = "Warning"
                if d.severity == "Minor":
                    d.severity = "Moderate"
                logger.info(
                    "enforce: blocked Safe→Warning on cause=%s", d.damage_cause
                )

    # ── SUMMARY ENFORCEMENT ───────────────────────────────────────────
    # The LLM may write a summary praising the image as "authentic"
    # even when forensic modules strongly disagree.  Override it.
    if risk >= t_high and response.summary:
        if _text_contradicts_forensics(response.summary):
            triggered = [
                m.get("module_name", "?")
                for m in modules
                if float(m.get("risk_score", 0) or 0) >= 0.40 and not m.get("error")
            ]
            response.summary = (
                f"Forenzicka analiza utvrdila je visoku sumnju na manipulaciju "
                f"(ukupni rizik: {risk:.0%}). Detektirani signali: "
                f"{', '.join(triggered[:5]) or 'vise modula'}."
            )
            logger.info("enforce: summary overridden (contradicted forensics)")

    # ── DESCRIPTION ENFORCEMENT ───────────────────────────────────────
    # Individual finding descriptions must not claim authenticity
    # when forensic results indicate manipulation.
    if risk >= t_high:
        for d in response.damages:
            if d.description and _text_contradicts_forensics(d.description):
                d.description += (
                    " NAPOMENA: Forenzicki moduli ukazuju na visoku sumnju "
                    f"na manipulaciju (rizik: {risk:.0%})."
                )

    logger.info(
        "enforce_forensic_severity DONE: urgency=%s→%s, risk=%.2f, t_crit=%.2f, t_high=%.2f, causes=%s",
        old_urgency, response.urgency_level, risk, t_critical, t_high,
        [d.damage_cause for d in response.damages],
    )
    return response


# ──────────────────────────────────────────────────────────────────────
# Module → damage mapping: deterministic forensic verdict
# ──────────────────────────────────────────────────────────────────────

# Static part of the damage map (descriptions, severity labels).
# Thresholds are injected from ThresholdRegistry at call time.
_MODULE_DAMAGE_STATIC: dict[str, dict] = {
    "ai_generation_detection": {
        "damage_cause": "AI generiranje",
        "severity_high": "Critical",
        "severity_low": "Severe",
        "fallback_desc": (
            "Swin Transformer detektor (obucen na 500k+ slika) identificirao je "
            "karakteristike AI-generiranog sadrzaja u ovoj slici."
        ),
    },
    "clip_ai_detection": {
        "damage_cause": "AI generiranje",
        "severity_high": "Severe",
        "severity_low": "Moderate",
        "fallback_desc": (
            "CLIP ViT-L/14 analiza embeddinga detektirala je obrasce "
            "karakteristicne za AI-generirane slike."
        ),
    },
    "prnu_detection": {
        "damage_cause": "Metadata anomalija",
        "severity_high": "Severe",
        "severity_low": "Moderate",
        "fallback_desc": (
            "Analiza PRNU senzorskog suma nije pronasla konzistentan otisak "
            "fizicke kamere, sto ukazuje na sinteticki izvor slike."
        ),
    },
    "vae_reconstruction": {
        "damage_cause": "Sumnjiva tekstura",
        "severity_high": "Severe",
        "severity_low": "Moderate",
        "fallback_desc": (
            "VAE rekonstrukcijska analiza pokazala je da se slika lako "
            "rekonstruira, sto je karakteristicno za AI-generirani sadrzaj."
        ),
    },
    "spectral_forensics": {
        "damage_cause": "Spektralna anomalija",
        "severity_high": "Severe",
        "severity_low": "Moderate",
        "fallback_desc": (
            "Frekvencijska analiza (FFT) detektirala je anomalije u "
            "spektru slike koje ukazuju na obradu ili AI generiranje."
        ),
    },
    "deep_modification_detection": {
        "damage_cause": "Digitalna manipulacija",
        "severity_high": "Severe",
        "severity_low": "Moderate",
        "fallback_desc": (
            "CNN detektor modificiranih regija pronasao je znakove "
            "digitalne obrade u slici."
        ),
    },
    "modification_detection": {
        "damage_cause": "Rekompresijski artefakti",
        "severity_high": "Moderate",
        "severity_low": "Moderate",
        "fallback_desc": (
            "ELA analiza ili detekcija kloniranja pronasla je sumnjive "
            "regije koje ukazuju na mogucu manipulaciju."
        ),
    },
    "metadata_analysis": {
        "damage_cause": "Metadata anomalija",
        "severity_high": "Moderate",
        "severity_low": "Moderate",
        "fallback_desc": (
            "Analiza metapodataka otkrila je anomalije koje ukazuju "
            "na mogucu obradu ili generiranje slike."
        ),
    },
    "semantic_forensics": {
        "damage_cause": "Statisticka anomalija",
        "severity_high": "Moderate",
        "severity_low": "Moderate",
        "fallback_desc": (
            "Statisticka analiza piksela detektirala je obrasce "
            "netipcine za autenticne fotografije."
        ),
    },
    "optical_forensics": {
        "damage_cause": "Nekonzistentno osvjetljenje",
        "severity_high": "Moderate",
        "severity_low": "Moderate",
        "fallback_desc": (
            "Opticka analiza otkrila je nekonzistentnosti u osvjetljenju "
            "ili perspektivi slike."
        ),
    },
    "text_ai_detection": {
        "damage_cause": "AI generiranje",
        "severity_high": "Severe",
        "severity_low": "Moderate",
        "fallback_desc": (
            "Detektor AI teksta identificirao je da tekst u dokumentu "
            "ima karakteristike strojno generiranog sadrzaja."
        ),
    },
    "content_validation": {
        "damage_cause": "Krivotvoreni identifikatori",
        "severity_high": "Critical",
        "severity_low": "Severe",
        "fallback_desc": (
            "Validacija sadrzaja otkrila je nevazece identifikacijske brojeve "
            "(OIB ili IBAN) u dokumentu, sto ukazuje na krivotvorenje."
        ),
    },
}


def _get_module_damage_map() -> dict[str, dict]:
    """Build module damage map with thresholds from the registry."""
    reg = get_registry()
    result = {}
    for mod_name, static in _MODULE_DAMAGE_STATIC.items():
        entry = dict(static)
        if mod_name in reg.module_damage:
            entry["threshold"] = reg.module_damage[mod_name].threshold
        else:
            entry["threshold"] = 0.40  # safe default
        result[mod_name] = entry
    return result


def _compute_deterministic_verdict(
    forensic_data: dict,
    capture_source: str | None = None,
) -> dict:
    """Compute ALL verdict fields deterministically from forensic module scores.

    Returns a dict with:
      - risk: float (overall)
      - overall_verdict: "Autenticno" | "Sumnjivo" | "Krivotvoreno"
      - urgency_level: "Low" | "Medium" | "High" | "Critical"
      - summary_template: pre-built summary
      - mandatory_findings: list of dicts with predetermined fields
    """
    try:
        risk = float(forensic_data.get("overall_risk_score", 0) or 0)
    except (TypeError, ValueError):
        risk = 0.0

    modules = forensic_data.get("modules", [])
    is_upload = capture_source == "upload"

    # Build module lookup: module_name → module dict
    mod_lookup: dict[str, dict] = {}
    for m in modules:
        name = m.get("module_name")
        if name and not m.get("error"):
            mod_lookup[name] = m

    # ── Generate mandatory findings from modules that exceed thresholds ──
    findings: list[dict] = []
    damage_map = _get_module_damage_map()
    for mod_name, mapping in damage_map.items():
        mod = mod_lookup.get(mod_name)
        if not mod:
            continue
        try:
            mod_risk = float(mod.get("risk_score", 0) or 0)
        except (TypeError, ValueError):
            mod_risk = 0.0

        threshold = mapping["threshold"]
        # Upload images: lower thresholds by upload_offset
        if is_upload:
            md = reg.module_damage.get(mod_name)
            offset = md.upload_offset if md else 0.10
            threshold = max(0.10, threshold - offset)

        if mod_risk >= threshold:
            severity = mapping["severity_high"] if mod_risk >= 0.60 else mapping["severity_low"]
            safety = "Critical" if mod_risk >= 0.60 else "Warning"
            confidence = min(0.95, 0.50 + mod_risk * 0.40)

            findings.append({
                "damage_cause": mapping["damage_cause"],
                "severity": severity,
                "safety_rating": safety,
                "confidence": round(confidence, 2),
                "module_name": mod_name,
                "module_risk": round(mod_risk, 4),
                "fallback_description": mapping["fallback_desc"],
                # LLM will fill description; this is fallback
                "description": "",
            })

    # ── Determine overall verdict ──
    reg = get_registry()
    if risk >= reg.verdict.forged_risk or len(findings) >= reg.verdict.forged_min_findings:
        overall_verdict = "Krivotvoreno"
    elif risk >= reg.verdict.suspicious_risk or len(findings) >= reg.verdict.suspicious_min_findings:
        overall_verdict = "Sumnjivo"
    else:
        overall_verdict = "Autenticno"

    # ── Urgency ──
    if risk >= reg.verdict.urgency_critical:
        urgency = "Critical"
    elif risk >= reg.verdict.urgency_high:
        urgency = "High"
    elif risk >= reg.verdict.urgency_medium:
        urgency = "Medium"
    else:
        urgency = "Low"

    # ── Summary template ──
    triggered_names = [f["module_name"] for f in findings]
    if overall_verdict == "Krivotvoreno":
        summary = (
            f"Forenzicka analiza utvrdila je visoku sumnju na manipulaciju ili "
            f"AI generiranje (ukupni rizik: {risk:.0%}). "
            f"Detektirani signali iz {len(findings)} modula: "
            f"{', '.join(triggered_names[:5])}."
        )
    elif overall_verdict == "Sumnjivo":
        summary = (
            f"Forenzicka analiza detektirala je sumnjive indikatore "
            f"(ukupni rizik: {risk:.0%}). Detektirani signali: "
            f"{', '.join(triggered_names[:5]) or 'blagi indikatori'}."
        )
    else:
        summary = (
            f"Forenzicka analiza nije pronasla znacajne indikatore "
            f"manipulacije ili AI generiranja (ukupni rizik: {risk:.0%})."
        )

    return {
        "risk": risk,
        "overall_verdict": overall_verdict,
        "urgency_level": urgency,
        "summary_template": summary,
        "mandatory_findings": findings,
    }


def _generate_mandatory_findings(forensic_data: dict) -> list[DamageResult]:
    """Generate DamageResult findings from forensic modules when LLM returned nothing."""
    verdict = _compute_deterministic_verdict(forensic_data)
    damages = []
    for f in verdict["mandatory_findings"]:
        desc = f["fallback_description"]
        damages.append(
            DamageResult(
                damage_type="Other",
                car_part="Other",
                severity=f["severity"],
                description=desc,
                confidence=f["confidence"],
                damage_cause=f["damage_cause"],
                safety_rating=f["safety_rating"],
                bounding_box=None,
            )
        )
    return damages


def _hard_merge_with_verdict(
    llm_response: AnalysisResponse,
    verdict: dict,
) -> AnalysisResponse:
    """Merge LLM descriptions with predetermined verdict fields.

    The LLM is ONLY trusted for:
      - description text (checked for contradictions)
      - bounding_box coordinates
      - vehicle_info

    Everything else comes from the deterministic verdict.
    """
    mandatory = verdict["mandatory_findings"]
    risk = verdict["risk"]

    if not mandatory:
        # No modules triggered — keep LLM response as-is (low risk)
        return llm_response

    # Build final damages: use predetermined findings, enrich descriptions from LLM
    final_damages: list[DamageResult] = []

    # Try to match LLM damages to predetermined findings by damage_cause
    llm_by_cause: dict[str, list[DamageResult]] = {}
    for d in llm_response.damages:
        cause = d.damage_cause or "Unknown"
        llm_by_cause.setdefault(cause, []).append(d)

    used_llm_indices: set[int] = set()

    for mf in mandatory:
        # Find matching LLM damage for description
        llm_desc = mf["fallback_description"]
        llm_bbox = None
        cause = mf["damage_cause"]

        # Try exact cause match first
        if cause in llm_by_cause and llm_by_cause[cause]:
            matched = llm_by_cause[cause].pop(0)
            if matched.description and not _text_contradicts_forensics(matched.description):
                llm_desc = matched.description
            # If LLM contradicts forensics: keep fallback_description (don't use LLM text)
            llm_bbox = matched.bounding_box

        final_damages.append(
            DamageResult(
                damage_type="Other",
                car_part="Other",
                severity=mf["severity"],           # FROM VERDICT
                description=llm_desc,
                confidence=mf["confidence"],         # FROM VERDICT
                damage_cause=mf["damage_cause"],     # FROM VERDICT
                safety_rating=mf["safety_rating"],   # FROM VERDICT
                bounding_box=llm_bbox,
            )
        )

    # Override response
    llm_response.damages = final_damages
    llm_response.urgency_level = verdict["urgency_level"]

    # Summary: use verdict template (LLM summary is unreliable)
    llm_response.summary = verdict["summary_template"]

    return llm_response


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


# ──────────────────────────────────────────────────────────────────────
# Description-only prompt (Phase 2): LLM writes descriptions only.
# All verdict fields (severity, safety_rating, damage_cause) are
# predetermined by _compute_deterministic_verdict().
# ──────────────────────────────────────────────────────────────────────

DESCRIPTION_ONLY_SYSTEM = """Ti si DENT — profesionalni forenzicki sustav. Koristis AnomReason okvir.

TVOJ JEDINI ZADATAK: Popuni "description" polje za svaki nalaz u JSON-u ispod.
SVA ostala polja (severity, safety_rating, damage_cause, urgency_level, summary) su VEC ISPUNJENA
i DETERMINISTICKI IZRACUNATA iz forenzickih modula. NE SMIJES ih mijenjati.

=== AnomReason OKVIR ZA OPISE ===
Za svaki nalaz koristi strukturiranu 4-koracnu analizu:
1. OBJEKT: Imenuj tocno koji dio slike je zahvacen
2. FENOMEN: Opisi sto nije u redu s tim objektom
3. FIZIKA: Objasni ZASTO je to fizicki nemoguce ili sumnjivo
4. KOORDINATE: Daj TOCNE bounding_box koordinate (0.0-1.0) za taj objekt

Pisi na HRVATSKOM jeziku, 3-5 recenica po nalazu.

=== GROUNDING PRAVILA ===
- SVAKI objekt koji opisujes MORA imati bounding_box koordinate
- NE OPISUJ objekte koje ne mozes locirati na slici
- Ako forenzicki modul detektira AI generiranje, trazi VIZUALNE POTVRDE:
  * Sjene — idu li u istom smjeru? Pokazuju li prema istom izvoru svjetla?
  * Tekst — je li citljiv? Ima li smisla?
  * Metal/staklo — ponasaju li se refleksije realisticno?
  * Rubovi — su li realisticno ostri ili "AI-mekani"?
  * Perspektiva — konvergiraju li linije prema jednoj tocki nedogleda?

KRITICNO — STROGO SE PRIDRZAVAJ:
- SVAKI opis MORA biti KONZISTENTAN s damage_cause poljem tog nalaza.
  Ako damage_cause kaze "AI generiranje", opis MORA objasniti ZASTO se sumnja na AI generiranje.
  Ako damage_cause kaze "Digitalna manipulacija", opis MORA objasniti DOKAZE manipulacije (copy-move, splice).
  Ako damage_cause kaze "Rekompresijski artefakti", opis MORA objasniti DOKAZE nekonzistentne kompresije.
  Ako damage_cause kaze "Spektralna anomalija", opis MORA objasniti frekvencijske anomalije.
- NIKADA ne pisi da je slika "autenticna", "bez anomalija", "konzistentna", "realisticna"
  ili "bez znakova manipulacije" kad damage_cause ukazuje na problem.
- Ako NE vidis vizualne dokaze koji potvrduju damage_cause, RECI:
  "Forenzicki modul {module_name} detektirao je anomaliju s pouzdanoscu {confidence}%.
  Matematicka analiza piksela ukazuje na [opis nalaza], iako vizualna inspekcija ne pokazuje ocite znakove."
- Budi KONKRETAN — "metal na braniku se stapa s asfaltom" umjesto "slika izgleda sumnjivo".
- OVO JE FORENZICKI ALAT, NE ALAT ZA PROCJENU STETE. Ne opisuj fizicka ostecenja vozila.
  Opisuj DIGITALNE ANOMALIJE u slici.
"""


def _build_description_prompt(
    verdict: dict,
    forensic_text: str,
) -> str:
    """Build a prompt that asks the LLM to fill descriptions only."""
    findings_json = []
    for i, f in enumerate(verdict["mandatory_findings"]):
        findings_json.append({
            "index": i,
            "damage_cause": f["damage_cause"],
            "severity": f["severity"],
            "safety_rating": f["safety_rating"],
            "confidence": f["confidence"],
            "module_name": f["module_name"],
            "module_risk": f["module_risk"],
            "description": "<<POPUNI OVO POLJE: 3-5 recenica na hrvatskom>>",
            "bounding_box": {"x": 0.0, "y": 0.0, "w": 1.0, "h": 1.0},
        })

    template = {
        "damages": findings_json,
        "overall_assessment": {
            "structural_integrity": "<<POPUNI: 2-3 recenice o digitalnom integritetu slike>>",
        },
    }

    return f"""
{forensic_text}

=== UNAPRIJED ODREDJENI NALAZI ===
Ispod je JSON s nalazima gdje su SVA polja vec popunjena OSIM "description" i "bounding_box".
TVOJ ZADATAK: Zamijeni "<<POPUNI ...>>" s pravim tekstom na hrvatskom jeziku.
NE DODAVAJ nove nalaze. NE MIJENJAJ postojeca polja. SAMO popuni description i bounding_box.

Odgovori ISKLJUCIVO validnim JSON-om:

{json.dumps(template, ensure_ascii=False, indent=2)}
"""


def _parse_description_response(
    response_text: str,
    verdict: dict,
) -> list[tuple[str, dict | None]]:
    """Parse LLM response from description-only mode.

    Returns list of (description, bounding_box_raw) tuples aligned
    with verdict["mandatory_findings"].
    """
    try:
        data = _extract_json(response_text)
    except (json.JSONDecodeError, IndexError):
        # Fallback: return empty descriptions
        return [("", None)] * len(verdict["mandatory_findings"])

    damages = data.get("damages", [])
    result: list[tuple[str, dict | None]] = []

    for i, mf in enumerate(verdict["mandatory_findings"]):
        if i < len(damages):
            d = damages[i]
            desc = d.get("description", "")
            bb = d.get("bounding_box")
        else:
            desc = ""
            bb = None
        result.append((desc, bb))

    # Also extract structural_integrity if available
    return result


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
- "Autenticno" - aspekt koji potvrduje autenticnost (ZABRANJENO ako BILO KOJI AI detektor >= 0.45 ili ukupni rizik >= 0.30)

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
4. safety_rating: Safe SAMO ako SVI forenzicki moduli imaju nizak rizik (<= 0.30) I NIJEDAN AI detektor >= 0.45
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
    capture_source: str = Form(""),
):
    """Context-aware analysis — "Matematika odlucuje, LLM objasnjava".

    Flow:
    1. Parse forensic data
    2. _compute_deterministic_verdict() → all verdict fields
    3. Send image + predetermined findings to LLM for descriptions only
    4. _hard_merge_with_verdict() → keep ONLY descriptions from LLM
    5. _enforce_forensic_severity() → final safety net
    """
    contents = await file.read()
    size_mb = len(contents) / (1024 * 1024)

    if size_mb > settings.max_image_size_mb:
        raise HTTPException(
            status_code=413,
            detail=f"Image too large: {size_mb:.1f}MB (max {settings.max_image_size_mb}MB)",
        )

    # Parse forensic context (C# API sends camelCase keys, normalize to snake_case)
    try:
        forensic_data = _normalize_forensic_keys(json.loads(forensic_context))
    except json.JSONDecodeError:
        logger.warning("Invalid forensic_context JSON, falling back to no-context analysis")
        forensic_data = {}

    image_b64 = base64.b64encode(contents).decode("utf-8")
    media_type = get_media_type(file.filename or "image.jpg")

    if forensic_data and forensic_data.get("modules"):
        # ── NEW FLOW: Deterministic verdict + description-only LLM ──
        forensic_text = _format_forensic_context(forensic_data)
        verdict = _compute_deterministic_verdict(
            forensic_data, capture_source=capture_source or None
        )

        logger.info(
            "deterministic_verdict: risk=%.2f, verdict=%s, findings=%d",
            verdict["risk"], verdict["overall_verdict"],
            len(verdict["mandatory_findings"]),
        )

        if verdict["mandatory_findings"]:
            # LLM writes descriptions only — verdict fields are locked
            desc_prompt = _build_description_prompt(verdict, forensic_text)
            system = DESCRIPTION_ONLY_SYSTEM

            result = await _call_openrouter_with_prompt(
                [(image_b64, media_type)],
                system_prompt=system,
                analysis_prompt=desc_prompt,
            )

            # Hard-merge: take ONLY descriptions from LLM, everything else from verdict
            result = _hard_merge_with_verdict(result, verdict)
        else:
            # No modules triggered → low risk, use full context prompt
            prompt_text = CONTEXT_ANALYSIS_PROMPT.format(forensic_context=forensic_text)
            system = CONTEXT_SYSTEM_PROMPT
            result = await _call_openrouter_with_prompt(
                [(image_b64, media_type)],
                system_prompt=system,
                analysis_prompt=prompt_text,
            )
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

    # ── Final safety net: deterministic enforcement ──────────────
    if forensic_data:
        if not result.damages:
            result.damages = _generate_mandatory_findings(forensic_data)

        result = _enforce_forensic_severity(
            result, forensic_data, capture_source=capture_source or None
        )

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
        logger.error(f"Failed to parse AI response (with_prompt): {e}")
        logger.error(f"Raw response: {response_text[:500]}")
        return AnalysisResponse(success=False, error_message=f"Failed to parse AI response: {e}")
    except httpx.HTTPStatusError as e:
        logger.error(f"OpenRouter API error (with_prompt): {e.response.status_code} - {e.response.text}")
        return AnalysisResponse(success=False, error_message=f"AI service error: {e.response.status_code}")
    except Exception as e:
        logger.error(f"Unexpected error (with_prompt): {e}")
        return AnalysisResponse(success=False, error_message=str(e))


# ──────────────────────────────────────────────────────────────────────
# SSE Streaming endpoint: forensics + Gemini in one stream
# ──────────────────────────────────────────────────────────────────────

@router.post("/analyze-with-context/stream")
async def analyze_with_context_stream(
    file: UploadFile = File(...),
    forensic_context: str = Form("{}"),
    capture_source: str = Form(""),
):
    """SSE streaming analysis: forensics progress + Gemini analysis in one stream.

    Events emitted:
      {"type": "progress", "phase": "forensics", "module": "...", "progress": 0.xx}
      {"type": "progress", "phase": "gemini", "progress": 0.xx}
      {"type": "complete", "result": <AnalysisResponse dict>}
    """
    contents = await file.read()
    size_mb = len(contents) / (1024 * 1024)

    if size_mb > settings.max_image_size_mb:
        async def _too_large():
            yield f"data: {json.dumps({'type': 'error', 'message': f'Image too large: {size_mb:.1f}MB'})}\n\n"
        return StreamingResponse(_too_large(), media_type="text/event-stream")

    # Parse forensic context (normalize camelCase keys from C# API)
    try:
        forensic_data = _normalize_forensic_keys(json.loads(forensic_context))
    except json.JSONDecodeError:
        forensic_data = {}

    image_b64 = base64.b64encode(contents).decode("utf-8")
    media_type_str = get_media_type(file.filename or "image.jpg")

    progress_queue: asyncio.Queue = asyncio.Queue()

    def on_forensic_progress(module_name: str, pct: float) -> None:
        """Forensic pipeline progress: scale to 0-0.70 (forensics = 70% of total)."""
        progress_queue.put_nowait({
            "type": "progress",
            "phase": "forensics",
            "module": module_name,
            "progress": round(pct * 0.70, 2),
        })

    async def _stream():
        # ── Phase 1: Run forensics if no context provided ──────────
        if not forensic_data or not forensic_data.get("modules"):
            from .forensics import get_pipeline
            pipeline = get_pipeline()
            report = await pipeline.analyze(
                contents,
                file.filename or "unknown",
                None,
                progress_callback=on_forensic_progress,
            )
            effective_forensic = report.model_dump()
        else:
            effective_forensic = forensic_data
            progress_queue.put_nowait({
                "type": "progress",
                "phase": "forensics",
                "module": "pre-computed",
                "progress": 0.70,
            })

        forensic_text = _format_forensic_context(effective_forensic)

        # ── Phase 2: Deterministic verdict + LLM descriptions ──────
        yield f"data: {json.dumps({'type': 'progress', 'phase': 'gemini', 'progress': 0.75})}\n\n"

        verdict = _compute_deterministic_verdict(
            effective_forensic, capture_source=capture_source or None
        )

        if verdict["mandatory_findings"]:
            # LLM writes descriptions only — verdict fields are locked
            desc_prompt = _build_description_prompt(verdict, forensic_text)
            system = DESCRIPTION_ONLY_SYSTEM
            result = await _call_openrouter_with_prompt(
                [(image_b64, media_type_str)],
                system_prompt=system,
                analysis_prompt=desc_prompt,
            )
            result = _hard_merge_with_verdict(result, verdict)
        else:
            prompt_text = CONTEXT_ANALYSIS_PROMPT.format(forensic_context=forensic_text)
            system = CONTEXT_SYSTEM_PROMPT
            result = await _call_openrouter_with_prompt(
                [(image_b64, media_type_str)],
                system_prompt=system,
                analysis_prompt=prompt_text,
            )

        yield f"data: {json.dumps({'type': 'progress', 'phase': 'gemini', 'progress': 0.95})}\n\n"

        # ── Final safety net ──
        if effective_forensic:
            if not result.damages:
                result.damages = _generate_mandatory_findings(effective_forensic)
            result = _enforce_forensic_severity(
                result, effective_forensic, capture_source=capture_source or None
            )

        yield f"data: {json.dumps({'type': 'complete', 'result': result.model_dump()})}\n\n"

    async def _stream_with_progress():
        """Merge progress queue events with the analysis stream."""
        stream_gen = _stream()
        stream_done = False

        while not stream_done:
            while not progress_queue.empty():
                event = progress_queue.get_nowait()
                yield f"data: {json.dumps(event)}\n\n"

            try:
                chunk = await asyncio.wait_for(stream_gen.__anext__(), timeout=0.5)
                yield chunk
            except StopAsyncIteration:
                stream_done = True
            except asyncio.TimeoutError:
                yield ": keepalive\n\n"

        while not progress_queue.empty():
            event = progress_queue.get_nowait()
            yield f"data: {json.dumps(event)}\n\n"

    return StreamingResponse(_stream_with_progress(), media_type="text/event-stream")
