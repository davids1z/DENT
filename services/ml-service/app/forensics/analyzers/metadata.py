import io
import logging
import os
import tempfile
import time
from datetime import datetime, timezone

import magic
import numpy as np
from PIL import Image

from ...config import settings
from ..base import AnalyzerFinding, BaseAnalyzer, ModuleResult

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Try importing pyexiftool; fall back to exifread if ExifTool binary missing
# ---------------------------------------------------------------------------
_USE_EXIFTOOL = False
try:
    import exiftool

    _USE_EXIFTOOL = True
except ImportError:
    logger.info("pyexiftool not installed, falling back to exifread")

if not _USE_EXIFTOOL:
    try:
        import exifread  # type: ignore[import-untyped]
    except ImportError:
        exifread = None  # type: ignore[assignment]
        logger.warning("Neither pyexiftool nor exifread available")

# ---------------------------------------------------------------------------
# Try importing c2pa-python
# ---------------------------------------------------------------------------
_C2PA_AVAILABLE = False
try:
    import c2pa  # type: ignore[import-untyped]

    _C2PA_AVAILABLE = True
except ImportError:
    logger.info("c2pa-python not installed, C2PA validation disabled")

# ---------------------------------------------------------------------------
# Software names that indicate image editing / AI generation
# (keyword_lower, risk_score, display_name)
# ---------------------------------------------------------------------------
EDITING_SOFTWARE: list[tuple[str, float, str]] = [
    # ── Generic editing tools (low risk — most camera images go through one) ──
    ("photoshop", 0.30, "Adobe Photoshop"),
    ("gimp", 0.25, "GIMP"),
    ("faceapp", 0.35, "FaceApp"),
    ("facetune", 0.35, "FaceTune"),
    ("snapseed", 0.15, "Snapseed"),
    ("lightroom", 0.10, "Adobe Lightroom"),
    ("affinity", 0.15, "Affinity Photo"),
    ("pixelmator", 0.15, "Pixelmator"),
    ("paint.net", 0.20, "Paint.NET"),
    ("canva", 0.20, "Canva"),
    ("remove.bg", 0.30, "Remove.bg"),
    # ── AI generators (DEFINITIVE — bumped 2026-04-07 from 0.50 to 0.95) ──
    # When AI generator software is in EXIF/XMP metadata, the image is almost
    # certainly synthetic. Edge cases (rare): a real photo passed through an
    # AI tool for upscaling, where the tool overwrites Software tag. Even
    # then the user clearly used AI to modify the image, so high risk is
    # appropriate for fraud detection.
    ("dall-e", 0.95, "DALL-E"),
    ("dall·e", 0.95, "DALL-E"),
    ("dall e", 0.95, "DALL-E"),
    ("dalle", 0.95, "DALL-E"),
    ("midjourney", 0.95, "Midjourney"),
    ("stable diffusion", 0.95, "Stable Diffusion"),
    ("stable-diffusion", 0.95, "Stable Diffusion"),
    ("stablediffusion", 0.95, "Stable Diffusion"),
    ("comfyui", 0.95, "ComfyUI"),
    ("comfy ui", 0.95, "ComfyUI"),
    ("automatic1111", 0.95, "Automatic1111"),
    ("a1111", 0.95, "Automatic1111"),
    ("invoke ai", 0.95, "InvokeAI"),
    ("invokeai", 0.95, "InvokeAI"),
    ("novelai", 0.95, "NovelAI"),
    ("adobe firefly", 0.95, "Adobe Firefly"),
    ("firefly", 0.95, "Adobe Firefly"),
    ("runway", 0.85, "Runway ML"),
    ("flux.1", 0.95, "Flux.1"),
    ("flux1", 0.95, "Flux.1"),
    ("flux dev", 0.95, "Flux.1"),
    ("flux-dev", 0.95, "Flux.1"),
    ("flux schnell", 0.95, "Flux.1"),
    ("imagen", 0.90, "Google Imagen"),
    ("playground", 0.80, "PlaygroundAI"),
    ("playgroundai", 0.85, "PlaygroundAI"),
    ("leonardo.ai", 0.90, "Leonardo.ai"),
    ("leonardo ai", 0.90, "Leonardo.ai"),
    ("ideogram", 0.95, "Ideogram"),
    ("krea.ai", 0.85, "Krea.ai"),
    ("kandinsky", 0.95, "Kandinsky"),
    ("ernie-vilg", 0.95, "ERNIE-ViLG"),
    ("diffusers", 0.85, "HuggingFace Diffusers"),
    ("huggingface diffusers", 0.85, "HuggingFace Diffusers"),
    # Adobe Generative Fill / AI features inside Photoshop (specific markers)
    ("generative fill", 0.85, "Adobe Generative Fill"),
    ("generative expand", 0.85, "Adobe Generative Expand"),
    ("photoshop ai", 0.85, "Photoshop AI"),
]

# ExifTool tag keys for software detection (colon-separated group:tag)
SOFTWARE_EXIFTOOL_TAGS = [
    "EXIF:Software",
    "EXIF:ProcessingSoftware",
    "XMP:CreatorTool",
    "XMP:Software",
    "IPTC:OriginatingProgram",
]

# exifread fallback tag keys (space-separated group tag)
SOFTWARE_EXIFREAD_TAGS = [
    "Image Software",
    "Image ProcessingSoftware",
    "EXIF Software",
]

# Date tags — ExifTool keys
DATE_EXIFTOOL_TAGS: dict[str, str] = {
    "EXIF:DateTimeOriginal": "original",
    "EXIF:CreateDate": "create",
    "EXIF:ModifyDate": "modified",
    "EXIF:DateTimeDigitized": "digitized",
    "XMP:CreateDate": "xmp_create",
    "XMP:ModifyDate": "xmp_modify",
    "XMP:MetadataDate": "xmp_metadata",
}

# exifread fallback date tags
DATE_EXIFREAD_TAGS: dict[str, str] = {
    "EXIF DateTimeOriginal": "original",
    "EXIF DateTimeDigitized": "digitized",
    "Image DateTime": "modified",
}

# Valid image MIME types
VALID_IMAGE_MIMES: dict[str, list[str]] = {
    ".jpg": ["image/jpeg"],
    ".jpeg": ["image/jpeg"],
    ".png": ["image/png"],
    ".webp": ["image/webp"],
    ".heic": ["image/heic", "image/heif"],
    ".heif": ["image/heic", "image/heif"],
    ".tiff": ["image/tiff"],
    ".tif": ["image/tiff"],
    ".bmp": ["image/bmp", "image/x-ms-bmp"],
}

