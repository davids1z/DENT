"""Universal file triage: detect real file type via magic bytes."""

import logging

logger = logging.getLogger(__name__)

# python-magic is already a dependency (PyMagic)
_MAGIC_AVAILABLE = False
try:
    import magic

    _MAGIC_AVAILABLE = True
except ImportError:
    logger.info("python-magic not installed, file triage using extension only")


# Map detected MIME → file category for pipeline routing
SUPPORTED_TYPES: dict[str, str] = {
    # Images
    "image/jpeg": "image",
    "image/png": "image",
    "image/webp": "image",
    "image/heic": "image",
    "image/heif": "image",
    "image/gif": "image",
    "image/tiff": "image",
    # Documents
    "application/pdf": "pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "xlsx",
    # ZIP-based office docs sometimes detected as generic zip
    "application/zip": "zip_check",
}

# Extension-based fallback when magic bytes are ambiguous
EXTENSION_MAP: dict[str, str] = {
    ".jpg": "image",
    ".jpeg": "image",
    ".png": "image",
    ".webp": "image",
    ".heic": "image",
    ".heif": "image",
    ".gif": "image",
    ".tiff": "image",
    ".tif": "image",
    ".pdf": "pdf",
    ".docx": "docx",
    ".xlsx": "xlsx",
}


def triage_file(file_bytes: bytes, filename: str) -> tuple[str, str]:
    """Detect real file type via magic bytes.

    Returns:
        (category, detected_mime) where category is one of:
        "image", "pdf", "docx", "xlsx", "unknown"
    """
    detected_mime = ""

    # Step 1: Magic byte detection
    if _MAGIC_AVAILABLE:
        try:
            detected_mime = magic.from_buffer(file_bytes[:4096], mime=True)
        except Exception as e:
            logger.debug("Magic byte detection failed: %s", e)

    if detected_mime:
        category = SUPPORTED_TYPES.get(detected_mime)

        # Special handling: generic ZIP might be DOCX/XLSX
        if category == "zip_check":
            category = _check_zip_office(file_bytes, filename)

        if category:
            return category, detected_mime

    # Step 2: Extension-based fallback
    ext = ""
    if "." in filename:
        ext = "." + filename.rsplit(".", 1)[-1].lower()

    category = EXTENSION_MAP.get(ext, "unknown")
    return category, detected_mime or f"unknown/{ext}"


def _check_zip_office(file_bytes: bytes, filename: str) -> str:
    """Check if a ZIP file is actually a DOCX or XLSX by inspecting contents."""
    import zipfile
    import io

    try:
        with zipfile.ZipFile(io.BytesIO(file_bytes)) as zf:
            names = set(zf.namelist())
            if "[Content_Types].xml" in names:
                if any(n.startswith("word/") for n in names):
                    return "docx"
                if any(n.startswith("xl/") for n in names):
                    return "xlsx"
    except Exception:
        pass

    # Fall back to extension
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext == "docx":
        return "docx"
    if ext == "xlsx":
        return "xlsx"
    return "unknown"
