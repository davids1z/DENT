import logging
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from io import BytesIO

from .models import ReportRequest

logger = logging.getLogger(__name__)


def generate_xml_certificate(request: ReportRequest) -> bytes:
    """Generate an XML evidence certificate inspired by ISO/IEC 27037."""

    root = ET.Element("EvidenceCertificate", {
        "xmlns": "urn:dent:evidence:v1",
        "version": "1.0",
        "generatedAt": datetime.now(timezone.utc).isoformat(),
    })

    # Inspection metadata
    meta = ET.SubElement(root, "InspectionMetadata")
    ET.SubElement(meta, "InspectionId").text = request.inspection_id
    ET.SubElement(meta, "CreatedAt").text = request.created_at
    ET.SubElement(meta, "CompletedAt").text = request.completed_at or ""

    vehicle = ET.SubElement(meta, "Vehicle")
    ET.SubElement(vehicle, "Make").text = request.vehicle_make or ""
    ET.SubElement(vehicle, "Model").text = request.vehicle_model or ""
    ET.SubElement(vehicle, "Year").text = str(request.vehicle_year) if request.vehicle_year else ""
    ET.SubElement(vehicle, "Color").text = request.vehicle_color or ""

    # Cost assessment
    costs = ET.SubElement(meta, "CostAssessment", currency=request.currency)
    ET.SubElement(costs, "EstimatedMin").text = f"{request.total_estimated_cost_min or 0:.2f}"
    ET.SubElement(costs, "EstimatedMax").text = f"{request.total_estimated_cost_max or 0:.2f}"
    ET.SubElement(costs, "GrossTotal").text = f"{request.gross_total:.2f}" if request.gross_total else ""

    # Evidence integrity
    integrity = ET.SubElement(root, "EvidenceIntegrity")
    ET.SubElement(integrity, "CombinedHash", algorithm="SHA-256").text = request.evidence_hash or ""

    img_hashes_el = ET.SubElement(integrity, "ImageHashes")
    for ih in request.image_hashes:
        img_el = ET.SubElement(img_hashes_el, "Image", fileName=ih.file_name)
        img_el.text = ih.sha256

    ET.SubElement(integrity, "ForensicResultHash", algorithm="SHA-256").text = (
        request.forensic_result_hash or ""
    )
    ET.SubElement(integrity, "AgentDecisionHash", algorithm="SHA-256").text = (
        request.agent_decision_hash or ""
    )

    # Qualified timestamp
    ts = ET.SubElement(root, "QualifiedTimestamp")
    ET.SubElement(ts, "TimestampedAt").text = request.timestamped_at or ""
    ET.SubElement(ts, "TimestampAuthority").text = request.timestamp_authority or ""
    ET.SubElement(ts, "TimestampToken", encoding="base64").text = request.timestamp_token or ""

    # Chain of custody
    chain = ET.SubElement(root, "ChainOfCustody")
    for evt in request.chain_of_custody:
        attrs = {"name": evt.event, "timestamp": evt.timestamp}
        if evt.hash:
            attrs["hash"] = evt.hash
        entry = ET.SubElement(chain, "Event", attrs)
        if evt.details:
            entry.text = evt.details

    # Assessment summary
    assessment = ET.SubElement(root, "AssessmentSummary")
    ET.SubElement(assessment, "DecisionOutcome").text = request.decision_outcome or ""
    ET.SubElement(assessment, "DecisionReason").text = request.decision_reason or ""
    ET.SubElement(assessment, "FraudRiskScore").text = f"{request.fraud_risk_score or 0:.4f}"
    ET.SubElement(assessment, "FraudRiskLevel").text = request.fraud_risk_level or ""

    if request.is_driveable is not None:
        ET.SubElement(assessment, "IsDriveable").text = str(request.is_driveable).lower()
    if request.structural_integrity:
        ET.SubElement(assessment, "StructuralIntegrity").text = request.structural_integrity
    if request.urgency_level:
        ET.SubElement(assessment, "UrgencyLevel").text = request.urgency_level

    # Damages
    damages_el = ET.SubElement(assessment, "Damages", count=str(len(request.damages)))
    for dmg in request.damages:
        d = ET.SubElement(damages_el, "Damage", {
            "type": dmg.damage_type,
            "part": dmg.car_part,
            "severity": dmg.severity,
            "confidence": f"{dmg.confidence:.2f}",
        })
        ET.SubElement(d, "Description").text = dmg.description
        if dmg.estimated_cost_min is not None:
            ET.SubElement(d, "EstimatedCost", currency=request.currency).text = (
                f"{dmg.estimated_cost_min:.2f}-{dmg.estimated_cost_max or 0:.2f}"
            )

    # Forensic modules
    forensics_el = ET.SubElement(assessment, "ForensicModules")
    for mod in request.forensic_modules:
        m = ET.SubElement(forensics_el, "Module", {
            "name": mod.module_name,
            "label": mod.module_label,
            "riskScore": f"{mod.risk_score:.4f}",
            "riskLevel": mod.risk_level,
        })
        for finding in mod.findings:
            f = ET.SubElement(m, "Finding", {
                "code": str(finding.get("code", "")),
                "riskScore": f"{finding.get('riskScore', 0):.4f}",
            })
            f.text = str(finding.get("title", ""))

    # Agent evaluation
    if request.agent_decision:
        agent_el = ET.SubElement(assessment, "AgentEvaluation")
        ad = request.agent_decision
        ET.SubElement(agent_el, "Outcome").text = ad.outcome
        ET.SubElement(agent_el, "Confidence").text = f"{ad.confidence:.2f}"
        ET.SubElement(agent_el, "StpEligible").text = str(ad.stp_eligible).lower()
        ET.SubElement(agent_el, "SummaryHr").text = ad.summary_hr

    # Serialize with XML declaration
    ET.indent(root, space="  ")
    buf = BytesIO()
    tree = ET.ElementTree(root)
    tree.write(buf, encoding="unicode", xml_declaration=True)
    return buf.getvalue().encode("utf-8")
