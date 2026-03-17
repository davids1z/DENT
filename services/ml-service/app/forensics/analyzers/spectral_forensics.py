"""
Spectral Forensics Module — Frequency-Domain AI Detection

Inspired by F2D-Net (Forensic Frequency Decomposition Network) research.
AI generators leave artifacts invisible in pixel space but clearly visible
in the frequency domain:

1. Phase spectrum analysis — phase coherence across R,G,B channels
2. Cross-channel frequency correlation — spectral shape similarity
3. Spectral flatness (Wiener entropy) — energy distribution uniformity
4. Multi-band energy ratios — high-frequency deficit detection
5. Block-based frequency anomaly heatmap — spatial visualization

Uses only numpy, scipy, PIL — no additional dependencies required.
"""

import base64
import io
import logging
import time

import numpy as np
from PIL import Image, ImageFilter
from scipy.stats import kurtosis as scipy_kurtosis, entropy as scipy_entropy, gmean

from ..base import AnalyzerFinding, BaseAnalyzer, ModuleResult

logger = logging.getLogger(__name__)

# Jet colormap LUT (same approach as optical.py, cnn_forensics.py)
_COLORMAP_LUT = np.zeros((256, 3), dtype=np.uint8)
for _i in range(256):
    _t = _i / 255.0
    if _t < 0.25:
        _r, _g, _b = 0, int(_t / 0.25 * 255), 255
    elif _t < 0.5:
        _r, _g, _b = 0, 255, int((0.5 - _t) / 0.25 * 255)
    elif _t < 0.75:
        _r, _g, _b = int((_t - 0.5) / 0.25 * 255), 255, 0
    else:
        _r, _g, _b = 255, int((1.0 - _t) / 0.25 * 255), 0
    _COLORMAP_LUT[_i] = [_r, _g, _b]

# Pre-compute 64x64 Hanning window for block analysis
_BLOCK_SIZE = 64
_BLOCK_WINDOW = np.outer(np.hanning(_BLOCK_SIZE), np.hanning(_BLOCK_SIZE))