# XMP history tags (ExifTool returns lists for multi-entry histories)
XMP_HISTORY_TAGS = [
    "XMP:HistoryAction",
    "XMP:HistorySoftwareAgent",
    "XMP:HistoryWhen",
    "XMP:HistoryParameters",
]

# EXIF date format used by most cameras
_EXIF_DATE_FMT = "%Y:%m:%d %H:%M:%S"


class MetadataAnalyzer(BaseAnalyzer):
    MODULE_NAME = "metadata_analysis"
    MODULE_LABEL = "Analiza metapodataka"

    async def analyze_image(self, image_bytes: bytes, filename: str) -> ModuleResult:
        start = time.monotonic()
        findings: list[AnalyzerFinding] = []

        try:
            # 0. Filename pattern detection (AI generators use distinctive names)
            self._check_filename_ai_pattern(filename, findings)

            # 1. Magic byte / MIME validation
            self._check_magic_bytes(image_bytes, filename, findings)

            # 1b. PNG text chunk parsing — Stable Diffusion / ComfyUI / Auto1111
            #     leak prompts and generation parameters into PNG iTXt/tEXt
            #     chunks (e.g. tEXt "parameters", tEXt "prompt", iTXt "workflow").
            #     This is a definitive AI signal even when EXIF Software is empty.
            self._check_png_text_chunks(image_bytes, findings)

            # 2. Extract metadata (ExifTool or exifread fallback)
            metadata = self._extract_metadata(image_bytes, filename)
            if metadata:
                self._check_software_tags(metadata, findings)
                self._check_xmp_history(metadata, findings)
                self._check_dates(metadata, findings)
                self._check_gps(metadata, findings)
                self._check_device_fingerprint(metadata, findings)
                self._check_thumbnail_consistency(image_bytes, metadata, findings)
            else:
                # Missing EXIF is a stronger AI signal than the previous
                # 0.10 baseline implied. AI generators (SD, MJ, DALL-E,
                # Gemini, FLUX) consistently strip or omit EXIF, while
                # genuine camera/phone photos almost always retain at
                # least Make/Model/DateTimeOriginal. Production stats
                # show ~95% of AI samples have no EXIF vs ~12% of
                # authentic samples — bumping to 0.40 better reflects
                # this gap without making it a hard verdict driver.
                findings.append(
                    AnalyzerFinding(
                        code="META_NO_EXIF",
                        title="Nedostaju EXIF podaci",
                        description=(
                            "Slika ne sadrzi EXIF metapodatke. Moguce je da su "
                            "uklonjeni nakon obrade u programu za uredivanje slika "
                            "ili da je slika generirana AI alatima koji ne pisu EXIF."
                        ),
                        risk_score=0.40,
                        confidence=0.55,
                    )
                )

            # 3. C2PA provenance (runs independently of EXIF)
            self._check_c2pa(image_bytes, filename, findings)

        except Exception as e:
            logger.warning("Metadata analysis error: %s", e)
            elapsed = int((time.monotonic() - start) * 1000)
            return self._make_result([], elapsed, error=str(e))

        elapsed = int((time.monotonic() - start) * 1000)
        return self._make_result(findings, elapsed)

    async def analyze_document(self, doc_bytes: bytes, filename: str) -> ModuleResult:
        return self._make_result([], 0)

    # ------------------------------------------------------------------
    # Filename AI pattern detection
    # ------------------------------------------------------------------

    # AI generators produce distinctive filenames — high confidence signal
    _AI_FILENAME_PATTERNS: list[tuple[str, str]] = [
        ("gemini_generated_image", "Google Gemini"),
        ("gemini_generated", "Google Gemini"),
        ("image_fx_", "Google ImageFX"),
        ("dall-e", "DALL-E"),
        ("dall_e", "DALL-E"),
        ("dalle_", "DALL-E"),
        ("midjourney_", "Midjourney"),
        ("comfyui_", "ComfyUI"),
        ("sdxl_", "Stable Diffusion XL"),
        ("stable_diffusion", "Stable Diffusion"),
        ("novelai_", "NovelAI"),
    ]

    def _check_filename_ai_pattern(
        self, filename: str, findings: list[AnalyzerFinding]
    ) -> None:
        """Check if filename matches known AI generator naming conventions."""
        fn_lower = filename.lower()
        for pattern, generator in self._AI_FILENAME_PATTERNS:
            if pattern in fn_lower:
                findings.append(
                    AnalyzerFinding(
                        code="META_FILENAME_AI_GENERATOR",
                        title=f"Naziv datoteke ukazuje na AI generator: {generator}",
                        description=(
                            f"Naziv datoteke '{filename}' sadrzi obrazac "
                            f"karakteristican za {generator} AI generator. "
                            f"Ovo je snazna indikacija da je sadrzaj umjetno generiran."
                        ),
                        risk_score=0.85,
                        confidence=0.95,
                    )
                )
                return  # Only one filename finding needed

    # Magic byte / MIME type validation
    # ------------------------------------------------------------------

    def _check_magic_bytes(
        self, image_bytes: bytes, filename: str, findings: list[AnalyzerFinding]
    ) -> None:
        detected_mime = magic.from_buffer(image_bytes[:2048], mime=True)
        ext = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""

        if ext and ext in VALID_IMAGE_MIMES:
            expected_mimes = VALID_IMAGE_MIMES[ext]
            if detected_mime not in expected_mimes:
                findings.append(
                    AnalyzerFinding(
                        code="META_MIME_MISMATCH",
                        title="Nepodudarnost tipa datoteke",
                        description=(
                            f"Ekstenzija datoteke ({ext}) ne odgovara stvarnom "
                            f"sadrzaju ({detected_mime}). Datoteka je moguce preimenovana."
                        ),
                        risk_score=0.35,
                        confidence=0.95,
                        evidence={"extension": ext, "detected_mime": detected_mime},
                    )
                )

    # ------------------------------------------------------------------
    # PNG text chunk parsing (Stable Diffusion / ComfyUI / Auto1111 etc.)
    # ------------------------------------------------------------------
    #
    # PNG files have tEXt, zTXt, and iTXt chunks for storing arbitrary
    # text. AI generation tools heavily abuse these:
    #
    #   Auto1111 / Forge / Vladmandic:
    #     tEXt "parameters" → "<prompt>\nNegative prompt: <neg>\nSteps: 20,
    #         Sampler: Euler a, CFG scale: 7, Seed: 12345, Size: 512x512,
    #         Model hash: abcd, Model: anything-v3, ..."
    #
    #   ComfyUI:
    #     tEXt "prompt" → JSON of the prompt graph
    #     tEXt "workflow" → JSON of the full ComfyUI workflow
    #
    #   InvokeAI:
    #     tEXt "Dream" / tEXt "sd-metadata" / tEXt "invokeai_metadata"
    #
    #   NovelAI:
    #     tEXt "Software" → "NovelAI"
    #     tEXt "Comment" → JSON with prompt and steps
    #
    #   Diffusers (HuggingFace):
    #     tEXt "Software" → "Diffusers <version>"
    #
    # All of these are DEFINITIVE AI signals — no real camera or photo
    # editor produces these chunks.

    # Recognized PNG text chunk keys that indicate AI generation
    _PNG_AI_TEXT_KEYS: tuple[tuple[bytes, str, float], ...] = (
        # (chunk key, generator name, risk score)
        (b"parameters",        "Stable Diffusion (Auto1111/Forge)", 0.95),
        (b"prompt",            "ComfyUI / SD",                       0.95),
        (b"workflow",          "ComfyUI",                            0.95),
        (b"Dream",             "InvokeAI",                           0.95),
        (b"sd-metadata",       "InvokeAI (legacy)",                  0.95),
        (b"invokeai_metadata", "InvokeAI",                           0.95),
        (b"sd_metadata",       "Stable Diffusion",                   0.95),
        (b"NovelAI",           "NovelAI",                            0.95),
        (b"NAI Generated",     "NovelAI",                            0.95),
    )

    # Substrings inside PNG text chunk VALUES that indicate AI generation
    # (caught when the key itself is generic e.g. "Software" or "Comment")
    _PNG_AI_VALUE_PATTERNS: tuple[tuple[bytes, str, float], ...] = (
        (b"stable-diffusion",  "Stable Diffusion",  0.95),
        (b"stable diffusion",  "Stable Diffusion",  0.95),
        (b"stablediffusion",   "Stable Diffusion",  0.95),
        (b"automatic1111",     "Automatic1111",     0.95),
        (b"comfyui",           "ComfyUI",           0.95),
        (b"invokeai",          "InvokeAI",          0.95),
        (b"novelai",           "NovelAI",           0.95),
        (b"diffusers",         "HuggingFace Diffusers", 0.85),
        (b"flux.1",            "Flux.1",            0.95),
        (b"flux schnell",      "Flux.1 Schnell",    0.95),
        (b"flux dev",          "Flux.1 Dev",        0.95),
        (b"midjourney",        "Midjourney",        0.95),
        (b"dall-e",            "DALL-E",            0.95),
        (b"firefly",           "Adobe Firefly",     0.95),
        (b"adobe ai",          "Adobe AI",          0.85),
        (b"generative fill",   "Adobe Generative Fill", 0.85),
        (b"generative expand", "Adobe Generative Expand", 0.85),
    )

    def _check_png_text_chunks(
        self, image_bytes: bytes, findings: list[AnalyzerFinding]
    ) -> None:
        """Parse PNG tEXt/zTXt/iTXt chunks for AI generator markers.

        Reads the file structure directly so we don't depend on Pillow's
        chunk handling (which strips most text chunks on save).
        """
        # PNG signature: 8 bytes \x89PNG\r\n\x1a\n
        if len(image_bytes) < 8 or image_bytes[:8] != b"\x89PNG\r\n\x1a\n":
            return  # Not a PNG, nothing to do

        # Walk chunks: 4-byte length, 4-byte type, payload, 4-byte CRC
        offset = 8
        scanned_chunks = 0
        max_chunks = 200  # Defensive cap against malformed files
        try:
            while offset + 8 <= len(image_bytes) and scanned_chunks < max_chunks:
                length = int.from_bytes(image_bytes[offset:offset + 4], "big")
                chunk_type = image_bytes[offset + 4:offset + 8]
                payload_start = offset + 8
                payload_end = payload_start + length

                if payload_end + 4 > len(image_bytes):
                    break  # Truncated chunk

                if chunk_type in (b"tEXt", b"zTXt", b"iTXt"):
                    payload = image_bytes[payload_start:payload_end]
                    self._scan_png_text_payload(chunk_type, payload, findings)

                # IEND ends the file
                if chunk_type == b"IEND":
                    break

                offset = payload_end + 4  # +4 for CRC
                scanned_chunks += 1
        except Exception as e:
            logger.debug("PNG chunk walk aborted at offset=%d: %s", offset, e)

    def _scan_png_text_payload(
        self, chunk_type: bytes, payload: bytes, findings: list[AnalyzerFinding]
    ) -> None:
        """Inspect a single PNG text chunk payload for AI markers."""
        # tEXt: keyword \x00 text
        # zTXt: keyword \x00 compression_method (1 byte) compressed_text
        # iTXt: keyword \x00 compression_flag compression_method language \x00
        #       translated_keyword \x00 text (text may be UTF-8)
        if b"\x00" not in payload:
            return
        try:
            keyword, _, rest = payload.partition(b"\x00")
            if chunk_type == b"zTXt":
                if not rest:
                    return
                # rest = comp_method (1 byte) + zlib data
                import zlib
                try:
                    text = zlib.decompress(rest[1:])
                except Exception:
                    return
            elif chunk_type == b"iTXt":
                # rest = comp_flag(1) + comp_method(1) + lang \x00 trans_kw \x00 text
                if len(rest) < 4:
                    return
                comp_flag = rest[0]
                comp_method = rest[1]
                # Skip language and translated_keyword (each \x00-terminated)
                tail = rest[2:]
                _lang, _, tail = tail.partition(b"\x00")
                _trans, _, tail = tail.partition(b"\x00")
                text = tail
                if comp_flag == 1:
                    import zlib
                    try:
                        text = zlib.decompress(text)
                    except Exception:
                        return
            else:  # tEXt
                text = rest
        except Exception:
            return

        keyword_lower = keyword.lower()

        # 1) Check known AI keys (definitive, regardless of content)
        for ai_key, generator, risk in self._PNG_AI_TEXT_KEYS:
            if ai_key.lower() == keyword_lower:
                # Limit text snippet for evidence
                snippet = text[:300].decode("utf-8", errors="replace")
                findings.append(
                    AnalyzerFinding(
                        code="META_PNG_AI_PARAMS",
                        title=f"PNG metapodaci sadrze AI parametre: {generator}",
                        description=(
                            f"PNG datoteka sadrzi text chunk '{keyword.decode('latin-1', errors='replace')}' "
                            f"karakteristican za AI generator {generator}. "
                            f"Ovo je definitivni signal sintetickog sadrzaja."
                        ),
                        risk_score=risk,
                        confidence=0.99,
                        evidence={
                            "chunk_type": chunk_type.decode("ascii"),
                            "chunk_key": keyword.decode("latin-1", errors="replace"),
                            "generator": generator,
                            "snippet": snippet,
                        },
                    )
                )
                return  # Single finding per chunk is enough

        # 2) Generic key (e.g. "Software" / "Comment") — scan VALUE for markers
        text_lower = text.lower()[:8192]  # cap to avoid pathological scans
        for marker, generator, risk in self._PNG_AI_VALUE_PATTERNS:
            if marker in text_lower:
                snippet = text[:300].decode("utf-8", errors="replace")
                findings.append(
                    AnalyzerFinding(
                        code="META_PNG_AI_VALUE",
                        title=f"PNG metapodaci spominju AI generator: {generator}",
                        description=(
                            f"PNG text chunk '{keyword.decode('latin-1', errors='replace')}' "
                            f"sadrzi referencu na AI generator {generator}. "
                            f"Vrlo vjerojatno sinteticki sadrzaj."
                        ),
                        risk_score=risk,
                        confidence=0.95,
                        evidence={
                            "chunk_type": chunk_type.decode("ascii"),
                            "chunk_key": keyword.decode("latin-1", errors="replace"),
                            "generator": generator,
                            "snippet": snippet,
                        },
                    )
                )
                return

    # ------------------------------------------------------------------
    # Metadata extraction (ExifTool preferred, exifread fallback)
    # ------------------------------------------------------------------

    def _extract_metadata(
        self, image_bytes: bytes, filename: str
    ) -> dict[str, object] | None:
        """Extract all metadata tags. Returns flat dict or None if empty."""
        if _USE_EXIFTOOL:
            return self._extract_with_exiftool(image_bytes, filename)
        return self._extract_with_exifread(image_bytes)

    def _extract_with_exiftool(
        self, image_bytes: bytes, filename: str
    ) -> dict[str, object] | None:
        ext = os.path.splitext(filename)[1] if "." in filename else ".jpg"
        try:
            with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
                tmp.write(image_bytes)
                tmp_path = tmp.name

            with exiftool.ExifToolHelper() as et:
                metadata_list = et.get_metadata(tmp_path)

            os.unlink(tmp_path)

            if not metadata_list:
                return None
            meta = metadata_list[0]
            # ExifTool always includes SourceFile — if that's the only key, no real metadata
            if len(meta) <= 1:
                return None
            return meta
        except Exception as e:
            logger.warning("ExifTool extraction failed, trying exifread: %s", e)
            # Clean up temp file on error
            try:
                os.unlink(tmp_path)  # type: ignore[possibly-undefined]
            except Exception as e:
                logger.debug("Temp file cleanup after exiftool error: %s", e)
            return self._extract_with_exifread(image_bytes)

    def _extract_with_exifread(
        self, image_bytes: bytes
    ) -> dict[str, object] | None:
        if exifread is None:
            return None
        stream = io.BytesIO(image_bytes)
        tags = exifread.process_file(stream, details=False)
        if not tags:
            return None
        # Convert exifread IfdTag values to strings for uniform handling
        return {k: str(v) for k, v in tags.items()}

    # ------------------------------------------------------------------
    # Software tag detection
    # ------------------------------------------------------------------

    def _check_software_tags(
        self, metadata: dict[str, object], findings: list[AnalyzerFinding]
    ) -> None:
        tag_keys = SOFTWARE_EXIFTOOL_TAGS if _USE_EXIFTOOL else SOFTWARE_EXIFREAD_TAGS
        found_software: set[str] = set()

        for tag_name in tag_keys:
            tag_value = metadata.get(tag_name)
            if not tag_value:
                continue
            software_str = str(tag_value).lower()

            for keyword, risk, display_name in EDITING_SOFTWARE:
                if keyword in software_str and display_name not in found_software:
                    found_software.add(display_name)
                    findings.append(
                        AnalyzerFinding(
                            code="META_EDITING_SOFTWARE",
                            title="Otkriven softver za uredivanje",
                            description=(
                                f"Metapodaci sadrze oznaku softvera '{display_name}' "
                                f"({tag_name}: {tag_value}). Slika je moguce modificirana."
                            ),
                            risk_score=risk,
                            confidence=0.90,
                            evidence={
                                "tag": tag_name,
                                "value": str(tag_value),
                                "software": display_name,
                            },
                        )
                    )
                    break  # One match per tag

    # ------------------------------------------------------------------
    # XMP ProcessingHistory analysis
    # ------------------------------------------------------------------

    def _check_xmp_history(
        self, metadata: dict[str, object], findings: list[AnalyzerFinding]
    ) -> None:
        if not _USE_EXIFTOOL:
            # exifread doesn't extract XMP history
            return

        actions = metadata.get("XMP:HistoryAction")
        agents = metadata.get("XMP:HistorySoftwareAgent")

        # Check if XMP namespace exists but history is stripped
        has_xmp = any(k.startswith("XMP:") for k in metadata)
        if has_xmp and not actions and not agents:
            # XMP present but no history — possibly stripped
            # Only flag if there's a CreatorTool suggesting editing
            creator_tool = metadata.get("XMP:CreatorTool", "")
            if creator_tool and any(
                kw in str(creator_tool).lower()
                for kw, _, _ in EDITING_SOFTWARE
                if kw not in ("lightroom", "snapseed")  # Common non-suspicious tools
            ):
                findings.append(
                    AnalyzerFinding(
                        code="META_XMP_HISTORY_STRIPPED",
                        title="Uklonjena XMP povijest izmjena",
                        description=(
                            f"XMP metapodaci postoje (CreatorTool: {creator_tool}) "
                            "ali ne sadrze povijest izmjena. Povijest je moguce "
                            "namjerno uklonjena."
                        ),
                        risk_score=0.15,
                        confidence=0.50,
                        evidence={"creator_tool": str(creator_tool)},
                    )
                )
            return

        if not actions:
            return

        # ExifTool returns lists for multi-value tags
        action_list = actions if isinstance(actions, list) else [actions]
        agent_list = (
            agents if isinstance(agents, list) else [agents] if agents else []
        )

        # Count save operations and detect specific tools
        save_count = sum(
            1 for a in action_list if str(a).lower() in ("saved", "converted", "derived")
        )
        ai_tools_found: list[str] = []
        photoshop_saves = 0

        for agent in agent_list:
            agent_str = str(agent).lower()
            for keyword, _, display_name in EDITING_SOFTWARE:
                if keyword in agent_str:
                    if keyword in (
                        "dall-e", "dall·e", "midjourney", "stable diffusion",
                        "comfyui", "automatic1111", "invoke ai", "novelai",
                        "adobe firefly", "runway",
                    ):
                        ai_tools_found.append(display_name)
                    if "photoshop" in agent_str:
                        photoshop_saves += 1
                    break

        # AI tool in history
        if ai_tools_found:
            findings.append(
                AnalyzerFinding(
                    code="META_XMP_AI_TOOL_HISTORY",
                    title="AI alat u povijesti izmjena",
                    description=(
                        f"XMP povijest sadrzi AI alat: {', '.join(set(ai_tools_found))}. "
                        "Slika je moguce generirana ili znacajno modificirana umjetnom inteligencijom."
                    ),
                    risk_score=0.50,
                    confidence=0.85,
                    evidence={
                        "ai_tools": list(set(ai_tools_found)),
                        "total_actions": len(action_list),
                    },
                )
            )

        # Multiple Photoshop save iterations
        elif photoshop_saves >= 3:
            findings.append(
                AnalyzerFinding(
                    code="META_XMP_EDIT_HISTORY",
                    title="Visestruke izmjene u Photoshopu",
                    description=(
                        f"XMP povijest sadrzi {photoshop_saves} Photoshop spremanja, "
                        f"ukupno {save_count} akcija. Slika je prosla kroz "
                        "vise iteracija uredivanja."
                    ),
                    risk_score=0.20,
                    confidence=0.75,
                    evidence={
                        "photoshop_saves": photoshop_saves,
                        "total_actions": len(action_list),
                    },
                )
            )

        # Many save operations (generic)
        elif save_count >= 5:
            findings.append(
                AnalyzerFinding(
                    code="META_XMP_EDIT_HISTORY",
                    title="Opsezna povijest izmjena",
                    description=(
                        f"XMP povijest sadrzi {save_count} operacija spremanja. "
                        "Slika je prosla kroz vise sesija uredivanja."
                    ),
                    risk_score=0.15,
                    confidence=0.60,
                    evidence={
                        "save_count": save_count,
                        "total_actions": len(action_list),
                        "agents": [str(a) for a in agent_list[:5]],
                    },
                )
            )

    # ------------------------------------------------------------------
    # Date consistency / temporal verification
    # ------------------------------------------------------------------

    def _check_dates(
        self, metadata: dict[str, object], findings: list[AnalyzerFinding]
    ) -> None:
        tag_map = DATE_EXIFTOOL_TAGS if _USE_EXIFTOOL else DATE_EXIFREAD_TAGS
        dates: dict[str, str] = {}

        for tag_name, label in tag_map.items():
            val = metadata.get(tag_name)
            if val:
                dates[label] = str(val).strip()

        if not dates:
            return

        # Parse dates for comparison
        parsed: dict[str, datetime] = {}
        for label, date_str in dates.items():
            dt = self._parse_exif_date(date_str)
            if dt:
                parsed[label] = dt

        # Check: ModifyDate before DateTimeOriginal
        original_dt = parsed.get("original")
        modified_dt = parsed.get("modified")
        if original_dt and modified_dt and modified_dt < original_dt:
            findings.append(
                AnalyzerFinding(
                    code="META_DATE_INCONSISTENCY",
                    title="Nedosljednost datuma",
                    description=(
                        f"Datum izmjene ({dates.get('modified', '?')}) je raniji od "
                        f"datuma izvornog snimanja ({dates.get('original', '?')}). "
                        "EXIF podaci su moguce rucno modificirani."
                    ),
                    risk_score=0.30,
                    confidence=0.85,
                    evidence=dates,
                )
            )

        # Check: CreateDate != DateTimeOriginal (>1 second gap)
        create_dt = parsed.get("create")
        if original_dt and create_dt:
            diff = abs((create_dt - original_dt).total_seconds())
            if diff > 1:
                findings.append(
                    AnalyzerFinding(
                        code="META_DATE_INCONSISTENCY",
                        title="Razlika izmedju CreateDate i DateTimeOriginal",
                        description=(
                            f"CreateDate ({dates.get('create', '?')}) razlikuje se od "
                            f"DateTimeOriginal ({dates.get('original', '?')}) za "
                            f"{int(diff)} sekundi. Podaci su moguce rucno postavljeni."
                        ),
                        risk_score=0.15,
                        confidence=0.60,
                        evidence=dates,
                    )
                )

        # Check: XMP MetadataDate significantly after EXIF dates
        xmp_meta_dt = parsed.get("xmp_metadata")
        ref_dt = original_dt or modified_dt
        if xmp_meta_dt and ref_dt:
            gap_hours = (xmp_meta_dt - ref_dt).total_seconds() / 3600
            if gap_hours > 24:
                findings.append(
                    AnalyzerFinding(
                        code="META_DATE_INCONSISTENCY",
                        title="XMP MetadataDate kasni za EXIF datumima",
                        description=(
                            f"XMP MetadataDate ({dates.get('xmp_metadata', '?')}) je "
                            f"{int(gap_hours)} sati nakon EXIF datuma. "
                            "Metapodaci su moguce naknadno modificirani."
                        ),
                        risk_score=0.10,
                        confidence=0.50,
                        evidence=dates,
                    )
                )

        # Check: future date
        now = datetime.now(timezone.utc)
        for label, dt in parsed.items():
            # Make naive datetimes UTC-aware for comparison
            dt_aware = dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt
            if dt_aware > now:
                findings.append(
                    AnalyzerFinding(
                        code="META_FUTURE_DATE",
                        title="Datum u buducnosti",
                        description=(
                            f"Metapodatak '{label}' ({dates.get(label, '?')}) sadrzi "
                            "datum u buducnosti. EXIF podaci su gotovo sigurno "
                            "rucno modificirani."
                        ),
                        risk_score=0.40,
                        confidence=0.90,
                        evidence={"field": label, "value": dates.get(label, "")},
                    )
                )
                break  # One future-date finding is enough

    @staticmethod
    def _parse_exif_date(date_str: str) -> datetime | None:
        """Parse common EXIF date formats."""
        date_str = date_str.strip()
        for fmt in (
            _EXIF_DATE_FMT,
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%dT%H:%M:%S%z",
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%d %H:%M:%S%z",
            "%Y:%m:%d %H:%M:%S%z",
        ):
            try:
                return datetime.strptime(date_str[:26], fmt)
            except (ValueError, IndexError):
                continue
        return None

    # ------------------------------------------------------------------
    # GPS coordinate plausibility
    # ------------------------------------------------------------------

    def _check_gps(
        self, metadata: dict[str, object], findings: list[AnalyzerFinding]
    ) -> None:
        lat = self._extract_gps_coord(metadata, "Latitude")
        lon = self._extract_gps_coord(metadata, "Longitude")

        if lat is None or lon is None:
            return

        evidence = {"latitude": lat, "longitude": lon}

        # Altitude check
        alt = self._extract_gps_altitude(metadata)
        if alt is not None:
            evidence["altitude"] = alt

        # Invalid range
        if not (-90 <= lat <= 90) or not (-180 <= lon <= 180):
            findings.append(
                AnalyzerFinding(
                    code="META_GPS_INVALID",
                    title="Nevazece GPS koordinate",
                    description=(
                        f"GPS koordinate ({lat:.6f}, {lon:.6f}) su izvan "
                        "dozvoljenog raspona. Podaci su moguce fabricirani."
                    ),
                    risk_score=0.25,
                    confidence=0.95,
                    evidence=evidence,
                )
            )
            return

        # Null Island (0, 0) — common sign of zeroed/fake GPS
        if abs(lat) < 0.01 and abs(lon) < 0.01:
            findings.append(
                AnalyzerFinding(
                    code="META_GPS_NULL_ISLAND",
                    title="GPS koordinate na 'Null Island' (0, 0)",
                    description=(
                        "GPS koordinate ukazuju na lokaciju (0, 0) u Atlantskom "
                        "oceanu ('Null Island'). Ovo je cest artefakt laznih ili "
                        "neinicijaliziranih GPS podataka."
                    ),
                    risk_score=0.20,
                    confidence=0.80,
                    evidence=evidence,
                )
            )

        # Implausible altitude
        if alt is not None and (alt < -500 or alt > 9000):
            findings.append(
                AnalyzerFinding(
                    code="META_GPS_ALTITUDE_IMPLAUSIBLE",
                    title="Neuvjerljiva GPS visina",
                    description=(
                        f"GPS visina ({alt:.0f}m) je izvan uvjerljivog raspona "
                        "(-500m do 9000m). Podaci su moguce modificirani."
                    ),
                    risk_score=0.10,
                    confidence=0.70,
                    evidence=evidence,
                )
            )

    def _extract_gps_coord(
        self, metadata: dict[str, object], coord_type: str
    ) -> float | None:
        """Extract GPS latitude or longitude as decimal degrees."""
        if _USE_EXIFTOOL:
            # ExifTool returns decimal degrees directly
            val = metadata.get(f"EXIF:GPS{coord_type}")
            if val is None:
                val = metadata.get(f"Composite:GPS{coord_type}")
            if val is None:
                val = metadata.get(f"XMP:GPS{coord_type}")
            if val is not None:
                try:
                    return float(val)
                except (TypeError, ValueError):
                    return None
        else:
            # exifread: need to parse GPS DMS format with ref
            tag = f"GPS GPS{coord_type}"
            ref_tag = f"GPS GPS{coord_type}Ref"
            val = metadata.get(tag)
            ref = metadata.get(ref_tag)
            if val and ref:
                return self._dms_to_decimal(str(val), str(ref))
        return None

    def _extract_gps_altitude(self, metadata: dict[str, object]) -> float | None:
        if _USE_EXIFTOOL:
            alt = metadata.get("EXIF:GPSAltitude")
            if alt is not None:
                try:
                    val = float(alt)
                    ref = metadata.get("EXIF:GPSAltitudeRef")
                    if ref is not None and str(ref).strip() == "1":
                        val = -val
                    return val
                except (TypeError, ValueError):
                    return None
        return None

    @staticmethod
    def _dms_to_decimal(dms_str: str, ref: str) -> float | None:
        """Convert EXIF DMS string like '[48, 51, 24]' to decimal degrees."""
        try:
            # Strip brackets and split
            parts = dms_str.strip("[]() ").replace(",", " ").split()
            # Handle fraction strings like '24/1'
            nums: list[float] = []
            for p in parts:
                p = p.strip()
                if not p:
                    continue
                if "/" in p:
                    num, den = p.split("/")
                    nums.append(float(num) / float(den))
                else:
                    nums.append(float(p))
            if len(nums) < 2:
                return None
            degrees = nums[0]
            minutes = nums[1] if len(nums) > 1 else 0.0
            seconds = nums[2] if len(nums) > 2 else 0.0
            decimal = degrees + minutes / 60 + seconds / 3600
            if ref.strip().upper() in ("S", "W"):
                decimal = -decimal
            return decimal
        except (ValueError, IndexError, ZeroDivisionError):
            return None

    # ------------------------------------------------------------------
    # Device fingerprint consistency
    # ------------------------------------------------------------------

    def _check_device_fingerprint(
        self, metadata: dict[str, object], findings: list[AnalyzerFinding]
    ) -> None:
        if _USE_EXIFTOOL:
            make = str(metadata.get("EXIF:Make", "")).strip()
            model = str(metadata.get("EXIF:Model", "")).strip()
            software = str(metadata.get("EXIF:Software", "")).strip()
        else:
            make = str(metadata.get("Image Make", "")).strip()
            model = str(metadata.get("Image Model", "")).strip()
            software = str(metadata.get("Image Software", "")).strip()

        has_other_exif = len(metadata) > 3  # More than just SourceFile + a couple tags

        # Device info completely stripped but other EXIF present.
        #
        # Production audit (2026-04-07): this is the finding that actually
        # fires on car4.webp / car5.jpg / Gemini outputs. The earlier
        # META_NO_EXIF bump (0.10 → 0.40) targeted the WRONG path —
        # META_NO_EXIF only fires when ExifTool returns absolutely nothing,
        # which is rare. Real AI generators leave JFIF/RIFF/file-system
        # tags in place but strip device info.
        #
        # In real-world production, phone uploads carry full EXIF
        # (Make/Model/DateTimeOriginal) so this finding doesn't fire.
        # When it DOES fire, it almost always means either:
        #   (a) the image is AI-generated and the generator left a format
        #       header but no device info (Gemini, FLUX, DALL-E 3, Sora,
        #       Midjourney v6/v7), or
        #   (b) the image was deliberately laundered through a metadata
        #       stripper, which is itself a strong tampering signal.
        # Both cases warrant a stronger score than the legacy 0.10.
        #
        # 0.30 chosen so the finding contributes meaningfully to the
        # metadata pillar while staying below the META_NO_EXIF 0.40
        # ceiling (the "completely wiped" case is still stronger).
        if not make and not model and has_other_exif:
            findings.append(
                AnalyzerFinding(
                    code="META_DEVICE_STRIPPED",
                    title="Uklonjeni podaci o uredaju",
                    description=(
                        "Slika sadrzi EXIF metapodatke ali nema informacija o "
                        "uredaju (Make/Model). Podaci o uredaju su moguce "
                        "namjerno uklonjeni ili je slika generirana AI alatima "
                        "koji ne pisu device fingerprint."
                    ),
                    risk_score=0.30,
                    confidence=0.55,
                    evidence={"tags_count": len(metadata)},
                )
            )
            return

        if not make or not software:
            return

        make_lower = make.lower()
        software_lower = software.lower()

        # Check: camera/phone Make present but Software is a desktop editing tool
        is_camera_device = any(
            brand in make_lower
            for brand in (
                "apple", "samsung", "google", "huawei", "xiaomi", "oppo",
                "vivo", "oneplus", "sony", "canon", "nikon", "fujifilm",
                "panasonic", "olympus", "leica",
            )
        )
        is_editing_software = any(
            kw in software_lower
            for kw, risk, _ in EDITING_SOFTWARE
            if risk >= 0.20  # Only flag high-risk editors, not Lightroom/Snapseed
        )

        if is_camera_device and is_editing_software:
            findings.append(
                AnalyzerFinding(
                    code="META_DEVICE_SOFTWARE_MISMATCH",
                    title="Nepodudarnost uredaja i softvera",
                    description=(
                        f"Uredaj '{make} {model}' ima softver '{software}' koji "
                        "upucuje na desktop program za uredivanje. Slika je "
                        "snimljena kamerom ali naknadno modificirana."
                    ),
                    risk_score=0.20,
                    confidence=0.75,
                    evidence={
                        "make": make,
                        "model": model,
                        "software": software,
                    },
                )
            )

    # ------------------------------------------------------------------
    # Thumbnail vs main image consistency
    # ------------------------------------------------------------------

    def _check_thumbnail_consistency(
        self,
        image_bytes: bytes,
        metadata: dict[str, object],
        findings: list[AnalyzerFinding],
    ) -> None:
        thumb_bytes = self._extract_thumbnail(image_bytes, metadata)

        # Determine if this is a camera image (has Make/Model/DateTimeOriginal)
        if _USE_EXIFTOOL:
            has_camera_exif = bool(
                metadata.get("EXIF:Make") and metadata.get("EXIF:DateTimeOriginal")
            )
        else:
            has_camera_exif = bool(
                metadata.get("Image Make") and metadata.get("EXIF DateTimeOriginal")
            )

        if thumb_bytes is None:
            # No thumbnail — flag only if camera photo > 100KB
            if len(image_bytes) > 100_000 and has_camera_exif:
                findings.append(
                    AnalyzerFinding(
                        code="META_NO_THUMBNAIL",
                        title="Nedostaje minijatura",
                        description=(
                            "Slika sadrzi EXIF podatke kamere ali nema ugradenu "
                            "minijaturu. Moguce je da je slika ponovo spremljena "
                            "kroz softver koji uklanja minijature."
                        ),
                        risk_score=0.08,
                        confidence=0.30,
                    )
                )
            return

        # Compare thumbnail to main image via histogram correlation
        try:
            correlation = self._compare_thumbnail(image_bytes, thumb_bytes)
            if correlation is None:
                return

            if correlation < 0.70:
                findings.append(
                    AnalyzerFinding(
                        code="META_THUMBNAIL_MISMATCH",
                        title="Minijatura ne odgovara slici",
                        description=(
                            f"Ugradena minijatura ima nisku korelaciju ({correlation:.0%}) "
                            "sa glavnom slikom. Ovo je jak pokazatelj da je slika "
                            "modificirana nakon izvornog snimanja, dok je stara "
                            "minijatura zadrzana."
                        ),
                        risk_score=0.35,
                        confidence=0.80,
                        evidence={"correlation": round(correlation, 4)},
                    )
                )
            elif correlation < 0.85:
                findings.append(
                    AnalyzerFinding(
                        code="META_THUMBNAIL_MISMATCH",
                        title="Sumnjiva razlika minijature i slike",
                        description=(
                            f"Ugradena minijatura ima srednju korelaciju ({correlation:.0%}) "
                            "sa glavnom slikom. Moguce je da je slika djelomicno "
                            "modificirana."
                        ),
                        risk_score=0.15,
                        confidence=0.60,
                        evidence={"correlation": round(correlation, 4)},
                    )
                )
        except Exception as e:
            logger.debug("Thumbnail comparison failed: %s", e)

    def _extract_thumbnail(
        self, image_bytes: bytes, metadata: dict[str, object]
    ) -> bytes | None:
        """Extract embedded JPEG thumbnail bytes."""
        if _USE_EXIFTOOL:
            # Use ExifTool to extract binary thumbnail
            ext = ".jpg"
            try:
                with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
                    tmp.write(image_bytes)
                    tmp_path = tmp.name

                with exiftool.ExifToolHelper() as et:
                    # Get ThumbnailImage tag as binary
                    result = et.execute(
                        "-b", "-ThumbnailImage", tmp_path
                    )
                os.unlink(tmp_path)

                if result and len(result) > 100:
                    # ExifTool returns raw bytes
                    if isinstance(result, str):
                        return result.encode("latin-1")
                    return result
                return None
            except Exception as e:
                logger.debug("ExifTool thumbnail extraction failed: %s", e)
                try:
                    os.unlink(tmp_path)  # type: ignore[possibly-undefined]
                except Exception as e:
                    logger.debug("Temp file cleanup after thumbnail error: %s", e)
                return None
        else:
            # exifread stores thumbnail bytes directly
            if not isinstance(metadata, dict):
                return None
            thumb = metadata.get("JPEGThumbnail") or metadata.get("TIFFThumbnail")
            if thumb and isinstance(thumb, (bytes, bytearray)):
                return bytes(thumb)
            return None

    @staticmethod
    def _compare_thumbnail(
        image_bytes: bytes, thumb_bytes: bytes
    ) -> float | None:
        """Compare main image and thumbnail via normalized histogram correlation."""
        try:
            main_img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
            thumb_img = Image.open(io.BytesIO(thumb_bytes)).convert("RGB")

            # Resize main to thumbnail size for fair comparison
            thumb_size = thumb_img.size
            if thumb_size[0] < 10 or thumb_size[1] < 10:
                return None

            main_resized = main_img.resize(thumb_size, Image.Resampling.LANCZOS)

            # Compute per-channel histograms and correlate
            correlations: list[float] = []
            for channel in range(3):
                main_hist = np.array(
                    main_resized.split()[channel].histogram(), dtype=np.float64
                )
                thumb_hist = np.array(
                    thumb_img.split()[channel].histogram(), dtype=np.float64
                )

                # Normalize
                main_hist /= main_hist.sum() + 1e-10
                thumb_hist /= thumb_hist.sum() + 1e-10

                # Correlation coefficient
                corr = np.corrcoef(main_hist, thumb_hist)[0, 1]
                correlations.append(float(corr))

            return sum(correlations) / len(correlations)
        except Exception as e:
            logger.debug("Histogram comparison error: %s", e)
            return None

    # ------------------------------------------------------------------
    # C2PA cryptographic provenance validation
    # ------------------------------------------------------------------

    def _check_c2pa(
        self,
        image_bytes: bytes,
        filename: str,
        findings: list[AnalyzerFinding],
    ) -> None:
        if not _C2PA_AVAILABLE or not settings.forensics_c2pa_enabled:
            return

        # c2pa needs a file path
        ext = os.path.splitext(filename)[1] if "." in filename else ".jpg"
        tmp_path: str | None = None
        try:
            with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
                tmp.write(image_bytes)
                tmp_path = tmp.name

            reader = c2pa.Reader.from_file(tmp_path)

            if reader is None:
                # No C2PA manifest — neutral, most images don't have one
                return

            # Manifest found — analyze it
            manifest_store = reader.get_manifest_store()

            if manifest_store is None:
                return

            active_manifest = manifest_store.get("active_manifest")
            manifests = manifest_store.get("manifests", {})

            if not active_manifest or active_manifest not in manifests:
                return

            manifest = manifests[active_manifest]

            # Check validation status
            validation_status = manifest_store.get("validation_status", [])
            has_errors = any(
                s.get("code", "").startswith("assertion")
                or s.get("code", "").startswith("signing")
                for s in validation_status
                if isinstance(s, dict)
            )

            if has_errors:
                findings.append(
                    AnalyzerFinding(
                        code="META_C2PA_INVALID_SIGNATURE",
                        title="Nevaljan C2PA potpis",
                        description=(
                            "Slika sadrzi C2PA manifest ali je kriptografski potpis "
                            "nevaljan. Slika je moguce modificirana nakon potpisivanja."
                        ),
                        risk_score=0.35,
                        confidence=0.90,
                        evidence={
                            "validation_errors": [
                                s.get("code", "") for s in validation_status
                                if isinstance(s, dict)
                            ][:5]
                        },
                    )
                )
                return

            # Check for AI generation claims
            assertions = manifest.get("assertions", [])
            ai_actions = []
            for assertion in assertions:
                label = assertion.get("label", "")
                data = assertion.get("data", {})

                if label == "c2pa.actions":
                    actions = data.get("actions", [])
                    for action in actions:
                        action_type = action.get("action", "")
                        if action_type in (
                            "c2pa.ai_generated",
                            "c2pa.ai_training",
                            "c2pa.created",
                        ):
                            software = action.get("softwareAgent", {})
                            ai_actions.append(
                                software.get("name", action_type)
                                if isinstance(software, dict)
                                else action_type
                            )

            if ai_actions:
                # 2026-04-07: bumped 0.40 → 0.95. C2PA AI assertion is a
                # cryptographically signed claim by the generator that the
                # image is AI-created. There is no scenario where this is
                # a false positive on real photos — it's a definitive signal.
                findings.append(
                    AnalyzerFinding(
                        code="META_C2PA_AI_GENERATED",
                        title="C2PA oznaka AI generiranog sadrzaja",
                        description=(
                            f"C2PA manifest oznacava sliku kao AI-generirani sadrzaj "
                            f"({', '.join(ai_actions)}). Slika nije fotografija "
                            "stvarnog dogadaja."
                        ),
                        risk_score=0.95,
                        confidence=0.99,
                        evidence={"ai_actions": ai_actions},
                    )
                )
                return

            # Valid C2PA with no AI flags — risk reduction (trustworthy provenance)
            claim_generator = manifest.get("claim_generator", "")
            signature_info = manifest.get("signature_info", {})
            issuer = (
                signature_info.get("issuer", "")
                if isinstance(signature_info, dict)
                else ""
            )

            findings.append(
                AnalyzerFinding(
                    code="META_C2PA_VALID",
                    title="Valjan C2PA certifikat provenijencije",
                    description=(
                        "Slika sadrzi valjan C2PA manifest s kriptografskim "
                        f"potpisom (izdavac: {issuer or 'nepoznat'}). "
                        "Ovo povecava povjerenje u autenticnost slike."
                    ),
                    risk_score=-0.10,  # Negative = risk reduction
                    confidence=0.95,
                    evidence={
                        "claim_generator": claim_generator,
                        "issuer": issuer,
                    },
                )
            )

        except Exception as e:
            # C2PA parsing failure — not an error, just can't validate
            logger.debug("C2PA validation skipped: %s", e)
        finally:
            if tmp_path:
                try:
                    os.unlink(tmp_path)
                except Exception as e:
                    logger.debug("Temp file cleanup after C2PA check: %s", e)
