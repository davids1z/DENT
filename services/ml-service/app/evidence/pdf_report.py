import logging
import os
from datetime import datetime, timezone
from io import BytesIO

from fpdf import FPDF

from .models import ReportRequest

logger = logging.getLogger(__name__)

# Path to DejaVu font (installed via fonts-dejavu-core)
DEJAVU_REGULAR = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
DEJAVU_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
DEJAVU_MONO = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"


class DentPDF(FPDF):
    """Custom PDF with Croatian Unicode support and DENT branding."""

    def __init__(self):
        super().__init__()
        self.set_auto_page_break(auto=True, margin=20)

        # Register DejaVu fonts for Croatian diacritics
        if os.path.exists(DEJAVU_REGULAR):
            self.add_font("DejaVu", "", DEJAVU_REGULAR)
            self.add_font("DejaVu", "B", DEJAVU_BOLD)
            self.add_font("DejaVuMono", "", DEJAVU_MONO)
            self._font_family = "DejaVu"
            self._mono_family = "DejaVuMono"
        else:
            # Fallback to built-in fonts (limited Croatian support)
            self._font_family = "Helvetica"
            self._mono_family = "Courier"

    def font(self, style: str = "", size: int = 10):
        self.set_font(self._font_family, style, size)

    def mono(self, size: int = 8):
        self.set_font(self._mono_family, "", size)


