"""Semantic forensics: AI-generated image detection and face liveness."""

import io
import logging
import time

import cv2
import numpy as np
from PIL import Image
from scipy.fft import dctn
from scipy.ndimage import gaussian_filter
from scipy.stats import kurtosis as scipy_kurtosis

from ..base import AnalyzerFinding, BaseAnalyzer, ModuleResult

logger = logging.getLogger(__name__)


class SemanticForensicsAnalyzer(BaseAnalyzer):
    MODULE_NAME = "semantic_forensics"
    MODULE_LABEL = "Semanticka forenzika"

    def __init__(
        self,
        face_enabled: bool = True,
    ) -> None:
        self._face_enabled = face_enabled
        self._face_cascade: cv2.CascadeClassifier | None = None

    def _get_face_cascade(self) -> cv2.CascadeClassifier:
        if self._face_cascade is None:
            cascade_path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
            self._face_cascade = cv2.CascadeClassifier(cascade_path)
        return self._face_cascade

    # ------------------------------------------------------------------
    # 1a. Statistical AI Detection
    # ------------------------------------------------------------------

    def _dct_spectral_analysis(self, gray: np.ndarray) -> dict:
        """Analyze DCT coefficients for AI generation fingerprints."""
        h, w = gray.shape
        block_size = 8
        # Trim to multiple of block_size
        h_trim = (h // block_size) * block_size
        w_trim = (w // block_size) * block_size
        if h_trim < 16 or w_trim < 16:
            return {"kurtosis": 0.0, "tail_ratio": 0.0, "dc_variance": 0.0}

        img = gray[:h_trim, :w_trim].astype(np.float64)
        blocks = img.reshape(h_trim // block_size, block_size, w_trim // block_size, block_size)
        blocks = blocks.transpose(0, 2, 1, 3).reshape(-1, block_size, block_size)

        # Sample blocks for efficiency (max 2000)
        if len(blocks) > 2000:
            rng = np.random.default_rng(42)
            indices = rng.choice(len(blocks), 2000, replace=False)
            blocks = blocks[indices]

        # DCT each block
        all_ac = []
        dc_values = []
        for block in blocks:
            dct_block = dctn(block, type=2, norm="ortho")
            dc_values.append(dct_block[0, 0])
            # AC coefficients (everything except DC)
            ac = dct_block.flatten()[1:]
            all_ac.extend(ac.tolist())

        all_ac = np.array(all_ac)
        dc_values = np.array(dc_values)

        # Kurtosis of AC coefficients
        # Natural images: high kurtosis (5-15+), AI: lower (2-4)
        ac_kurtosis = float(scipy_kurtosis(all_ac, fisher=True))
        ac_kurtosis = max(0.0, ac_kurtosis)

        # Tail ratio: energy in high-freq AC / total AC energy
        ac_energy = np.abs(all_ac)
        total_energy = np.sum(ac_energy) + 1e-10
        # High-freq = last 25% of zigzag order (approximate: last 16 of 63 coefficients)
        n_per_block = 63
        n_blocks_sampled = len(all_ac) // n_per_block
        if n_blocks_sampled > 0:
            reshaped = all_ac[: n_blocks_sampled * n_per_block].reshape(n_blocks_sampled, n_per_block)
            high_freq = np.abs(reshaped[:, 48:])  # last 15 of 63
            tail_ratio = float(np.sum(high_freq) / total_energy)
        else:
            tail_ratio = 0.0

        # DC variance (normalized)
        dc_variance = float(np.var(dc_values) / (np.mean(np.abs(dc_values)) + 1e-10))

        return {
            "kurtosis": ac_kurtosis,
            "tail_ratio": tail_ratio,
            "dc_variance": dc_variance,
        }

    def _color_correlation_analysis(self, img_array: np.ndarray) -> dict:
        """Analyze cross-channel correlations for AI fingerprints."""
        if img_array.ndim != 3 or img_array.shape[2] < 3:
            return {"mean_correlation": 0.5, "uniformity": 0.5}

        r = img_array[:, :, 0].flatten().astype(np.float64)
        g = img_array[:, :, 1].flatten().astype(np.float64)
        b = img_array[:, :, 2].flatten().astype(np.float64)

        # Sample pixels for efficiency
        if len(r) > 100000:
            rng = np.random.default_rng(42)
            idx = rng.choice(len(r), 100000, replace=False)
            r, g, b = r[idx], g[idx], b[idx]

        def pearson(a: np.ndarray, b: np.ndarray) -> float:
            std_a, std_b = np.std(a), np.std(b)
            if std_a < 1e-10 or std_b < 1e-10:
                return 1.0
            return float(np.corrcoef(a, b)[0, 1])

        corr_rg = pearson(r, g)
        corr_rb = pearson(r, b)
        corr_gb = pearson(g, b)

        correlations = [corr_rg, corr_rb, corr_gb]
        mean_corr = float(np.mean(correlations))
        # Uniformity: how similar are all three correlations
        # AI images tend to have very uniform high correlation
        uniformity = 1.0 - float(np.std(correlations))

        return {"mean_correlation": mean_corr, "uniformity": uniformity}

    def _noise_residual_analysis(self, img_array: np.ndarray) -> dict:
        """Analyze noise patterns for AI vs natural camera signatures."""
        if img_array.ndim == 3:
            gray = np.mean(img_array[:, :, :3], axis=2)
        else:
            gray = img_array.astype(np.float64)

        gray = gray.astype(np.float64)

        # Extract noise residual
        smoothed = gaussian_filter(gray, sigma=1.5)
        noise = gray - smoothed

        # Compute spatial uniformity via local patches
        patch_size = 32
        h, w = noise.shape
        patches_h = h // patch_size
        patches_w = w // patch_size
        if patches_h < 2 or patches_w < 2:
            return {"spatial_uniformity": 0.5, "noise_kurtosis": 0.0}

        noise_trimmed = noise[: patches_h * patch_size, : patches_w * patch_size]
        patches = noise_trimmed.reshape(patches_h, patch_size, patches_w, patch_size)
        patches = patches.transpose(0, 2, 1, 3).reshape(-1, patch_size, patch_size)

        # Local standard deviation per patch
        local_stds = np.array([np.std(p) for p in patches])
        mean_std = np.mean(local_stds)

        # Coefficient of variation of local stds
        # Natural: high CV (noise varies with scene content); AI: low CV (uniform noise)
        if mean_std > 1e-10:
            cv = float(np.std(local_stds) / mean_std)
        else:
            cv = 0.0

        # Spatial uniformity: inverse of CV (higher = more uniform = more suspicious)
        spatial_uniformity = 1.0 / (1.0 + cv)

        # Kurtosis of noise residual
        noise_flat = noise.flatten()
        if len(noise_flat) > 200000:
            rng = np.random.default_rng(42)
            noise_flat = noise_flat[rng.choice(len(noise_flat), 200000, replace=False)]
        noise_kurt = float(scipy_kurtosis(noise_flat, fisher=True))

        return {
            "spatial_uniformity": spatial_uniformity,
            "noise_kurtosis": max(0.0, noise_kurt),
        }

    def _compute_ai_score(self, img_array: np.ndarray, gray: np.ndarray) -> tuple[float, dict]:
        """Compute combined AI-generated detection score."""
        dct = self._dct_spectral_analysis(gray)
        color = self._color_correlation_analysis(img_array)
        noise = self._noise_residual_analysis(img_array)

        # Normalize signals to [0, 1] where 1 = more likely AI

        # DCT kurtosis: natural ~5-15, AI ~2-4. Lower kurtosis = more suspicious
        # Map: kurtosis < 3 → 1.0, kurtosis > 10 → 0.0
        dct_kurt_score = np.clip(1.0 - (dct["kurtosis"] - 3.0) / 7.0, 0.0, 1.0)

        # Color correlation uniformity: AI tends to have uniformity > 0.85
        # Map: uniformity > 0.95 → 1.0, uniformity < 0.7 → 0.0
        color_uniformity_score = np.clip((color["uniformity"] - 0.7) / 0.25, 0.0, 1.0)

        # Noise spatial uniformity: AI has high uniformity (>0.7)
        # Map: uniformity > 0.85 → 1.0, uniformity < 0.5 → 0.0
        noise_uniformity_score = np.clip((noise["spatial_uniformity"] - 0.5) / 0.35, 0.0, 1.0)

        # DCT tail ratio: AI tends to have lower high-freq energy
        # Map: tail_ratio < 0.02 → 1.0, tail_ratio > 0.08 → 0.0
        dct_tail_score = np.clip(1.0 - (dct["tail_ratio"] - 0.02) / 0.06, 0.0, 1.0)

        # Weighted combination
        ai_score = (
            0.30 * dct_kurt_score
            + 0.25 * color_uniformity_score
            + 0.25 * noise_uniformity_score
            + 0.20 * dct_tail_score
        )

        evidence = {
            "dct_kurtosis": round(dct["kurtosis"], 3),
            "dct_kurtosis_score": round(float(dct_kurt_score), 3),
            "dct_tail_ratio": round(dct["tail_ratio"], 4),
            "dct_tail_score": round(float(dct_tail_score), 3),
            "color_mean_correlation": round(color["mean_correlation"], 3),
            "color_uniformity": round(color["uniformity"], 3),
            "color_uniformity_score": round(float(color_uniformity_score), 3),
            "noise_spatial_uniformity": round(noise["spatial_uniformity"], 3),
            "noise_uniformity_score": round(float(noise_uniformity_score), 3),
            "noise_kurtosis": round(noise["noise_kurtosis"], 3),
            "ai_composite_score": round(float(ai_score), 4),
        }

        return float(ai_score), evidence

    # ------------------------------------------------------------------
    # 1b. Face Liveness / PAD
    # ------------------------------------------------------------------

    def _face_liveness_analysis(self, img_array: np.ndarray, gray: np.ndarray) -> list[AnalyzerFinding]:
        """Detect presentation attacks on faces (screen-displayed faces)."""
        if not self._face_enabled:
            return []

        cascade = self._get_face_cascade()
        gray_u8 = gray.astype(np.uint8) if gray.dtype != np.uint8 else gray

        faces = cascade.detectMultiScale(gray_u8, scaleFactor=1.1, minNeighbors=5, minSize=(60, 60))
        if len(faces) == 0:
            return []

        findings = []
        for x, y, w, h in faces:
            face_gray = gray_u8[y : y + h, x : x + w].astype(np.float64)
            face_color = img_array[y : y + h, x : x + w] if img_array.ndim == 3 else None

            # Laplacian variance — depth/focus indicator
            # Real faces: higher variance (depth variation); screen: lower (flat)
            laplacian = cv2.Laplacian(face_gray.astype(np.uint8), cv2.CV_64F)
            lap_var = float(np.var(laplacian))
            # Normalize: lap_var < 100 → suspicious (flat), > 500 → normal
            lap_score = np.clip(1.0 - (lap_var - 100) / 400, 0.0, 1.0)

            # High-frequency energy via FFT
            f = np.fft.fft2(face_gray)
            fshift = np.fft.fftshift(f)
            magnitude = np.abs(fshift)
            rows, cols = face_gray.shape
            crow, ccol = rows // 2, cols // 2
            # High freq: outside 75% of radius
            Y, X = np.ogrid[:rows, :cols]
            max_radius = min(crow, ccol)
            dist = np.sqrt((X - ccol) ** 2 + (Y - crow) ** 2)
            high_mask = dist > (0.75 * max_radius)
            total_energy = np.sum(magnitude) + 1e-10
            hf_ratio = float(np.sum(magnitude[high_mask]) / total_energy)
            # Low HF ratio → suspicious (screen reduces high-freq detail)
            # Map: hf_ratio < 0.05 → 1.0, > 0.15 → 0.0
            hf_score = np.clip(1.0 - (hf_ratio - 0.05) / 0.10, 0.0, 1.0)

            # Specular highlight analysis
            spec_score = 0.0
            if face_color is not None and face_color.ndim == 3:
                # Count saturated pixels (>250 in any channel)
                saturated = np.any(face_color > 250, axis=2)
                sat_ratio = float(np.sum(saturated)) / (w * h + 1e-10)
                # Screens produce more uniform specular; natural has sparse highlights
                # High sat_ratio with uniform distribution → screen
                # Map: sat_ratio > 0.05 → suspicious
                spec_score = np.clip(sat_ratio / 0.05, 0.0, 1.0)

            # Composite face liveness score
            composite = 0.45 * lap_score + 0.35 * hf_score + 0.20 * spec_score

            evidence = {
                "laplacian_variance": round(lap_var, 2),
                "laplacian_score": round(float(lap_score), 3),
                "hf_energy_ratio": round(hf_ratio, 4),
                "hf_score": round(float(hf_score), 3),
                "specular_score": round(float(spec_score), 3),
                "face_liveness_composite": round(float(composite), 4),
                "face_region": {"x": int(x), "y": int(y), "w": int(w), "h": int(h)},
            }

            if composite > 0.7:
                findings.append(
                    AnalyzerFinding(
                        code="SEM_FACE_SCREEN_DETECTED",
                        title="Lice prikazano na ekranu",
                        description="Analiza dubine i teksture lica ukazuje da je lice prikazano na ekranu, a ne uzivo.",
                        risk_score=0.80,
                        confidence=0.80,
                        evidence=evidence,
                    )
                )
            elif composite > 0.4:
                findings.append(
                    AnalyzerFinding(
                        code="SEM_FACE_LIVENESS_SUSPECT",
                        title="Sumnjiva zivost lica",
                        description="Detekcija zivosti lica pokazuje sumnjive karakteristike — moguca prezentacijska prijevara.",
                        risk_score=0.40,
                        confidence=0.55,
                        evidence=evidence,
                    )
                )

        return findings

    # VLM forensic analysis removed — all detection via statistical + face modules
    # (was ~300 lines of OpenRouter API calls for Gemini VLM)

    # ------------------------------------------------------------------
    # Main analysis
    # ------------------------------------------------------------------

    async def analyze_image(self, image_bytes: bytes, filename: str) -> ModuleResult:
        t0 = time.perf_counter()
        findings: list[AnalyzerFinding] = []

        try:
            img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
            img_array = np.array(img)
            gray = np.mean(img_array, axis=2).astype(np.float64)

            # 1a. Statistical AI detection
            ai_score, ai_evidence = self._compute_ai_score(img_array, gray)

            # Thresholds raised — real JPEG photos routinely score 0.35-0.45
            # due to compression artifacts that mimic AI statistical patterns.
            # Only flag when statistical evidence is strong (>0.65) or moderate (>0.50).
            if ai_score > 0.65:
                findings.append(
                    AnalyzerFinding(
                        code="SEM_AI_GENERATED_HIGH",
                        title="Visoka vjerojatnost AI-generirane slike",
                        description="Statisticka analiza DCT spektra, korelacije boja i suma ukazuje na visoku vjerojatnost da je slika generirana umjetnom inteligencijom.",
                        risk_score=0.85,
                        confidence=0.85,
                        evidence=ai_evidence,
                    )
                )
            elif ai_score > 0.50:
                findings.append(
                    AnalyzerFinding(
                        code="SEM_AI_GENERATED_MODERATE",
                        title="Umjerena sumnja na AI-generirani sadrzaj",
                        description="Statisticki pokazatelji sugeriraju moguce koristenje AI generatora slika.",
                        risk_score=0.45,
                        confidence=0.60,
                        evidence=ai_evidence,
                    )
                )
            elif ai_score > 0.35:
                findings.append(
                    AnalyzerFinding(
                        code="SEM_AI_GENERATED_LOW",
                        title="Blagi AI indikatori",
                        description="Neki statisticki pokazatelji odstupaju od tipicnih kamera, ali nedovoljno za potvrdu AI generiranja.",
                        risk_score=0.20,
                        confidence=0.40,
                        evidence=ai_evidence,
                    )
                )

            # 1b. Face liveness
            face_findings = self._face_liveness_analysis(img_array, gray)
            findings.extend(face_findings)

        except Exception as e:
            logger.error("Semantic analysis failed: %s", e, exc_info=True)
            elapsed = int((time.perf_counter() - t0) * 1000)
            return self._make_result([], processing_time_ms=elapsed, error=str(e))

        elapsed = int((time.perf_counter() - t0) * 1000)
        return self._make_result(findings, processing_time_ms=elapsed)

    async def analyze_document(self, doc_bytes: bytes, filename: str) -> ModuleResult:
        return self._make_result([])
