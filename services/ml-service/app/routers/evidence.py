import logging

from fastapi import APIRouter
from fastapi.responses import Response

from ..config import settings
from ..evidence.models import (
    CertificateRequest,
    ReportRequest,
    TimestampRequest,
    TimestampResponse,
)
from ..evidence.pdf_report import generate_pdf
from ..evidence.timestamp import obtain_timestamp
from ..evidence.xml_certificate import generate_xml_certificate

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/evidence")


@router.post("/timestamp", response_model=TimestampResponse)
async def get_timestamp(request: TimestampRequest) -> TimestampResponse:
    """Obtain an RFC 3161 timestamp for an evidence hash."""
    if not settings.evidence_enabled:
        return TimestampResponse(success=False, error="Evidence module disabled")

    return await obtain_timestamp(
        request.evidence_hash,
        tsa_url=settings.evidence_tsa_url,
    )


@router.post("/report")
async def generate_report(request: ReportRequest) -> Response:
    """Generate a court-admissible forensic PDF report."""
    pdf_bytes = generate_pdf(request)
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="dent-izvjestaj-{request.inspection_id[:8]}.pdf"'
        },
    )


@router.post("/certificate")
async def generate_certificate(request: CertificateRequest) -> Response:
    """Generate an XML evidence certificate (ISO/IEC 27037 inspired)."""
    xml_bytes = generate_xml_certificate(request)
    return Response(
        content=xml_bytes,
        media_type="application/xml",
        headers={
            "Content-Disposition": f'attachment; filename="dent-certifikat-{request.inspection_id[:8]}.xml"'
        },
    )