def generate_pdf(request: ReportRequest) -> bytes:
    """Generate a professional forensic PDF report."""
    pdf = DentPDF()
    pdf.add_page()

    # Title
    pdf.font("B", 18)
    pdf.cell(0, 12, "Forenzički izvještaj o oštećenju vozila", new_x="LMARGIN", new_y="NEXT", align="C")
    pdf.font("", 10)
    pdf.cell(0, 6, "DENT - Automatska analiza šteta", new_x="LMARGIN", new_y="NEXT", align="C")
    pdf.cell(0, 6, f"ID: {request.inspection_id}", new_x="LMARGIN", new_y="NEXT", align="C")
    pdf.cell(0, 6, f"Datum: {request.created_at[:19] if request.created_at else 'N/A'}", new_x="LMARGIN", new_y="NEXT", align="C")
    pdf.ln(8)

    # Vehicle info
    _section_header(pdf, "Podaci o vozilu")
    _kv(pdf, "Proizvođač", request.vehicle_make or "N/A")
    _kv(pdf, "Model", request.vehicle_model or "N/A")
    _kv(pdf, "Godina", str(request.vehicle_year) if request.vehicle_year else "N/A")
    _kv(pdf, "Boja", request.vehicle_color or "N/A")
    if request.is_driveable is not None:
        _kv(pdf, "Vožljivo", "Da" if request.is_driveable else "Ne")
    if request.structural_integrity:
        _kv(pdf, "Strukturalni integritet", request.structural_integrity)
    if request.urgency_level:
        _kv(pdf, "Hitnost", request.urgency_level)
    pdf.ln(4)

    # Summary
    if request.summary:
        _section_header(pdf, "Sažetak")
        pdf.font("", 9)
        pdf.multi_cell(0, 5, request.summary)
        pdf.ln(4)

    # Damage assessment
    _section_header(pdf, "Pregled oštećenja")
    _kv(pdf, "Broj oštećenja", str(len(request.damages)))
    cost_min = request.total_estimated_cost_min or 0
    cost_max = request.total_estimated_cost_max or 0
    _kv(pdf, "Procjena troškova", f"{cost_min:,.2f} - {cost_max:,.2f} {request.currency}")
    if request.gross_total:
        _kv(pdf, "Ukupno (bruto)", f"{request.gross_total:,.2f} {request.currency}")
    if request.labor_total:
        _kv(pdf, "  Rad", f"{request.labor_total:,.2f} {request.currency}")
    if request.parts_total:
        _kv(pdf, "  Dijelovi", f"{request.parts_total:,.2f} {request.currency}")
    if request.materials_total:
        _kv(pdf, "  Materijali", f"{request.materials_total:,.2f} {request.currency}")
    pdf.ln(2)

    for i, dmg in enumerate(request.damages, 1):
        pdf.font("B", 9)
        severity_label = _severity_hr(dmg.severity)
        pdf.cell(0, 5, f"  {i}. {dmg.damage_type} — {dmg.car_part} ({severity_label})",
                 new_x="LMARGIN", new_y="NEXT")
        pdf.font("", 8)
        pdf.multi_cell(0, 4, f"     {dmg.description}")
        if dmg.estimated_cost_min is not None:
            pdf.cell(0, 4,
                     f"     Trošak: {dmg.estimated_cost_min:,.2f} - {dmg.estimated_cost_max or 0:,.2f} {request.currency}",
                     new_x="LMARGIN", new_y="NEXT")
    pdf.ln(4)

    # Forensic analysis
    _section_header(pdf, "Forenzička analiza prijevare")
    risk_pct = (request.fraud_risk_score or 0) * 100
    _kv(pdf, "Ukupni rizik", f"{risk_pct:.0f}% ({request.fraud_risk_level or 'N/A'})")

    for mod in request.forensic_modules:
        mod_pct = mod.risk_score * 100
        _kv(pdf, f"  {mod.module_label}", f"{mod_pct:.0f}% ({mod.risk_level})")
    pdf.ln(4)

    # Agent evaluation
    if request.agent_decision:
        _section_header(pdf, "AI evaluacija agenta")
        ad = request.agent_decision
        _kv(pdf, "Odluka", ad.outcome)
        _kv(pdf, "Pouzdanost", f"{ad.confidence * 100:.0f}%")
        _kv(pdf, "STP prihvatljivo", "Da" if ad.stp_eligible else "Ne")
        if ad.summary_hr:
            pdf.font("", 8)
            pdf.multi_cell(0, 4, f"  {ad.summary_hr}")
        if ad.fraud_indicators:
            pdf.font("B", 8)
            pdf.cell(0, 5, "  Indikatori prijevare:", new_x="LMARGIN", new_y="NEXT")
            pdf.font("", 8)
            for fi in ad.fraud_indicators:
                pdf.cell(0, 4, f"    • {fi}", new_x="LMARGIN", new_y="NEXT")
        pdf.ln(4)

    # Decision
    _section_header(pdf, "Odluka")
    _kv(pdf, "Ishod", request.decision_outcome or "N/A")
    if request.decision_reason:
        pdf.font("", 8)
        pdf.multi_cell(0, 4, f"  {request.decision_reason}")
    pdf.ln(4)

    # Evidence integrity (new page)
    pdf.add_page()
    _section_header(pdf, "Integritet dokaza")
    pdf.ln(2)

    pdf.font("B", 9)
    pdf.cell(0, 5, "SHA-256 hash dokaza:", new_x="LMARGIN", new_y="NEXT")
    pdf.mono(7)
    pdf.cell(0, 5, request.evidence_hash or "N/A", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(3)

    # Per-image hashes
    pdf.font("B", 9)
    pdf.cell(0, 5, "Hashevi slika:", new_x="LMARGIN", new_y="NEXT")
    for ih in request.image_hashes:
        pdf.font("", 8)
        pdf.cell(50, 4, f"  {ih.file_name}")
        pdf.mono(6)
        pdf.cell(0, 4, ih.sha256, new_x="LMARGIN", new_y="NEXT")
    pdf.ln(2)

    pdf.font("B", 9)
    pdf.cell(50, 5, "Forenzički hash:")
    pdf.mono(6)
    pdf.cell(0, 5, request.forensic_result_hash or "N/A", new_x="LMARGIN", new_y="NEXT")

    pdf.font("B", 9)
    pdf.cell(50, 5, "Agent hash:")
    pdf.mono(6)
    pdf.cell(0, 5, request.agent_decision_hash or "N/A", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(4)

    # Chain of custody
    _section_header(pdf, "Lanac skrbništva")
    pdf.font("B", 8)
    # Table header
    pdf.set_fill_color(230, 230, 230)
    pdf.cell(50, 5, "Vrijeme", border=1, fill=True)
    pdf.cell(40, 5, "Događaj", border=1, fill=True)
    pdf.cell(0, 5, "Detalji", border=1, fill=True, new_x="LMARGIN", new_y="NEXT")

    pdf.font("", 7)
    for evt in request.chain_of_custody:
        ts = evt.timestamp[:19] if evt.timestamp else ""
        event_label = _custody_event_hr(evt.event)
        pdf.cell(50, 4, ts, border=1)
        pdf.cell(40, 4, event_label, border=1)
        pdf.cell(0, 4, evt.details or "", border=1, new_x="LMARGIN", new_y="NEXT")
    pdf.ln(4)

    # Timestamp
    _section_header(pdf, "RFC 3161 vremenski pečat")
    if request.timestamp_token:
        _kv(pdf, "Zapečaćeno", request.timestamped_at or "N/A")
        _kv(pdf, "TSA", request.timestamp_authority or "N/A")
        pdf.mono(6)
        token_preview = request.timestamp_token[:100]
        pdf.multi_cell(0, 3, f"Token: {token_preview}...")
    else:
        pdf.font("", 9)
        pdf.cell(0, 5, "Vremenski pečat nije dostupan.", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(4)

    # Footer
    pdf.ln(8)
    pdf.font("", 7)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    pdf.cell(0, 4,
             f"Generirano: {now} | DENT Faza 8 — Paket dokaza | eIDAS kompatibilno",
             new_x="LMARGIN", new_y="NEXT", align="C")

    return pdf.output()


def _section_header(pdf: DentPDF, title: str):
    pdf.font("B", 12)
    pdf.set_fill_color(240, 240, 240)
    pdf.cell(0, 8, f"  {title}", new_x="LMARGIN", new_y="NEXT", fill=True)
    pdf.ln(2)


def _kv(pdf: DentPDF, key: str, value: str):
    pdf.font("B", 9)
    pdf.cell(55, 5, key)
    pdf.font("", 9)
    pdf.cell(0, 5, value, new_x="LMARGIN", new_y="NEXT")


def _severity_hr(severity: str) -> str:
    mapping = {
        "Minor": "Manje",
        "Moderate": "Umjereno",
        "Severe": "Teško",
        "Critical": "Kritično",
    }
    return mapping.get(severity, severity)


def _custody_event_hr(event: str) -> str:
    mapping = {
        "image_received": "Slika zaprimljena",
        "analysis_complete": "Analiza završena",
        "forensics_complete": "Forenzika završena",
        "agent_complete": "AI evaluacija",
        "decision_complete": "Odluka donesena",
        "evidence_sealed": "Dokazi zapečaćeni",
        "timestamp_failed": "Pečat neuspješan",
    }
    return mapping.get(event, event)