class SpectralForensicsAnalyzer(BaseAnalyzer):
    """Frequency-domain forensics for AI-generated image detection."""

    MODULE_NAME = "spectral_forensics"
    MODULE_LABEL = "Spektralna forenzika"

    def __init__(self) -> None:
        self._spectral_heatmap_b64: str | None = None

    @property
    def spectral_heatmap_b64(self) -> str | None:
        return self._spectral_heatmap_b64

    async def analyze_image(self, image_bytes: bytes, filename: str) -> ModuleResult:
        start = time.monotonic()
        findings: list[AnalyzerFinding] = []
        self._spectral_heatmap_b64 = None

        try:
            img = Image.open(io.BytesIO(image_bytes))
            if img.mode != "RGB":
                img = img.convert("RGB")

            img_array = np.array(img, dtype=np.float64)

            # Resize large images (FFT is O(n log n), cap for performance)
            max_dim = 1536
            h, w = img_array.shape[:2]
            if max(h, w) > max_dim:
                scale = max_dim / max(h, w)
                new_h, new_w = int(h * scale), int(w * scale)
                img_resized = img.resize((new_w, new_h), Image.LANCZOS)
                img_array = np.array(img_resized, dtype=np.float64)

            # Extract R, G, B channels
            r_ch = img_array[:, :, 0]
            g_ch = img_array[:, :, 1]
            b_ch = img_array[:, :, 2]

            # Apply 2D Hanning window and compute FFT per channel
            h, w = r_ch.shape
            win_h = np.hanning(h)
            win_w = np.hanning(w)
            window = np.outer(win_h, win_w)

            fft_r = np.fft.fftshift(np.fft.fft2(r_ch * window))
            fft_g = np.fft.fftshift(np.fft.fft2(g_ch * window))
            fft_b = np.fft.fftshift(np.fft.fft2(b_ch * window))

            # Log-magnitude spectra
            mag_r = np.log1p(np.abs(fft_r))
            mag_g = np.log1p(np.abs(fft_g))
            mag_b = np.log1p(np.abs(fft_b))

            # Run analysis components
            phase_results = self._phase_spectrum_analysis(fft_r, fft_g, fft_b)
            cross_ch_results = self._cross_channel_frequency_analysis(mag_r, mag_g, mag_b)
            flatness_results = self._spectral_flatness_analysis(mag_r, mag_g, mag_b)
            multiband_results = self._multiband_energy_analysis(mag_r, mag_g, mag_b)

            # Generate frequency anomaly heatmap
            self._spectral_heatmap_b64 = self._generate_spectral_heatmap(img_array)

            # Composite scoring
            composite, evidence = self._compute_composite_score(
                phase_results, cross_ch_results, flatness_results, multiband_results
            )

            # Emit findings
            self._emit_findings(composite, evidence, findings)

        except Exception as e:
            logger.warning("Spectral forensics error: %s", e)
            elapsed = int((time.monotonic() - start) * 1000)
            return self._make_result([], elapsed, error=str(e))

        elapsed = int((time.monotonic() - start) * 1000)
        return self._make_result(findings, elapsed)

    async def analyze_document(self, doc_bytes: bytes, filename: str) -> ModuleResult:
        return self._make_result([], 0)

    # ------------------------------------------------------------------
    # A. Phase Spectrum Analysis
    # ------------------------------------------------------------------

    @staticmethod
    def _phase_spectrum_analysis(
        fft_r: np.ndarray, fft_g: np.ndarray, fft_b: np.ndarray
    ) -> dict:
        """Analyze phase spectrum for AI generation artifacts.

        Key insight from F2D-Net: phase contains structural information
        hypersensitive to AI generation. Natural images have high cross-channel
        phase coherence; AI generators process channels more independently.
        """
        phase_r = np.angle(fft_r)
        phase_g = np.angle(fft_g)
        phase_b = np.angle(fft_b)

        # Cross-channel phase coherence: mean cos(phase_a - phase_b)
        # Natural images: > 0.7, AI: 0.3-0.7
        coh_rg = float(np.mean(np.cos(phase_r - phase_g)))
        coh_rb = float(np.mean(np.cos(phase_r - phase_b)))
        coh_gb = float(np.mean(np.cos(phase_g - phase_b)))
        phase_coherence = (coh_rg + coh_rb + coh_gb) / 3.0

        # Phase gradient kurtosis: spatial gradient of phase map
        # Natural images: high kurtosis (5-15), AI: lower (1-4)
        kurtosis_vals = []
        for phase in [phase_r, phase_g, phase_b]:
            gy, gx = np.gradient(phase)
            grad_mag = np.sqrt(gx**2 + gy**2).flatten()
            # Sample for efficiency
            if len(grad_mag) > 200000:
                rng = np.random.default_rng(42)
                grad_mag = rng.choice(grad_mag, 200000, replace=False)
            k = float(scipy_kurtosis(grad_mag, fisher=True))
            kurtosis_vals.append(max(0.0, k))
        phase_gradient_kurtosis = float(np.mean(kurtosis_vals))

        # Phase entropy: Shannon entropy of phase histogram
        # AI images have higher (more uniform) phase distribution
        entropy_vals = []
        for phase in [phase_r, phase_g, phase_b]:
            hist, _ = np.histogram(phase.flatten(), bins=64, density=True)
            hist = hist + 1e-10  # avoid log(0)
            hist = hist / hist.sum()
            entropy_vals.append(float(scipy_entropy(hist)))
        phase_entropy = float(np.mean(entropy_vals))

        return {
            "phase_coherence": round(phase_coherence, 4),
            "phase_gradient_kurtosis": round(phase_gradient_kurtosis, 4),
            "phase_entropy": round(phase_entropy, 4),
        }

    # ------------------------------------------------------------------
    # B. Cross-Channel Frequency Analysis
    # ------------------------------------------------------------------

    def _cross_channel_frequency_analysis(
        self, mag_r: np.ndarray, mag_g: np.ndarray, mag_b: np.ndarray
    ) -> dict:
        """Compare spectral shapes between R, G, B channels.

        Natural images: camera optics affect all channels similarly → high correlation.
        AI generators: sometimes process channels with slight independence → lower correlation.
        """
        radial_r = self._radial_power_spectrum(mag_r)
        radial_g = self._radial_power_spectrum(mag_g)
        radial_b = self._radial_power_spectrum(mag_b)

        if len(radial_r) < 5:
            return {
                "mean_spectral_correlation": 0.95,
                "min_spectral_correlation": 0.95,
                "spectral_divergence": 0.0,
            }

        # Pearson correlation between radial power spectra
        corr_rg = float(np.corrcoef(radial_r, radial_g)[0, 1]) if np.std(radial_r) > 0 and np.std(radial_g) > 0 else 1.0
        corr_rb = float(np.corrcoef(radial_r, radial_b)[0, 1]) if np.std(radial_r) > 0 and np.std(radial_b) > 0 else 1.0
        corr_gb = float(np.corrcoef(radial_g, radial_b)[0, 1]) if np.std(radial_g) > 0 and np.std(radial_b) > 0 else 1.0

        mean_corr = (corr_rg + corr_rb + corr_gb) / 3.0
        min_corr = min(corr_rg, corr_rb, corr_gb)

        # Jensen-Shannon divergence between normalized radial spectra
        def _js_divergence(a: np.ndarray, b: np.ndarray) -> float:
            # Normalize to probability distributions
            a_norm = np.abs(a) + 1e-10
            b_norm = np.abs(b) + 1e-10
            a_norm = a_norm / a_norm.sum()
            b_norm = b_norm / b_norm.sum()
            m = (a_norm + b_norm) / 2.0
            return float(0.5 * scipy_entropy(a_norm, m) + 0.5 * scipy_entropy(b_norm, m))

        js_rg = _js_divergence(radial_r, radial_g)
        js_rb = _js_divergence(radial_r, radial_b)
        js_gb = _js_divergence(radial_g, radial_b)
        mean_divergence = (js_rg + js_rb + js_gb) / 3.0

        return {
            "mean_spectral_correlation": round(mean_corr, 4),
            "min_spectral_correlation": round(min_corr, 4),
            "spectral_divergence": round(mean_divergence, 4),
        }

    @staticmethod
    def _radial_power_spectrum(magnitude: np.ndarray) -> np.ndarray:
        """Compute radial power spectrum by polar averaging of 2D magnitude."""
        h, w = magnitude.shape
        cy, cx = h // 2, w // 2
        max_r = min(cy, cx)

        if max_r < 10:
            return np.array([])

        Y, X = np.ogrid[:h, :w]
        R = np.sqrt((X - cx) ** 2 + (Y - cy) ** 2).astype(int)

        radial = np.zeros(max_r)
        for r in range(1, max_r):
            mask = R == r
            if np.any(mask):
                radial[r] = np.mean(magnitude[mask])

        # Skip DC component
        return radial[1:]

    # ------------------------------------------------------------------
    # C. Spectral Flatness (Wiener Entropy)
    # ------------------------------------------------------------------

    def _spectral_flatness_analysis(
        self, mag_r: np.ndarray, mag_g: np.ndarray, mag_b: np.ndarray
    ) -> dict:
        """Compute spectral flatness and entropy.

        Spectral flatness = geometric_mean(power) / arithmetic_mean(power).
        Natural images: low (0.10-0.30), energy concentrated in low frequencies.
        AI images: higher (0.30-0.60), more uniform energy distribution.
        """
        flatness_vals = []
        entropy_vals = []

        for mag in [mag_r, mag_g, mag_b]:
            radial = self._radial_power_spectrum(mag)
            if len(radial) < 5:
                flatness_vals.append(0.2)
                entropy_vals.append(3.0)
                continue

            power = radial**2
            power = power + 1e-10  # avoid zeros

            # Spectral flatness (Wiener entropy)
            geo_mean = float(gmean(power))
            arith_mean = float(np.mean(power))
            flatness = geo_mean / arith_mean if arith_mean > 0 else 0.0
            flatness_vals.append(flatness)

            # Spectral entropy
            p_norm = power / power.sum()
            ent = float(scipy_entropy(p_norm))
            entropy_vals.append(ent)

        return {
            "spectral_flatness": round(float(np.mean(flatness_vals)), 4),
            "spectral_entropy": round(float(np.mean(entropy_vals)), 4),
        }

    # ------------------------------------------------------------------
    # D. Multi-Band Energy Analysis
    # ------------------------------------------------------------------

    @staticmethod
    def _multiband_energy_analysis(
        mag_r: np.ndarray, mag_g: np.ndarray, mag_b: np.ndarray
    ) -> dict:
        """Analyze energy distribution across frequency bands.

        Diffusion models systematically underestimate high-frequency content.
        Natural images: high_to_low_ratio ~0.15-0.40
        AI images: high_to_low_ratio ~0.05-0.15
        """
        h, w = mag_r.shape
        cy, cx = h // 2, w // 2
        max_r = min(cy, cx)

        if max_r < 20:
            return {
                "high_to_low_ratio": 0.25,
                "vhigh_to_mid_ratio": 0.10,
                "high_to_total_ratio": 0.10,
            }

        Y, X = np.ogrid[:h, :w]
        R = np.sqrt((X - cx) ** 2 + (Y - cy) ** 2)

        # Define frequency bands (proportion of max radius)
        bands = {
            "dc":    (0, max_r * 0.02),
            "low":   (max_r * 0.02, max_r * 0.15),
            "mid":   (max_r * 0.15, max_r * 0.40),
            "high":  (max_r * 0.40, max_r * 0.70),
            "vhigh": (max_r * 0.70, max_r * 1.00),
        }

        ratios = {"high_to_low": [], "vhigh_to_mid": [], "high_to_total": []}

        for mag in [mag_r, mag_g, mag_b]:
            power = mag**2
            band_energy = {}
            total_energy = 0.0

            for name, (r_min, r_max) in bands.items():
                mask = (R >= r_min) & (R < r_max)
                energy = float(np.sum(power[mask]))
                band_energy[name] = energy
                total_energy += energy

            total_energy = max(total_energy, 1e-10)
            low_e = max(band_energy["low"], 1e-10)
            mid_e = max(band_energy["mid"], 1e-10)

            ratios["high_to_low"].append(band_energy["high"] / low_e)
            ratios["vhigh_to_mid"].append(band_energy["vhigh"] / mid_e)
            ratios["high_to_total"].append(band_energy["high"] / total_energy)

        return {
            "high_to_low_ratio": round(float(np.mean(ratios["high_to_low"])), 4),
            "vhigh_to_mid_ratio": round(float(np.mean(ratios["vhigh_to_mid"])), 4),
            "high_to_total_ratio": round(float(np.mean(ratios["high_to_total"])), 4),
        }

    # ------------------------------------------------------------------
    # E. Frequency Anomaly Heatmap
    # ------------------------------------------------------------------

    def _generate_spectral_heatmap(self, img_array: np.ndarray) -> str:
        """Generate block-based frequency anomaly heatmap.

        Divides image into 64×64 blocks, computes spectral anomaly score
        per block, assembles into a spatial heatmap showing WHERE in the
        image frequency anomalies occur.
        """
        h, w = img_array.shape[:2]

        # Downscale for heatmap computation if too large
        max_heatmap_dim = 1024
        if max(h, w) > max_heatmap_dim:
            scale = max_heatmap_dim / max(h, w)
            new_h, new_w = int(h * scale), int(w * scale)
            img_small = np.array(
                Image.fromarray(img_array.astype(np.uint8)).resize(
                    (new_w, new_h), Image.LANCZOS
                ),
                dtype=np.float64,
            )
        else:
            img_small = img_array
            new_h, new_w = h, w

        block_size = _BLOCK_SIZE
        stride = 32

        # Adaptive stride for large images
        n_blocks_h = (new_h - block_size) // stride + 1
        n_blocks_w = (new_w - block_size) // stride + 1
        if n_blocks_h * n_blocks_w > 800:
            stride = block_size  # No overlap for large images

        n_blocks_h = max(1, (new_h - block_size) // stride + 1)
        n_blocks_w = max(1, (new_w - block_size) // stride + 1)

        score_grid = np.zeros((n_blocks_h, n_blocks_w), dtype=np.float64)

        for bi in range(n_blocks_h):
            for bj in range(n_blocks_w):
                y0 = bi * stride
                x0 = bj * stride
                y1 = min(y0 + block_size, new_h)
                x1 = min(x0 + block_size, new_w)

                # Ensure full block (pad if needed)
                block = img_small[y0:y1, x0:x1]
                if block.shape[0] < block_size or block.shape[1] < block_size:
                    padded = np.zeros((block_size, block_size, 3), dtype=np.float64)
                    padded[: block.shape[0], : block.shape[1]] = block
                    block = padded

                score_grid[bi, bj] = self._block_anomaly_score(block)

        # Render heatmap
        return self._render_heatmap(score_grid, h, w)

    @staticmethod
    def _block_anomaly_score(block: np.ndarray) -> float:
        """Compute spectral anomaly score for a single 64×64 block."""
        scores = []

        for ch in range(3):
            channel = block[:, :, ch]
            windowed = channel * _BLOCK_WINDOW

            fft = np.fft.fftshift(np.fft.fft2(windowed))
            mag = np.abs(fft)
            phase = np.angle(fft)

            power = mag**2 + 1e-10

            # 1. Spectral flatness of block
            geo = float(gmean(power.flatten()))
            arith = float(np.mean(power))
            flatness = geo / arith if arith > 0 else 0.0

            # 2. High-to-low energy ratio
            h, w = mag.shape
            cy, cx = h // 2, w // 2
            max_r = min(cy, cx)
            Y, X = np.ogrid[:h, :w]
            R = np.sqrt((X - cx) ** 2 + (Y - cy) ** 2)

            low_mask = (R >= max_r * 0.02) & (R < max_r * 0.25)
            high_mask = (R >= max_r * 0.40) & (R < max_r * 1.0)

            low_e = float(np.sum(power[low_mask])) + 1e-10
            high_e = float(np.sum(power[high_mask]))
            hl_ratio = high_e / low_e

            scores.append(flatness)
            scores.append(1.0 - min(1.0, hl_ratio / 0.30))  # Lower ratio = more AI-like

        # 3. Phase coherence across channels
        phases = []
        for ch in range(3):
            channel = block[:, :, ch]
            windowed = channel * _BLOCK_WINDOW
            fft = np.fft.fftshift(np.fft.fft2(windowed))
            phases.append(np.angle(fft))

        coh_rg = float(np.mean(np.cos(phases[0] - phases[1])))
        coh_rb = float(np.mean(np.cos(phases[0] - phases[2])))
        coh_gb = float(np.mean(np.cos(phases[1] - phases[2])))
        coherence = (coh_rg + coh_rb + coh_gb) / 3.0

        # Combine: higher score = more anomalous (more AI-like)
        avg_flatness = float(np.mean(scores[::2]))  # flatness values
        avg_hl_deficit = float(np.mean(scores[1::2]))  # HL ratio inversions
        phase_anomaly = max(0.0, 1.0 - (coherence + 0.3) / 1.0)

        anomaly = 0.35 * avg_flatness + 0.35 * avg_hl_deficit + 0.30 * phase_anomaly
        return min(1.0, max(0.0, anomaly))

    @staticmethod
    def _render_heatmap(
        score_grid: np.ndarray, target_h: int, target_w: int
    ) -> str:
        """Render anomaly score grid as a jet-colormap heatmap image."""
        # Normalize to 0-255
        max_val = max(float(np.max(score_grid)), 1e-6)
        normalized = (score_grid / max_val * 255).astype(np.uint8)

        gh, gw = normalized.shape
        heatmap = _COLORMAP_LUT[normalized.ravel()].reshape(gh, gw, 3)

        # Resize to original image dimensions
        heatmap_img = Image.fromarray(heatmap)
        heatmap_img = heatmap_img.resize((target_w, target_h), Image.BILINEAR)
        heatmap_img = heatmap_img.filter(ImageFilter.GaussianBlur(radius=3))

        buffer = io.BytesIO()
        heatmap_img.save(buffer, format="PNG", optimize=True)
        return base64.b64encode(buffer.getvalue()).decode("ascii")

    # ------------------------------------------------------------------
    # F. Composite Scoring
    # ------------------------------------------------------------------

    @staticmethod
    def _compute_composite_score(
        phase: dict, cross_channel: dict, flatness: dict, multiband: dict
    ) -> tuple[float, dict]:
        """Compute weighted composite score from all frequency analysis components.

        Returns (composite_score, evidence_dict).
        """

        def _clip(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
            return max(lo, min(hi, x))

        # Normalize each signal to [0, 1] where 1 = more AI-like
        s_phase_coherence = _clip(1.0 - (phase["phase_coherence"] - 0.3) / 0.5)
        s_phase_kurtosis = _clip(1.0 - (phase["phase_gradient_kurtosis"] - 2.0) / 8.0)
        s_cross_channel = _clip(1.0 - (cross_channel["mean_spectral_correlation"] - 0.75) / 0.20)
        s_spectral_flatness = _clip((flatness["spectral_flatness"] - 0.15) / 0.35)
        s_high_to_low = _clip(1.0 - (multiband["high_to_low_ratio"] - 0.05) / 0.25)
        s_phase_entropy = _clip((phase["phase_entropy"] - 2.5) / 1.5)

        # Weighted combination
        composite = (
            0.25 * s_phase_coherence
            + 0.15 * s_phase_kurtosis
            + 0.20 * s_cross_channel
            + 0.20 * s_spectral_flatness
            + 0.15 * s_high_to_low
            + 0.05 * s_phase_entropy
        )

        evidence = {
            **phase,
            **cross_channel,
            **flatness,
            **multiband,
            "s_phase_coherence": round(s_phase_coherence, 4),
            "s_phase_kurtosis": round(s_phase_kurtosis, 4),
            "s_cross_channel": round(s_cross_channel, 4),
            "s_spectral_flatness": round(s_spectral_flatness, 4),
            "s_high_to_low": round(s_high_to_low, 4),
            "s_phase_entropy": round(s_phase_entropy, 4),
            "composite_score": round(composite, 4),
        }

        return composite, evidence

    # ------------------------------------------------------------------
    # Finding Emission
    # ------------------------------------------------------------------

    @staticmethod
    def _emit_findings(
        composite: float, evidence: dict, findings: list[AnalyzerFinding]
    ) -> None:
        """Emit findings based on composite spectral score."""

        if composite > 0.65:
            findings.append(
                AnalyzerFinding(
                    code="SPECTRAL_AI_DETECTED",
                    title="Frekvencijska domena ukazuje na AI generiranje",
                    description=(
                        f"Spektralna analiza (F2D-Net pristup) otkrila je jake anomalije "
                        f"u frekvencijskoj domeni (kompozitni rezultat: {composite:.0%}). "
                        f"Fazna koherencija izmedju RGB kanala je niska "
                        f"({evidence['phase_coherence']:.2f}), spektralna ravnoca je "
                        f"povisena ({evidence['spectral_flatness']:.2f}), a omjer "
                        f"visokih/niskih frekvencija je snizen ({evidence['high_to_low_ratio']:.3f}). "
                        "Ovi artefakti su karakteristicni za difuzijske generatore "
                        "(Stable Diffusion, DALL-E, Midjourney) — signali su nevidljivi "
                        "ljudskom oku, ali jasno vidljivi u frekvencijskoj domeni."
                    ),
                    risk_score=min(0.90, max(0.80, composite)),
                    confidence=0.85,
                    evidence=evidence,
                )
            )
        elif composite > 0.40:
            findings.append(
                AnalyzerFinding(
                    code="SPECTRAL_AI_SUSPECTED",
                    title="Sumnjive spektralne anomalije",
                    description=(
                        f"Frekvencijska analiza pokazuje umjerene anomalije "
                        f"(kompozitni rezultat: {composite:.0%}). Fazna koherencija: "
                        f"{evidence['phase_coherence']:.2f}, spektralna ravnoca: "
                        f"{evidence['spectral_flatness']:.2f}. Moguce su tragovi "
                        "AI generiranja ili znacajne post-obrade slike."
                    ),
                    risk_score=max(0.40, composite * 0.80),
                    confidence=0.65,
                    evidence=evidence,
                )
            )
        elif composite > 0.25:
            findings.append(
                AnalyzerFinding(
                    code="SPECTRAL_AI_LOW",
                    title="Blage spektralne neobicnosti",
                    description=(
                        f"Frekvencijska analiza pokazuje blage neobicnosti "
                        f"(kompozitni rezultat: {composite:.0%}). Vjerojatno autenticna "
                        "slika s nekim neobicnim frekvencijskim karakteristikama, "
                        "moguce zbog kompresije ili obrade."
                    ),
                    risk_score=composite * 0.50,
                    confidence=0.45,
                    evidence=evidence,
                )
            )
