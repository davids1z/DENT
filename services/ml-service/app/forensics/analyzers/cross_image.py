"""Cross-image comparison analyzer for group forensic analysis."""
import time
import logging
from collections import Counter
from ..base import CrossImageFinding, CrossImageReport, ForensicReport

logger = logging.getLogger(__name__)


def analyze_cross_image(
    file_bytes_list: list[bytes],
    file_names: list[str],
    per_file_reports: list[ForensicReport],
) -> CrossImageReport:
    """Compare multiple files to find cross-image inconsistencies."""
    start = time.time()
    findings: list[CrossImageFinding] = []

    if len(per_file_reports) < 2:
        return CrossImageReport(processing_time_ms=0)

    # 1. EXIF metadata consistency
    findings.extend(_check_metadata_consistency(per_file_reports, file_names))

    # 2. Risk score patterns
    findings.extend(_check_risk_patterns(per_file_reports, file_names))

    # 3. Source attribution consistency
    findings.extend(_check_source_consistency(per_file_reports, file_names))

    # 4. Compression consistency
    findings.extend(_check_compression_consistency(per_file_reports, file_names))

    # Calculate group risk modifier
    group_risk_modifier = _calculate_risk_modifier(findings)

    elapsed = int((time.time() - start) * 1000)
    return CrossImageReport(
        findings=findings,
        group_risk_modifier=group_risk_modifier,
        processing_time_ms=elapsed,
    )


def _get_metadata_evidence(report: ForensicReport) -> dict:
    """Extract metadata evidence from a forensic report's metadata module."""
    for module in report.modules:
        if module.module_name == "metadata_analysis":
            evidence = {}
            for finding in module.findings:
                if finding.evidence:
                    evidence.update(finding.evidence)
                # Extract device info from specific findings
                if finding.code == "META_NO_EXIF":
                    evidence["has_exif"] = False
                elif finding.code.startswith("META_"):
                    evidence["has_exif"] = evidence.get("has_exif", True)
            return evidence
    return {}


def _check_metadata_consistency(
    reports: list[ForensicReport], names: list[str]
) -> list[CrossImageFinding]:
    """Check EXIF metadata consistency across files."""
    findings = []

    # Extract metadata from each report
    meta_list = []
    for report in reports:
        meta = {}
        for module in report.modules:
            if module.module_name == "metadata_analysis":
                for finding in module.findings:
                    ev = finding.evidence or {}
                    if "make" in ev:
                        meta["make"] = ev["make"]
                    if "model" in ev:
                        meta["model"] = ev["model"]
                    if "software" in ev:
                        meta["software"] = ev["software"]
                    if "latitude" in ev and "longitude" in ev:
                        meta["gps"] = (ev["latitude"], ev["longitude"])
                    if "all_extracted_dates" in ev:
                        meta["dates"] = ev["all_extracted_dates"]
                break
        meta_list.append(meta)

    # Check camera make/model consistency
    devices = {}
    for i, meta in enumerate(meta_list):
        device = None
        if "make" in meta and "model" in meta:
            device = f"{meta['make']} {meta['model']}"
        elif "make" in meta:
            device = meta["make"]
        if device:
            devices[i] = device

    if len(set(devices.values())) > 1:
        affected = list(devices.keys())
        device_list = [f"{names[i]}: {devices[i]}" for i in affected]
        findings.append(CrossImageFinding(
            code="CROSS_META_CAMERA_MISMATCH",
            title="Razliciti uredaji",
            description=f"Datoteke snimljene razlicitim kamerama: {'; '.join(device_list)}. Ovo moze ukazivati na datoteke iz razlicitih izvora.",
            risk_score=0.45,
            confidence=0.85,
            affected_files=affected,
            evidence={"devices": devices},
        ))

    # Check GPS consistency (if multiple have GPS)
    gps_files = {i: meta["gps"] for i, meta in enumerate(meta_list) if "gps" in meta}
    if len(gps_files) >= 2:
        coords = list(gps_files.values())
        indices = list(gps_files.keys())
        # Simple distance check: if any pair is more than ~5km apart
        for j in range(len(coords)):
            for k in range(j + 1, len(coords)):
                lat_diff = abs(coords[j][0] - coords[k][0])
                lon_diff = abs(coords[j][1] - coords[k][1])
                # ~0.01 degree ~ 1.1km
                if lat_diff > 0.05 or lon_diff > 0.05:
                    findings.append(CrossImageFinding(
                        code="CROSS_META_GPS_MISMATCH",
                        title="Razlicite GPS lokacije",
                        description=f"Datoteke {names[indices[j]]} i {names[indices[k]]} imaju razlicite GPS koordinate (udaljenost > 5km). Ako su iz istog dogadaja, ovo je sumnjivo.",
                        risk_score=0.55,
                        confidence=0.80,
                        affected_files=[indices[j], indices[k]],
                        evidence={"gps_coords": {str(i): list(c) for i, c in gps_files.items()}},
                    ))
                    break  # One finding is enough
            else:
                continue
            break

    # Check software consistency
    software_files = {}
    for i, meta in enumerate(meta_list):
        if "software" in meta:
            software_files[i] = meta["software"]

    if len(set(software_files.values())) > 1:
        affected = list(software_files.keys())
        sw_list = [f"{names[i]}: {software_files[i]}" for i in affected]
        findings.append(CrossImageFinding(
            code="CROSS_META_SOFTWARE_MISMATCH",
            title="Razlicit softver za obradu",
            description=f"Datoteke obradene razlicitim softverom: {'; '.join(sw_list)}.",
            risk_score=0.30,
            confidence=0.70,
            affected_files=affected,
            evidence={"software": software_files},
        ))

    return findings


