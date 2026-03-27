import json
import logging
import unicodedata

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from ..config import settings
from ..forensics.thresholds import get_registry
from ..schemas import (
    AnalysisResponse,
    BoundingBox,
    DamageResult,
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
        # Semantic authenticity claims that bypass keyword check
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
    _enforce_forensic_severity and other functions work
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
    Deterministic post-processing: override severity ratings
    to match forensic fusion scores.

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

    # ── AI-specific override REMOVED ──────────────────────────────────
    # Previously: individual AI detectors with risk >= 0.45 would override
    # "Autenticno" findings to "AI generiranje" + Critical, BYPASSING
    # the fusion score.  This caused false positives on authentic images
    # (e.g., car5.jpg: 22% fusion risk but EfficientNet=0.43 triggered
    # override).  The fusion score already handles consensus — individual
    # modules should not override it.
    modules = forensic_data.get("modules", [])

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

    # ── Registry must be loaded FIRST (used for thresholds below) ──
    reg = get_registry()

    # ── Only CORE + TAMPERING modules can generate mandatory findings ──
    # Support modules (metadata, spectral, optical, semantic, PRNU) are
    # informational — they appear in the forensic report but do NOT create
    # mandatory findings that drive the verdict. This prevents false
    # positives from noisy support modules on real photos.
    _FINDING_MODULES = {
        "ai_generation_detection",      # Core AI
        "clip_ai_detection",            # Core AI
        "vae_reconstruction",           # Core AI
        "deep_modification_detection",  # Tampering
        "modification_detection",       # Tampering (copy-move/ELA)
        "content_validation",           # Document (OIB/IBAN)
        "text_ai_detection",            # Document AI text
    }

    def _get_mod_risk(name: str) -> float:
        try:
            return float(mod_lookup.get(name, {}).get("risk_score", 0) or 0)
        except (TypeError, ValueError):
            return 0.0

    # ── Generate mandatory findings from allowed modules only ──
    findings: list[dict] = []
    damage_map = _get_module_damage_map()
    for mod_name, mapping in damage_map.items():
        # Skip modules not in the finding-allowed list
        if mod_name not in _FINDING_MODULES:
            continue

        mod = mod_lookup.get(mod_name)
        if not mod:
            continue
        mod_risk = _get_mod_risk(mod_name)

        threshold = mapping["threshold"]
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
                "description": "",
            })

    # ── Determine overall verdict — DRIVEN BY FUSION RISK SCORE ONLY ──
    # Individual module findings are informational — they appear in the
    # report but do NOT override the fused risk score.  The fusion layer
    # (fusion.py) already applies cross-validation, weighting, and
    # meta-learner consensus.  Counting findings here caused false
    # positives on authentic images (e.g. car5.jpg: 22% risk but 3
    # weak findings → "Potreban pregled").
    if risk >= reg.verdict.forged_risk:
        overall_verdict = "Krivotvoreno"
    elif risk >= reg.verdict.suspicious_risk:
        overall_verdict = "Sumnjivo"
    else:
        overall_verdict = "Autenticno"

    # ── Urgency — also driven by risk score only ──
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

        # Always use fallback_description for forensic findings.
        if cause in llm_by_cause and llm_by_cause[cause]:
            matched = llm_by_cause[cause].pop(0)
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


@router.post("/analyze-with-context", response_model=AnalysisResponse)
async def analyze_with_context(
    file: UploadFile = File(...),
    forensic_context: str = Form("{}"),
    capture_source: str = Form(""),
):
    """Purely deterministic analysis from forensic module scores.

    Flow:
    1. Parse forensic data
    2. _compute_deterministic_verdict() → all verdict fields
    3. Build findings from mandatory_findings (fallback descriptions)
    4. _enforce_forensic_severity() → final safety net
    5. Return result
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
        logger.warning("Invalid forensic_context JSON, falling back to empty")
        forensic_data = {}

    verdict = _compute_deterministic_verdict(
        forensic_data, capture_source=capture_source or None
    )

    logger.info(
        "deterministic_verdict: risk=%.2f, verdict=%s, findings=%d",
        verdict["risk"], verdict["overall_verdict"],
        len(verdict["mandatory_findings"]),
    )

    # Build damages from mandatory findings (no LLM — use fallback descriptions)
    damages: list[DamageResult] = []
    for f in verdict["mandatory_findings"]:
        damages.append(
            DamageResult(
                damage_type="Other",
                car_part="Other",
                severity=f["severity"],
                description=f["fallback_description"],
                confidence=f["confidence"],
                damage_cause=f["damage_cause"],
                safety_rating=f["safety_rating"],
                bounding_box=None,
            )
        )

    # If no mandatory findings, generate from forensic data as fallback
    if not damages and forensic_data:
        damages = _generate_mandatory_findings(forensic_data)

    result = AnalysisResponse(
        success=True,
        summary=verdict["summary_template"],
        urgency_level=verdict["urgency_level"],
        damages=damages,
    )

    # Final safety net: deterministic enforcement
    if forensic_data:
        result = _enforce_forensic_severity(
            result, forensic_data, capture_source=capture_source or None
        )

    return result
