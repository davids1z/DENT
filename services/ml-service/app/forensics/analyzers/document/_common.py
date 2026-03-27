"""Shared imports, constants, and utility functions for document forensics."""

import base64
import difflib
import io
import logging
import re
import time
import unicodedata
from datetime import datetime, timedelta, timezone
from xml.etree import ElementTree

import numpy as np
from PIL import Image

from ...base import AnalyzerFinding, BaseAnalyzer, ModuleResult

logger = logging.getLogger(__name__)

# Graceful degradation for optional libraries
_PYPDF_AVAILABLE = False
try:
    from pypdf import PdfReader

    _PYPDF_AVAILABLE = True
except ImportError:
    logger.info("pypdf not installed, PDF document forensics disabled")

_PYHANKO_AVAILABLE = False
try:
    from pyhanko.pdf_utils.reader import PdfFileReader as HankoPdfReader
    from pyhanko.sign.validation import validate_pdf_signature

    _PYHANKO_AVAILABLE = True
except ImportError:
    logger.info("pyhanko not installed, PDF signature verification disabled")

_PYMUPDF_AVAILABLE = False
try:
    import fitz  # PyMuPDF

    _PYMUPDF_AVAILABLE = True
except ImportError:
    logger.info("PyMuPDF not installed, advanced PDF forensics (fake redaction/shadow) disabled")

_FONTTOOLS_AVAILABLE = False
try:
    from fontTools.ttLib import TTFont

    _FONTTOOLS_AVAILABLE = True
except ImportError:
    logger.info("fontTools not installed, font glyph analysis disabled")

_TESSERACT_AVAILABLE = False
try:
    import pytesseract

    _TESSERACT_AVAILABLE = True
except ImportError:
    logger.info("pytesseract not installed, Visual vs OCR comparison disabled")

# Known PDF editing software (keyword_lower, risk_score, display_name)
# Ordered from highest risk (online tools) to lowest risk (standard office).
PDF_EDITING_SOFTWARE: list[tuple[str, float, str]] = [
    # Online editing tools — highest risk (anonymous web-based manipulation)
    ("ilovepdf", 0.55, "iLovePDF"),
    ("smallpdf", 0.55, "Smallpdf"),
    ("pdf24", 0.55, "PDF24"),
    ("sejda", 0.55, "Sejda"),
    ("docfly", 0.55, "DocFly"),
    ("sodapdf", 0.50, "Soda PDF"),
    ("pdfcandy", 0.50, "PDF Candy"),
    ("pdf-xchange", 0.45, "PDF-XChange"),
    # Local editing tools
    ("pdftk", 0.45, "PDFtk"),
    ("itext", 0.40, "iText"),
    ("itextsharp", 0.40, "iTextSharp"),
    ("nitro", 0.40, "Nitro PDF"),
    ("qoppa", 0.40, "Qoppa PDF"),
    ("fpdf", 0.35, "FPDF"),
    ("tcpdf", 0.35, "TCPDF"),
    ("pdfsharp", 0.35, "PDFsharp"),
    ("foxit phantompdf", 0.35, "Foxit PhantomPDF"),
    ("reportlab", 0.30, "ReportLab"),
    ("adobe acrobat", 0.15, "Adobe Acrobat"),
    ("libreoffice", 0.10, "LibreOffice"),
    ("microsoft", 0.05, "Microsoft Office"),
]

# Unicode codepoints considered zero-width or invisible formatting
_ZERO_WIDTH_CHARS = frozenset({
    0x200B,  # ZWSP - Zero Width Space
    0x200C,  # ZWNJ - Zero Width Non-Joiner
    0x200D,  # ZWJ  - Zero Width Joiner
    0x200E,  # LRM  - Left-to-Right Mark
    0x200F,  # RLM  - Right-to-Left Mark
    0xFEFF,  # BOM  - Byte Order Mark (when used as ZWNBSP)
    # BiDi embedding/override controls
    0x202A,  # LRE  - Left-to-Right Embedding
    0x202B,  # RLE  - Right-to-Left Embedding
    0x202C,  # PDF  - Pop Directional Formatting
    0x202D,  # LRO  - Left-to-Right Override
    0x202E,  # RLO  - Right-to-Left Override
    # BiDi isolate controls (Unicode 6.3+)
    0x2066,  # LRI  - Left-to-Right Isolate
    0x2067,  # RLI  - Right-to-Left Isolate
    0x2068,  # FSI  - First Strong Isolate
    0x2069,  # PDI  - Pop Directional Isolate
})

# Cyrillic letters visually identical to Latin (homoglyphs)
_CYRILLIC_HOMOGLYPHS: dict[int, str] = {
    0x0410: "A",  # А
    0x0412: "B",  # В
    0x0421: "C",  # С
    0x0415: "E",  # Е
    0x041D: "H",  # Н
    0x041A: "K",  # К
    0x041C: "M",  # М
    0x041E: "O",  # О
    0x0420: "P",  # Р
    0x0422: "T",  # Т
    0x0425: "X",  # Х
    0x0430: "a",  # а
    0x0435: "e",  # е
    0x043E: "o",  # о
    0x0440: "p",  # р
    0x0441: "c",  # с
    0x0443: "y",  # у (looks like y)
    0x0445: "x",  # х
}


def _parse_pdf_date(date_str: str | None) -> datetime | None:
    """Parse a PDF date string (D:YYYYMMDDHHmmSSOHH'mm') into datetime."""
    if not date_str:
        return None
    # Strip D: prefix
    s = date_str.strip()
    if s.startswith("D:"):
        s = s[2:]

    # Try common formats
    for fmt in ("%Y%m%d%H%M%S", "%Y%m%d%H%M", "%Y%m%d"):
        try:
            # Take only the date portion (ignore timezone offset after +/- or Z)
            clean = re.split(r"[+\-Z]", s)[0]
            return datetime.strptime(clean, fmt).replace(tzinfo=timezone.utc)
        except (ValueError, IndexError):
            continue
    return None


def _parse_xmp_date(date_str: str | None) -> datetime | None:
    """Parse an XMP/ISO 8601 date string into datetime."""
    if not date_str:
        return None
    s = date_str.strip()
    # XMP dates: 2024-01-15T10:30:00+02:00 or 2024-01-15T10:30:00Z
    for fmt in (
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M",
        "%Y-%m-%d",
    ):
        try:
            clean = re.split(r"[+\-Z]", s)[0]
            return datetime.strptime(clean, fmt).replace(tzinfo=timezone.utc)
        except (ValueError, IndexError):
            continue
    return None
