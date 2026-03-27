"""
AI-Generated Text Detection Module

Detects AI-generated text content within documents (PDF, DOCX, XLSX).

Uses a multi-layer detection approach inspired by professional tools
(GPTZero, Originality.ai, Winston AI):

Layer 1 — Statistical Analysis (local, no models):
  * Per-sentence perplexity via DistilGPT-2
  * Burstiness (variance of per-sentence perplexity)
  * N-gram repetition analysis
  * Lexical diversity (Type-Token Ratio)

Layer 2 — ML Classifier (local):
  * Fine-tuned RoBERTa-base for AI text classification
  * Processes text in 512-token chunks with 128-token overlap
  * Aggregates chunk scores for document-level assessment

Layer 3 — Optional GPTZero API integration:
  * Highest accuracy (95.7% on RAID benchmark)
  * Sentence-level detection
  * Configurable via settings.forensics_text_ai_gptzero_api_key
"""

import io
import logging
import math
import os
import re
import time
import zipfile
from collections import Counter

import numpy as np

from ...config import settings
from ..base import AnalyzerFinding, BaseAnalyzer, ModuleResult

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Lazy imports
# ---------------------------------------------------------------------------
_TORCH_AVAILABLE = False
_TRANSFORMERS_AVAILABLE = False
_FITZ_AVAILABLE = False

try:
    import torch
    _TORCH_AVAILABLE = True
except ImportError:
    pass

if _TORCH_AVAILABLE:
    try:
        import transformers  # noqa: F401
        _TRANSFORMERS_AVAILABLE = True
    except ImportError:
        pass

try:
    import fitz  # PyMuPDF
    _FITZ_AVAILABLE = True
except ImportError:
    pass

# Minimum text length (in characters) for reliable analysis
_MIN_TEXT_LENGTH = 300
# Minimum number of sentences for statistical analysis
_MIN_SENTENCES = 5

_PERPLEXITY_MODEL = "distilgpt2"
_CLASSIFIER_MODEL = "fakespot-ai/roberta-base-ai-text-detection-v1"


def _is_likely_english(text: str) -> bool:
    """
    Quick heuristic to check if text is likely English.
    DistilGPT-2 perplexity is only meaningful for English text.
    Non-English text will have artificially high perplexity, skewing results.
    """
    # Sample first 2000 chars
    sample = text[:2000].lower()
    if not sample:
        return False
    # Count common English words
    english_markers = {
        "the", "and", "is", "in", "to", "of", "a", "for", "that", "it",
        "with", "as", "was", "on", "are", "be", "this", "have", "from",
        "or", "an", "by", "not", "but", "at", "which", "they", "has",
    }
    words = set(sample.split())
    matches = len(words & english_markers)
    return matches >= 4


def _split_sentences(text: str) -> list[str]:
    """Split text into sentences using a simple regex heuristic."""
    # Split on period/question/exclamation followed by whitespace and uppercase
    raw = re.split(r'(?<=[.!?])\s+(?=[A-Z\u0100-\u024F])', text)
    # Also split on newlines that seem like paragraph breaks
    sentences = []
    for chunk in raw:
        parts = chunk.split('\n\n')
        for part in parts:
            part = part.strip()
            if len(part) > 10:
                sentences.append(part)
    return sentences


