"""Office document forensics: DOCX/XLSX structure, VBA, hidden content analysis."""

import io
import logging
import re
import time
import zipfile
from xml.etree import ElementTree as ET

from ..base import AnalyzerFinding, BaseAnalyzer, ModuleResult

logger = logging.getLogger(__name__)

# Graceful degradation for oletools (VBA detection)
_OLETOOLS_AVAILABLE = False
try:
    from oletools.olevba import VBA_Parser, detect_autoexec

    _OLETOOLS_AVAILABLE = True
except ImportError:
    logger.info("oletools not installed, VBA macro detection disabled")

# Office XML namespaces
NS_CORE = "http://schemas.openxmlformats.org/package/2006/metadata/core-properties"
NS_DC = "http://purl.org/dc/elements/1.1/"
NS_DCTERMS = "http://purl.org/dc/terms/"
NS_CP = "http://schemas.openxmlformats.org/officeDocument/2006/extended-properties"
NS_REL = "http://schemas.openxmlformats.org/package/2006/relationships"
NS_SHEET = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
NS_WP = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"

# Suspicious file extensions that should never appear in normal Office documents
DANGEROUS_EXTENSIONS = {
    ".exe", ".bat", ".cmd", ".com", ".scr", ".pif", ".vbs",
    ".js", ".jse", ".wsf", ".wsh", ".ps1", ".psm1",
    ".dll", ".sys", ".drv", ".msi", ".jar",
}