def _check_risk_patterns(
    reports: list[ForensicReport], names: list[str]
) -> list[CrossImageFinding]:
    """Detect risk score outliers and suspicious patterns."""
    findings = []
    scores = [r.overall_risk_score for r in reports]
    n = len(scores)

    if n < 2:
        return findings

    avg = sum(scores) / n

    # Check for outliers (Z-score-like: significantly different from mean)
    if n >= 3:
        std = (sum((s - avg) ** 2 for s in scores) / n) ** 0.5
        if std > 0.05:  # Only if there's meaningful variance
            for i, score in enumerate(scores):
                if std > 0 and abs(score - avg) > 2 * std and score > 0.50:
                    findings.append(CrossImageFinding(
                        code="CROSS_RISK_OUTLIER",
                        title="Rizicni outlier u skupini",
                        description=f"Datoteka {names[i]} ima znacajno visi rizik ({round(score * 100)}%) od prosjeka skupine ({round(avg * 100)}%). Ovo zasluzuje posebnu paznju.",
                        risk_score=0.50,
                        confidence=0.75,
                        affected_files=[i],
                        evidence={"outlier_score": round(score, 4), "group_avg": round(avg, 4), "group_std": round(std, 4)},
                    ))

    # All files high risk
    high_count = sum(1 for s in scores if s >= 0.50)
    if high_count == n and n >= 3:
        findings.append(CrossImageFinding(
            code="CROSS_RISK_ALL_HIGH",
            title="Svi fajlovi visokorizicni",
            description=f"Svih {n} datoteka ima visok rizik (prosjek {round(avg * 100)}%). Ovo snazno sugerira da cijela skupina zahtijeva detaljnu provjeru.",
            risk_score=0.70,
            confidence=0.85,
            affected_files=list(range(n)),
            evidence={"scores": [round(s, 4) for s in scores]},
        ))

    return findings


def _check_source_consistency(
    reports: list[ForensicReport], names: list[str]
) -> list[CrossImageFinding]:
    """Check if multiple files have the same AI generator attribution."""
    findings = []

    sources = {}
    for i, report in enumerate(reports):
        if report.predicted_source and report.source_confidence >= 40:
            sources[i] = report.predicted_source

    if len(sources) >= 2:
        # Count generators
        gen_counts = Counter(sources.values())
        most_common_gen, count = gen_counts.most_common(1)[0]

        if count >= 2:
            affected = [i for i, s in sources.items() if s == most_common_gen]
            findings.append(CrossImageFinding(
                code="CROSS_SAME_GENERATOR",
                title="Isti AI generator detektiran",
                description=f"{count} od {len(reports)} datoteka prepoznato kao generirano istim AI alatom ({most_common_gen}). Ovo snazno sugerira AI-generirani sadrzaj.",
                risk_score=0.75,
                confidence=0.85,
                affected_files=affected,
                evidence={"generator": most_common_gen, "count": count, "all_sources": sources},
            ))

    return findings


def _check_compression_consistency(
    reports: list[ForensicReport], names: list[str]
) -> list[CrossImageFinding]:
    """Check JPEG compression quality consistency across files."""
    findings = []

    # Look for compression-related findings in metadata
    quality_levels = {}
    for i, report in enumerate(reports):
        for module in report.modules:
            if module.module_name == "metadata_analysis":
                for finding in module.findings:
                    ev = finding.evidence or {}
                    if "quality" in ev:
                        quality_levels[i] = ev["quality"]
                    elif "compression" in ev:
                        quality_levels[i] = ev["compression"]

    if len(quality_levels) >= 2:
        values = list(quality_levels.values())
        # Check if quality levels differ significantly
        try:
            numeric = [float(v) for v in values if str(v).replace(".", "").isdigit()]
            if len(numeric) >= 2:
                q_range = max(numeric) - min(numeric)
                if q_range > 30:  # Significant quality difference
                    affected = list(quality_levels.keys())
                    findings.append(CrossImageFinding(
                        code="CROSS_COMPRESSION_MISMATCH",
                        title="Nekonzistentna kompresija",
                        description=f"Datoteke imaju razlicite razine JPEG kompresije (raspon: {q_range:.0f}). Ovo moze ukazivati na datoteke iz razlicitih izvora ili razlicitu obradu.",
                        risk_score=0.25,
                        confidence=0.65,
                        affected_files=affected,
                        evidence={"quality_levels": quality_levels},
                    ))
        except (ValueError, TypeError):
            pass

    return findings


def _calculate_risk_modifier(findings: list[CrossImageFinding]) -> float:
    """Calculate the group risk modifier based on cross-image findings."""
    if not findings:
        return 0.0

    # Use the max finding risk score scaled down
    max_finding_risk = max(f.risk_score for f in findings)

    # More findings = higher modifier (but capped)
    count_factor = min(len(findings) / 5.0, 1.0)  # caps at 5 findings

    # Modifier is 10-30% of the max finding risk, scaled by count
    modifier = max_finding_risk * 0.15 * (1.0 + count_factor)

    return round(min(modifier, 0.30), 4)  # Cap at 0.30