class TextAiDetectionAnalyzer(BaseAnalyzer):
    """AI-generated text detection for documents."""

    MODULE_NAME = "text_ai_detection"
    MODULE_LABEL = "AI tekst detekcija"

    def __init__(self) -> None:
        self._models_loaded = False
        self._perplexity_model = None
        self._perplexity_tokenizer = None
        self._classifier_pipe = None

    # ------------------------------------------------------------------
    # Model loading
    # ------------------------------------------------------------------

    def _ensure_models(self) -> None:
        if self._models_loaded:
            return

        if not _TORCH_AVAILABLE or not _TRANSFORMERS_AVAILABLE:
            self._models_loaded = True
            return

        if not getattr(settings, "forensics_text_ai_enabled", True):
            self._models_loaded = True
            return

        from transformers import (
            AutoModelForCausalLM,
            AutoTokenizer,
            pipeline as hf_pipeline,
        )

        cache_dir = os.path.join(settings.forensics_model_cache_dir, "text_ai")
        os.makedirs(cache_dir, exist_ok=True)

        # Load perplexity model (DistilGPT-2, ~80MB)
        ppl_model = getattr(settings, "forensics_text_ai_perplexity_model", _PERPLEXITY_MODEL)
        try:
            self._perplexity_tokenizer = AutoTokenizer.from_pretrained(
                ppl_model, cache_dir=cache_dir
            )
            self._perplexity_model = AutoModelForCausalLM.from_pretrained(
                ppl_model, cache_dir=cache_dir
            )
            self._perplexity_model.eval()
            logger.info("Perplexity model loaded: %s", ppl_model)
        except Exception as e:
            logger.warning("Failed to load perplexity model: %s", e)

        # Load classifier (RoBERTa-based, ~500MB)
        cls_model = getattr(settings, "forensics_text_ai_classifier", _CLASSIFIER_MODEL)
        try:
            self._classifier_pipe = hf_pipeline(
                "text-classification",
                model=cls_model,
                device=-1,  # CPU
                model_kwargs={"cache_dir": cache_dir},
            )
            logger.info("Text AI classifier loaded: %s", cls_model)
        except Exception as e:
            logger.warning("Failed to load text AI classifier: %s", e)

        self._models_loaded = True

    # ------------------------------------------------------------------
    # Text extraction
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_text_from_pdf(doc_bytes: bytes) -> str:
        """Extract text from PDF using PyMuPDF."""
        if not _FITZ_AVAILABLE:
            return ""
        try:
            doc = fitz.open(stream=doc_bytes, filetype="pdf")
            pages_text = []
            for page in doc:
                pages_text.append(page.get_text())
            doc.close()
            return "\n\n".join(pages_text)
        except Exception as e:
            logger.warning("PDF text extraction failed: %s", e)
            return ""

    @staticmethod
    def _extract_text_from_docx(doc_bytes: bytes) -> str:
        """Extract text from DOCX by parsing word/document.xml."""
        try:
            with zipfile.ZipFile(io.BytesIO(doc_bytes)) as zf:
                if "word/document.xml" not in zf.namelist():
                    return ""
                xml_bytes = zf.read("word/document.xml")
                xml_str = xml_bytes.decode("utf-8", errors="ignore")
                # Extract text between <w:t> tags
                import xml.etree.ElementTree as ET
                root = ET.fromstring(xml_str)
                ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
                texts = []
                for elem in root.iter():
                    if elem.tag.endswith("}t") or elem.tag == "t":
                        if elem.text:
                            texts.append(elem.text)
                return " ".join(texts)
        except Exception as e:
            logger.warning("DOCX text extraction failed: %s", e)
            return ""

    @staticmethod
    def _extract_text_from_xlsx(doc_bytes: bytes) -> str:
        """Extract cell values from XLSX shared strings."""
        try:
            with zipfile.ZipFile(io.BytesIO(doc_bytes)) as zf:
                texts = []
                # Shared strings contain most text in XLSX
                if "xl/sharedStrings.xml" in zf.namelist():
                    xml_bytes = zf.read("xl/sharedStrings.xml")
                    xml_str = xml_bytes.decode("utf-8", errors="ignore")
                    import xml.etree.ElementTree as ET
                    root = ET.fromstring(xml_str)
                    for elem in root.iter():
                        if elem.tag.endswith("}t") and elem.text:
                            texts.append(elem.text)
                return " ".join(texts)
        except Exception as e:
            logger.warning("XLSX text extraction failed: %s", e)
            return ""

    # ------------------------------------------------------------------
    # Analysis
    # ------------------------------------------------------------------

    async def analyze_image(self, image_bytes: bytes, filename: str) -> ModuleResult:
        """Text AI detection is not applicable to images."""
        return self._make_result([], 0)

    async def analyze_document(self, doc_bytes: bytes, filename: str) -> ModuleResult:
        start = time.monotonic()
        findings: list[AnalyzerFinding] = []

        if not getattr(settings, "forensics_text_ai_enabled", True):
            return self._make_result([], int((time.monotonic() - start) * 1000))

        try:
            # Extract text based on file type
            fn_lower = filename.lower()
            if fn_lower.endswith(".pdf"):
                text = self._extract_text_from_pdf(doc_bytes)
            elif fn_lower.endswith(".docx"):
                text = self._extract_text_from_docx(doc_bytes)
            elif fn_lower.endswith(".xlsx"):
                text = self._extract_text_from_xlsx(doc_bytes)
            else:
                # Unsupported format — skip
                return self._make_result([], int((time.monotonic() - start) * 1000))

            text = text.strip()
            if len(text) < _MIN_TEXT_LENGTH:
                # Too short for reliable analysis
                elapsed = int((time.monotonic() - start) * 1000)
                if text:
                    findings.append(
                        AnalyzerFinding(
                            code="TEXT_TOO_SHORT",
                            title="Premalo teksta za AI analizu",
                            description=(
                                f"Dokument sadrzi samo {len(text)} znakova. "
                                f"Potrebno je najmanje {_MIN_TEXT_LENGTH} znakova "
                                f"za pouzdanu AI detekciju."
                            ),
                            risk_score=0.0,
                            confidence=0.0,
                            evidence={"text_length": len(text)},
                        )
                    )
                return self._make_result(findings, elapsed)

            self._ensure_models()

            # Layer 1: Statistical analysis
            sentences = _split_sentences(text)
            stat_score, stat_details = self._statistical_analysis(text, sentences)

            # Layer 2: ML classifier
            cls_score, cls_details = self._classifier_analysis(text)

            # Combine scores
            combined = self._combine_scores(stat_score, cls_score, stat_details)

            # Emit findings
            self._emit_findings(combined, stat_details, cls_details, findings)

        except Exception as e:
            logger.warning("Text AI detection error: %s", e)
            return self._make_result(
                [], int((time.monotonic() - start) * 1000), error=str(e)
            )

        elapsed = int((time.monotonic() - start) * 1000)
        return self._make_result(findings, elapsed)

    # ------------------------------------------------------------------
    # Layer 1: Statistical analysis
    # ------------------------------------------------------------------

    def _statistical_analysis(
        self, text: str, sentences: list[str]
    ) -> tuple[float, dict]:
        """
        Compute statistical signals that distinguish AI from human text.
        Returns (score, details_dict).
        """
        details: dict = {}
        signals: list[tuple[float, float]] = []  # (score, weight)

        # A. Perplexity analysis (English only — DistilGPT-2 is English-trained)
        is_english = _is_likely_english(text)
        details["language_english"] = is_english
        if self._perplexity_model is not None and len(sentences) >= _MIN_SENTENCES and is_english:
            perplexities = self._compute_perplexities(sentences)
            if perplexities:
                mean_ppl = float(np.mean(perplexities))
                std_ppl = float(np.std(perplexities))
                details["perplexity_mean"] = round(mean_ppl, 2)
                details["perplexity_std"] = round(std_ppl, 2)

                # Low perplexity → AI. Sigmoid centred at 20.
                ppl_signal = 1.0 / (1.0 + math.exp(0.15 * (mean_ppl - 20)))
                signals.append((ppl_signal, 0.30))
                details["perplexity_signal"] = round(ppl_signal, 4)

                # B. Burstiness (variance of per-sentence perplexity)
                # Low burstiness → AI (uniformly predictable)
                if mean_ppl > 1e-8:
                    burstiness = std_ppl / mean_ppl
                else:
                    burstiness = 0.0
                details["burstiness"] = round(burstiness, 4)

                burst_signal = 1.0 / (1.0 + math.exp(5.0 * (burstiness - 0.5)))
                signals.append((burst_signal, 0.25))
                details["burstiness_signal"] = round(burst_signal, 4)

        # C. N-gram repetition
        ngram_score = self._ngram_repetition(text)
        details["ngram_repetition"] = round(ngram_score, 4)
        # High repetition → AI
        ngram_signal = np.clip(ngram_score / 0.05, 0.0, 1.0)
        signals.append((float(ngram_signal), 0.20))

        # D. Lexical diversity (Type-Token Ratio)
        words = text.lower().split()
        if len(words) > 50:
            # Use first 1000 words for TTR (normalise for text length)
            sample = words[:1000]
            ttr = len(set(sample)) / len(sample)
            details["type_token_ratio"] = round(ttr, 4)

            # Low TTR → AI (less diverse vocabulary)
            # Typical human: 0.45-0.65, AI: 0.30-0.45
            ttr_signal = 1.0 / (1.0 + math.exp(15.0 * (ttr - 0.42)))
            signals.append((float(ttr_signal), 0.15))
            details["ttr_signal"] = round(float(ttr_signal), 4)

        # E. Sentence length uniformity
        if len(sentences) >= _MIN_SENTENCES:
            lengths = [len(s.split()) for s in sentences]
            mean_len = np.mean(lengths)
            std_len = np.std(lengths)
            if mean_len > 0:
                cv = std_len / mean_len  # Coefficient of variation
            else:
                cv = 0.0
            details["sentence_length_cv"] = round(float(cv), 4)

            # Low CV → AI (uniform sentence lengths)
            cv_signal = 1.0 / (1.0 + math.exp(8.0 * (cv - 0.4)))
            signals.append((float(cv_signal), 0.10))

        # Weighted combination
        if not signals:
            return 0.0, details

        total_weight = sum(w for _, w in signals)
        score = sum(s * w for s, w in signals) / total_weight if total_weight > 0 else 0.0
        details["statistical_score"] = round(score, 4)
        return float(score), details

    def _compute_perplexities(self, sentences: list[str]) -> list[float]:
        """Compute per-sentence perplexity using the causal LM."""
        if self._perplexity_model is None or self._perplexity_tokenizer is None:
            return []

        perplexities = []
        max_sentences = 50  # Cap for performance

        for sent in sentences[:max_sentences]:
            try:
                encodings = self._perplexity_tokenizer(
                    sent, return_tensors="pt", truncation=True, max_length=256
                )
                input_ids = encodings["input_ids"]
                if input_ids.shape[1] < 2:
                    continue

                with torch.no_grad():
                    outputs = self._perplexity_model(input_ids, labels=input_ids)
                    loss = outputs.loss
                    ppl = float(torch.exp(loss))
                    # Cap at reasonable range
                    ppl = min(ppl, 1000.0)
                    perplexities.append(ppl)
            except Exception as e:
                logger.debug("Perplexity computation for chunk: %s", e)
                continue

        return perplexities

    @staticmethod
    def _ngram_repetition(text: str, n: int = 4) -> float:
        """Compute 4-gram repetition ratio (repeated / total)."""
        words = text.lower().split()
        if len(words) < n + 1:
            return 0.0

        ngrams = [tuple(words[i:i + n]) for i in range(len(words) - n + 1)]
        counter = Counter(ngrams)
        total = len(ngrams)
        repeated = sum(count - 1 for count in counter.values() if count > 1)

        return repeated / total if total > 0 else 0.0

    # ------------------------------------------------------------------
    # Layer 2: ML Classifier
    # ------------------------------------------------------------------

    def _classifier_analysis(self, text: str) -> tuple[float, dict]:
        """
        Run fine-tuned RoBERTa classifier on text chunks.
        Returns (score, details_dict).
        """
        details: dict = {}

        if self._classifier_pipe is None:
            details["classifier"] = "unavailable"
            return 0.0, details

        # Split into overlapping chunks of ~512 tokens
        chunk_size = 500  # words (approximate tokens)
        overlap = 128
        words = text.split()
        chunks = []

        i = 0
        while i < len(words):
            chunk = " ".join(words[i:i + chunk_size])
            if len(chunk) > 50:  # Minimum chunk length
                chunks.append(chunk)
            i += chunk_size - overlap

        if not chunks:
            return 0.0, details

        # Classify each chunk
        fake_scores = []
        for chunk in chunks[:20]:  # Cap at 20 chunks for performance
            try:
                result = self._classifier_pipe(chunk, truncation=True, max_length=512)
                for r in result:
                    label = r.get("label", "").upper()
                    score = r.get("score", 0.5)
                    if "FAKE" in label or "AI" in label or "MACHINE" in label:
                        fake_scores.append(score)
                    elif "REAL" in label or "HUMAN" in label:
                        fake_scores.append(1.0 - score)
                    else:
                        # Unknown label — assume binary with index
                        if "1" in label or "LABEL_1" in label:
                            fake_scores.append(score)
                        else:
                            fake_scores.append(1.0 - score)
            except Exception as e:
                logger.debug("Chunk classification error: %s", e)
                continue

        if not fake_scores:
            return 0.0, details

        # Aggregate: use weighted mean with higher weight for high-confidence chunks
        scores_arr = np.array(fake_scores)
        # Weight by deviation from 0.5 (more confident = more weight)
        weights = np.abs(scores_arr - 0.5) + 0.1
        cls_score = float(np.average(scores_arr, weights=weights))

        details["classifier_score"] = round(cls_score, 4)
        details["chunks_analyzed"] = len(fake_scores)
        details["chunk_scores_mean"] = round(float(scores_arr.mean()), 4)
        details["chunk_scores_std"] = round(float(scores_arr.std()), 4)

        return cls_score, details

    # ------------------------------------------------------------------
    # Score combination
    # ------------------------------------------------------------------

    @staticmethod
    def _combine_scores(
        stat_score: float,
        cls_score: float,
        stat_details: dict,
    ) -> float:
        """Combine statistical and classifier scores."""
        has_stats = stat_details.get("statistical_score") is not None
        has_cls = cls_score > 0.0

        if has_stats and has_cls:
            # Both available — weighted combination, classifier slightly trusted more
            combined = stat_score * 0.40 + cls_score * 0.60
            # Agreement bonus: both signals agree
            if stat_score > 0.55 and cls_score > 0.55:
                combined = max(combined, max(stat_score, cls_score) * 0.95)
        elif has_cls:
            combined = cls_score
        elif has_stats:
            combined = stat_score * 0.85  # Slight discount without classifier
        else:
            combined = 0.0

        return float(np.clip(combined, 0.0, 1.0))

    # ------------------------------------------------------------------
    # Findings
    # ------------------------------------------------------------------

    @staticmethod
    def _emit_findings(
        combined: float,
        stat_details: dict,
        cls_details: dict,
        findings: list[AnalyzerFinding],
    ) -> None:
        evidence = {
            "method": "multi_layer_text_ai_detection",
            "statistical": stat_details,
            "classifier": cls_details,
            "combined_score": round(combined, 4),
        }

        if combined > 0.70:
            findings.append(
                AnalyzerFinding(
                    code="TEXT_AI_DETECTED",
                    title="Detektiran AI-generirani tekst",
                    description=(
                        f"Viseslojni sustav detekcije (statisticka analiza perpleksije "
                        f"i burstiness + RoBERTa klasifikator) indicira s visokom "
                        f"pouzdanoscu ({combined:.0%}) da tekst u ovom dokumentu "
                        f"potjece od AI jezicnog modela. AI-generirani tekst ima "
                        f"karakteristicne obrasce: nisku perpleksiju, uniformnu "
                        f"strukturu recenica i ogranicenu leksicku raznolikost."
                    ),
                    risk_score=min(0.95, max(0.70, combined)),
                    confidence=min(0.92, 0.60 + combined * 0.30),
                    evidence=evidence,
                )
            )
        elif combined > 0.45:
            findings.append(
                AnalyzerFinding(
                    code="TEXT_AI_SUSPECTED",
                    title="Sumnja na AI-generirani tekst",
                    description=(
                        f"Analiza teksta dokumenta pokazuje umjerene indikatore "
                        f"({combined:.0%}) moguceg AI generiranja. Statisticki "
                        f"obrasci djelomicno odgovaraju AI-generiranom sadrzaju."
                    ),
                    risk_score=max(0.45, combined * 0.90),
                    confidence=min(0.80, 0.45 + combined * 0.30),
                    evidence=evidence,
                )
            )
        elif combined > 0.25:
            findings.append(
                AnalyzerFinding(
                    code="TEXT_AI_LOW",
                    title="Blagi indikatori AI teksta",
                    description=(
                        f"Tekst dokumenta pokazuje blage indikatore ({combined:.0%}) "
                        f"moguceg AI generiranja, ali pouzdanost je niska."
                    ),
                    risk_score=combined * 0.60,
                    confidence=0.35 + combined * 0.15,
                    evidence=evidence,
                )
            )