class OfficeForensicsAnalyzer(BaseAnalyzer):
    MODULE_NAME = "office_forensics"
    MODULE_LABEL = "Office dokument forenzika"

    # ------------------------------------------------------------------
    # 1. Structural Analysis
    # ------------------------------------------------------------------

    def _check_structure(
        self, zf: zipfile.ZipFile, filename: str, findings: list[AnalyzerFinding]
    ) -> str:
        """Validate OOXML structure and detect suspicious embedded files.

        Returns: "docx" or "xlsx" based on detected type.
        """
        names = set(zf.namelist())
        doc_type = "unknown"

        # Determine document type
        if any(n.startswith("word/") for n in names):
            doc_type = "docx"
        elif any(n.startswith("xl/") for n in names):
            doc_type = "xlsx"

        # Check for required OOXML structure files
        if "[Content_Types].xml" not in names:
            findings.append(
                AnalyzerFinding(
                    code="OFFICE_MISSING_CONTENT_TYPES",
                    title="Nevalidna OOXML struktura",
                    description="Dokument nema [Content_Types].xml datoteku koja je obavezna za OOXML format.",
                    risk_score=0.40,
                    confidence=0.80,
                    evidence={"files_count": len(names)},
                )
            )

        # Detect dangerous embedded files
        dangerous_files = []
        for name in names:
            ext = "." + name.rsplit(".", 1)[-1].lower() if "." in name else ""
            if ext in DANGEROUS_EXTENSIONS:
                dangerous_files.append(name)

        if dangerous_files:
            findings.append(
                AnalyzerFinding(
                    code="OFFICE_DANGEROUS_EMBED",
                    title="Sumnjive ugradene datoteke",
                    description=(
                        f"Dokument sadrzi {len(dangerous_files)} potencijalno opasnih "
                        f"ugradenih datoteka: {', '.join(dangerous_files[:5])}."
                    ),
                    risk_score=0.75,
                    confidence=0.90,
                    evidence={"dangerous_files": dangerous_files[:10]},
                )
            )

        return doc_type

    # ------------------------------------------------------------------
    # 2. VBA Macro Detection
    # ------------------------------------------------------------------

    def _check_vba_macros(
        self, doc_bytes: bytes, zf: zipfile.ZipFile, findings: list[AnalyzerFinding]
    ) -> None:
        """Detect VBA macro projects and auto-exec macros."""
        # Quick check: look for vbaProject.bin in the ZIP
        has_vba_bin = any("vbaProject.bin" in n for n in zf.namelist())

        if not has_vba_bin:
            return  # No macros — clean

        if not _OLETOOLS_AVAILABLE:
            # Can't analyze macros in detail, but flag presence
            findings.append(
                AnalyzerFinding(
                    code="OFFICE_VBA_PRESENT",
                    title="VBA makro projekt detektiran",
                    description="Dokument sadrzi VBA makro projekt (vbaProject.bin). Detaljna analiza nije dostupna.",
                    risk_score=0.45,
                    confidence=0.80,
                    evidence={"vba_bin_present": True},
                )
            )
            return

        try:
            vba_parser = VBA_Parser(filename="doc", data=doc_bytes)
            if not vba_parser.detect_vba_macros():
                return

            # Extract macro info
            macro_count = 0
            auto_exec_macros = []
            suspicious_keywords = []

            for vba_type, _, _, vba_code in vba_parser.extract_macros():
                macro_count += 1
                # Check for auto-exec patterns
                auto_results = detect_autoexec(vba_code)
                if auto_results:
                    auto_exec_macros.extend([r[0] for r in auto_results])

                # Check for suspicious patterns
                for pattern in ["Shell", "WScript", "CreateObject", "PowerShell",
                                "cmd.exe", "Environ", "Kill", "Open.*Binary"]:
                    if re.search(pattern, vba_code, re.IGNORECASE):
                        suspicious_keywords.append(pattern)

            vba_parser.close()

            evidence = {
                "macro_count": macro_count,
                "auto_exec": list(set(auto_exec_macros))[:10],
                "suspicious_keywords": list(set(suspicious_keywords))[:10],
            }

            if auto_exec_macros:
                findings.append(
                    AnalyzerFinding(
                        code="OFFICE_VBA_AUTOEXEC",
                        title="Auto-izvrsni VBA makro",
                        description=(
                            f"Detektirano {macro_count} VBA makroa s auto-izvrsnim funkcijama: "
                            f"{', '.join(set(auto_exec_macros)[:5])}. Auto-exec makroi se pokrecu "
                            f"automatski pri otvaranju dokumenta."
                        ),
                        risk_score=0.70,
                        confidence=0.85,
                        evidence=evidence,
                    )
                )
            else:
                findings.append(
                    AnalyzerFinding(
                        code="OFFICE_VBA_PRESENT",
                        title="VBA makro projekt detektiran",
                        description=f"Dokument sadrzi {macro_count} VBA makroa bez auto-exec funkcija.",
                        risk_score=0.45,
                        confidence=0.80,
                        evidence=evidence,
                    )
                )

            if suspicious_keywords:
                findings.append(
                    AnalyzerFinding(
                        code="OFFICE_VBA_SUSPICIOUS",
                        title="Sumnjive VBA naredbe",
                        description=(
                            f"VBA kod sadrzi sumnjive kljucne rijeci: "
                            f"{', '.join(set(suspicious_keywords)[:5])}."
                        ),
                        risk_score=0.60,
                        confidence=0.75,
                        evidence=evidence,
                    )
                )

        except Exception as e:
            logger.debug("VBA analysis failed: %s", e)

    # ------------------------------------------------------------------
    # 3. Hidden Content Detection (XLSX)
    # ------------------------------------------------------------------

    def _check_hidden_content(
        self, zf: zipfile.ZipFile, doc_type: str, findings: list[AnalyzerFinding]
    ) -> None:
        """Detect hidden/veryHidden sheets in XLSX files."""
        if doc_type != "xlsx":
            return

        try:
            workbook_xml = zf.read("xl/workbook.xml")
            root = ET.fromstring(workbook_xml)
        except (KeyError, ET.ParseError) as e:
            logger.debug("Could not parse workbook.xml: %s", e)
            return

        hidden_sheets = []
        very_hidden_sheets = []

        for sheet in root.iter(f"{{{NS_SHEET}}}sheet"):
            name = sheet.get("name", "")
            state = sheet.get("state", "visible")

            if state == "hidden":
                hidden_sheets.append(name)
            elif state == "veryHidden":
                very_hidden_sheets.append(name)

        evidence = {
            "hidden_sheets": hidden_sheets,
            "very_hidden_sheets": very_hidden_sheets,
        }

        if very_hidden_sheets:
            findings.append(
                AnalyzerFinding(
                    code="OFFICE_VERY_HIDDEN_SHEET",
                    title="Vrlo skriveni listovi u tablici",
                    description=(
                        f"Tablica sadrzi {len(very_hidden_sheets)} 'veryHidden' listova "
                        f"({', '.join(very_hidden_sheets[:5])}). Ovi listovi su nevidljivi "
                        f"korisnicima i zahtijevaju VBA ili editor za pristup."
                    ),
                    risk_score=0.55,
                    confidence=0.85,
                    evidence=evidence,
                )
            )

        if hidden_sheets:
            findings.append(
                AnalyzerFinding(
                    code="OFFICE_HIDDEN_SHEET",
                    title="Skriveni listovi u tablici",
                    description=(
                        f"Tablica sadrzi {len(hidden_sheets)} skrivenih listova "
                        f"({', '.join(hidden_sheets[:5])})."
                    ),
                    risk_score=0.35,
                    confidence=0.80,
                    evidence=evidence,
                )
            )

    # ------------------------------------------------------------------
    # 4. Metadata Asymmetry
    # ------------------------------------------------------------------

    def _check_metadata(
        self, zf: zipfile.ZipFile, findings: list[AnalyzerFinding]
    ) -> None:
        """Analyze Office metadata for inconsistencies."""
        core_props = {}
        app_props = {}

        # Parse core.xml (dc:creator, dcterms:created, etc.)
        try:
            core_xml = zf.read("docProps/core.xml")
            core_root = ET.fromstring(core_xml)

            for tag, ns in [
                ("creator", NS_DC),
                ("lastModifiedBy", NS_CP),
                ("created", NS_DCTERMS),
                ("modified", NS_DCTERMS),
            ]:
                el = core_root.find(f"{{{ns}}}{tag}")
                if el is not None and el.text:
                    core_props[tag] = el.text.strip()
        except (KeyError, ET.ParseError):
            pass

        # Parse app.xml (Application, AppVersion, Template)
        try:
            app_xml = zf.read("docProps/app.xml")
            app_root = ET.fromstring(app_xml)

            for tag in ["Application", "AppVersion", "Template", "TotalTime"]:
                el = app_root.find(f"{{{NS_CP}}}{tag}")
                if el is not None and el.text:
                    app_props[tag] = el.text.strip()
        except (KeyError, ET.ParseError):
            pass

        evidence = {"core": core_props, "app": app_props}

        # Creator vs LastModifiedBy mismatch
        creator = core_props.get("creator", "")
        last_mod_by = core_props.get("lastModifiedBy", "")
        if creator and last_mod_by and creator != last_mod_by:
            findings.append(
                AnalyzerFinding(
                    code="OFFICE_META_AUTHOR_MISMATCH",
                    title="Nepodudarnost autora dokumenta",
                    description=(
                        f"Izvorni autor ('{creator}') razlikuje se od zadnjeg uredivaca "
                        f"('{last_mod_by}') — dokument je uredivan od strane druge osobe."
                    ),
                    risk_score=0.25,
                    confidence=0.75,
                    evidence=evidence,
                )
            )

        # Template anomaly (DOCX)
        template = app_props.get("Template", "")
        if template and template.lower() not in ("normal.dotm", "normal", ""):
            findings.append(
                AnalyzerFinding(
                    code="OFFICE_META_CUSTOM_TEMPLATE",
                    title="Nestandardni predlozak dokumenta",
                    description=f"Dokument koristi nestandardni predlozak: '{template}'.",
                    risk_score=0.15,
                    confidence=0.60,
                    evidence=evidence,
                )
            )

        # Zero total edit time (suspicious for modified documents)
        total_time = app_props.get("TotalTime", "")
        if total_time and total_time == "0" and last_mod_by:
            findings.append(
                AnalyzerFinding(
                    code="OFFICE_META_ZERO_EDIT_TIME",
                    title="Nulto vrijeme uredivanja",
                    description=(
                        "Dokument prikazuje 0 minuta ukupnog vremena uredivanja unatok "
                        "tome sto je modificiran — moguce programsko generiranje."
                    ),
                    risk_score=0.20,
                    confidence=0.65,
                    evidence=evidence,
                )
            )

    # ------------------------------------------------------------------
    # 5. Track Changes / Revisions (DOCX)
    # ------------------------------------------------------------------

    def _check_tracked_changes(
        self, zf: zipfile.ZipFile, doc_type: str, findings: list[AnalyzerFinding]
    ) -> None:
        """Detect tracked changes in DOCX files."""
        if doc_type != "docx":
            return

        try:
            doc_xml = zf.read("word/document.xml")
            root = ET.fromstring(doc_xml)
        except (KeyError, ET.ParseError):
            return

        insertions = list(root.iter(f"{{{NS_WP}}}ins"))
        deletions = list(root.iter(f"{{{NS_WP}}}del"))

        total_changes = len(insertions) + len(deletions)
        if total_changes == 0:
            return

        # Extract sample deleted text
        deleted_texts = []
        for d in deletions[:10]:
            for t in d.iter(f"{{{NS_WP}}}delText"):
                if t.text and t.text.strip():
                    deleted_texts.append(t.text.strip()[:100])

        evidence = {
            "insertions": len(insertions),
            "deletions": len(deletions),
            "deleted_text_samples": deleted_texts[:5],
        }

        risk = 0.20
        if deleted_texts:
            risk = 0.40  # Deletions with actual content are more suspicious

        findings.append(
            AnalyzerFinding(
                code="OFFICE_TRACKED_CHANGES",
                title="Pracene izmjene u dokumentu",
                description=(
                    f"Dokument sadrzi {len(insertions)} umetanja i {len(deletions)} brisanja "
                    f"kao pracene izmjene. "
                    + (f"Obrisani tekst ukljucuje: '{deleted_texts[0][:50]}...'"
                       if deleted_texts else "Nema obrisanog teksta za prikaz.")
                ),
                risk_score=risk,
                confidence=0.80,
                evidence=evidence,
            )
        )

    # ------------------------------------------------------------------
    # 6. External References
    # ------------------------------------------------------------------

    def _check_external_references(
        self, zf: zipfile.ZipFile, findings: list[AnalyzerFinding]
    ) -> None:
        """Check for external URL references in relationship files."""
        external_refs = []

        for name in zf.namelist():
            if not name.endswith(".rels"):
                continue
            try:
                rels_xml = zf.read(name)
                root = ET.fromstring(rels_xml)

                for rel in root.iter(f"{{{NS_REL}}}Relationship"):
                    target_mode = rel.get("TargetMode", "")
                    target = rel.get("Target", "")
                    rel_type = rel.get("Type", "")

                    if target_mode == "External" and target.startswith("http"):
                        external_refs.append({
                            "source": name,
                            "target": target[:200],
                            "type": rel_type.rsplit("/", 1)[-1] if "/" in rel_type else rel_type,
                        })
            except (KeyError, ET.ParseError):
                continue

        if external_refs:
            findings.append(
                AnalyzerFinding(
                    code="OFFICE_EXTERNAL_REFS",
                    title="Eksterne reference u dokumentu",
                    description=(
                        f"Dokument sadrzi {len(external_refs)} eksternih URL referenci. "
                        f"Eksterne reference mogu ucitavati sadrzaj s interneta pri otvaranju dokumenta."
                    ),
                    risk_score=0.30,
                    confidence=0.80,
                    evidence={"references": external_refs[:10]},
                )
            )

    # ------------------------------------------------------------------
    # Main analysis
    # ------------------------------------------------------------------

    async def analyze_image(self, image_bytes: bytes, filename: str) -> ModuleResult:
        return self._make_result([])  # No-op for images

    async def analyze_document(self, doc_bytes: bytes, filename: str) -> ModuleResult:
        t0 = time.perf_counter()
        findings: list[AnalyzerFinding] = []

        try:
            zf = zipfile.ZipFile(io.BytesIO(doc_bytes))
        except zipfile.BadZipFile:
            elapsed = int((time.perf_counter() - t0) * 1000)
            return self._make_result(
                [AnalyzerFinding(
                    code="OFFICE_INVALID_ZIP",
                    title="Nevalidna ZIP struktura",
                    description="Datoteka nema validnu ZIP strukturu potrebnu za OOXML format.",
                    risk_score=0.50,
                    confidence=0.90,
                    evidence={},
                )],
                processing_time_ms=elapsed,
            )

        try:
            # 1. Structure validation
            doc_type = self._check_structure(zf, filename, findings)

            # 2. VBA macro detection
            self._check_vba_macros(doc_bytes, zf, findings)

            # 3. Hidden content (XLSX)
            self._check_hidden_content(zf, doc_type, findings)

            # 4. Metadata asymmetry
            self._check_metadata(zf, findings)

            # 5. Track changes (DOCX)
            self._check_tracked_changes(zf, doc_type, findings)

            # 6. External references
            self._check_external_references(zf, findings)

        except Exception as e:
            logger.error("Office forensics failed: %s", e, exc_info=True)
            elapsed = int((time.perf_counter() - t0) * 1000)
            return self._make_result([], processing_time_ms=elapsed, error=str(e))
        finally:
            zf.close()

        elapsed = int((time.perf_counter() - t0) * 1000)

        logger.info(
            "Office forensics complete: %s type=%s findings=%d time=%dms",
            filename,
            doc_type,
            len(findings),
            elapsed,
        )

        return self._make_result(findings, processing_time_ms=elapsed)
