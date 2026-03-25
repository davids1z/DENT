"""
PRNU (Photo Response Non-Uniformity) Sensor Noise Analysis

Every camera sensor has a unique noise pattern caused by manufacturing
imperfections in individual pixels. This "fingerprint" is present in all
photos taken by a physical camera but absent in AI-generated images.

Detection approach:
1. Extract noise residual via wavelet denoising (Wiener filter)
2. Measure structured noise energy (PRNU energy)
3. Analyze cross-channel noise correlation (R/G/B correlate in real cameras)
4. Compute camera signature strength metric

Real photos: high PRNU energy (~0.003-0.01), high cross-channel correlation
AI images: near-zero PRNU energy, uncorrelated channel noise

CPU-only — pure numpy/scipy, no ML models needed.
"""

import io
import logging
import time

import numpy as np
from PIL import Image

from ..base import AnalyzerFinding, BaseAnalyzer, ModuleResult

logger = logging.getLogger(__name__)


class PrnuDetectionAnalyzer(BaseAnalyzer):
    """Camera sensor fingerprint detection via PRNU noise analysis."""

    MODULE_NAME = "prnu_detection"
    MODULE_LABEL = "PRNU senzorska analiza"

    async def analyze_image(self, image_bytes: bytes, filename: str) -> ModuleResult:
        start = time.monotonic()
        findings: list[AnalyzerFinding] = []

        try:
            img = Image.open(io.BytesIO(image_bytes))
            if img.mode != "RGB":
                img = img.convert("RGB")

            arr = np.array(img, dtype=np.float64)

            # Skip if image is too small for meaningful analysis
            if arr.shape[0] < 64 or arr.shape[1] < 64:
                elapsed = int((time.monotonic() - start) * 1000)
                return self._make_result([], elapsed)

            # Extract noise residual per channel
            noise_r = self._extract_noise(arr[:, :, 0])
            noise_g = self._extract_noise(arr[:, :, 1])
            noise_b = self._extract_noise(arr[:, :, 2])

            # 1. PRNU energy — structured sensor noise magnitude
            prnu_energy_r = self._prnu_energy(noise_r)
            prnu_energy_g = self._prnu_energy(noise_g)
            prnu_energy_b = self._prnu_energy(noise_b)
            avg_prnu_energy = (prnu_energy_r + prnu_energy_g + prnu_energy_b) / 3

            # 2. Cross-channel correlation — real sensors have correlated noise
            corr_rg = self._channel_correlation(noise_r, noise_g)
            corr_rb = self._channel_correlation(noise_r, noise_b)
            corr_gb = self._channel_correlation(noise_g, noise_b)
            avg_cross_corr = (corr_rg + corr_rb + corr_gb) / 3

            # 3. Noise spatial uniformity — AI noise is spatially uniform,
            #    real sensor noise has position-dependent patterns
            spatial_var = self._spatial_variance(noise_r, noise_g, noise_b)

            # 4. High-frequency noise structure — real PRNU has specific
            #    spectral characteristics
            hf_structure = self._hf_noise_structure(noise_r)

            # Composite AI probability score.
            # With wavelet denoising, PRNU energy is much lower and cleaner
            # than with a mean filter. Thresholds calibrated for db8 level-4.
            #
            # After wavelet denoising:
            #   Real photos: energy ~0.0005-0.003, cross-corr ~0.01-0.30
            #   AI images: energy ~0.0001-0.0005, cross-corr ~-0.05-0.05
            #   JPEG compression reduces both but preserves relative ordering.
            score = 0.0

            # PRNU energy (wavelet-denoised): primary signal
            if avg_prnu_energy < 0.0002:
                score += 0.35  # Very low — strong AI indicator
            elif avg_prnu_energy < 0.0005:
                score += 0.20  # Low — moderate AI indicator
            elif avg_prnu_energy < 0.001:
                score += 0.05  # Borderline
            elif avg_prnu_energy > 0.002:
                score -= 0.15  # Clear camera signature

            # Cross-channel correlation: secondary signal
            if avg_cross_corr < 0.02:
                score += 0.25  # Uncorrelated — AI indicator
            elif avg_cross_corr < 0.08:
                score += 0.10  # Weakly correlated
            elif avg_cross_corr > 0.15:
                score -= 0.10  # Correlated — camera signature

            # Spatial variance: tertiary signal
            if spatial_var < 0.10:
                score += 0.10  # Too uniform — AI noise
            elif spatial_var > 0.30:
                score -= 0.05  # Position-dependent — sensor

            # HF noise structure
            if hf_structure < 0.15:
                score += 0.10  # Flat spectrum — AI
            elif hf_structure > 0.40:
                score -= 0.05  # Structured — sensor

            score = max(0.0, min(1.0, score))

            evidence = {
                "prnu_energy_avg": round(avg_prnu_energy, 6),
                "prnu_energy_r": round(prnu_energy_r, 6),
                "prnu_energy_g": round(prnu_energy_g, 6),
                "prnu_energy_b": round(prnu_energy_b, 6),
                "cross_corr_avg": round(avg_cross_corr, 4),
                "cross_corr_rg": round(corr_rg, 4),
                "cross_corr_rb": round(corr_rb, 4),
                "cross_corr_gb": round(corr_gb, 4),
                "spatial_variance": round(spatial_var, 4),
                "hf_structure": round(hf_structure, 4),
            }

            if score >= 0.55:
                findings.append(AnalyzerFinding(
                    code="PRNU_NO_SENSOR_PATTERN",
                    title="Senzorski otisak nije detektiran",
                    description=(
                        f"Analiza PRNU (Photo Response Non-Uniformity) senzorskog "
                        f"suma pokazuje da slika nema karakteristican otisak fizicke "
                        f"kamere. Energija senzorskog suma ({avg_prnu_energy:.5f}) je "
                        f"znacajno ispod razine tipicne za prave fotografije "
                        f"(>0.003). Kros-kanalna korelacija ({avg_cross_corr:.3f}) "
                        f"je niska, sto ukazuje na AI-generirani sadrzaj."
                    ),
                    risk_score=min(0.90, score),
                    confidence=min(0.92, 0.70 + score * 0.25),
                    evidence=evidence,
                ))
            elif score >= 0.30:
                findings.append(AnalyzerFinding(
                    code="PRNU_WEAK_PATTERN",
                    title="Slab senzorski otisak",
                    description=(
                        f"PRNU analiza detektira slab senzorski otisak "
                        f"(energija: {avg_prnu_energy:.5f}, korelacija: "
                        f"{avg_cross_corr:.3f}). Moguce objasnjenje: jaka "
                        f"kompresija, screenshot, ili AI-generirani sadrzaj."
                    ),
                    risk_score=score * 0.85,
                    confidence=0.60 + score * 0.15,
                    evidence=evidence,
                ))
            elif avg_prnu_energy > 0.002 and avg_cross_corr > 0.15 and score <= 0.0:
                findings.append(AnalyzerFinding(
                    code="PRNU_AUTHENTIC_SENSOR",
                    title="Autentican senzorski otisak",
                    description=(
                        f"PRNU analiza detektira senzorski otisak fizicke kamere "
                        f"(energija: {avg_prnu_energy:.5f}, korelacija: "
                        f"{avg_cross_corr:.3f})."
                    ),
                    risk_score=-0.10,
                    confidence=min(0.85, 0.60 + avg_cross_corr * 0.50),
                    evidence=evidence,
                ))

        except Exception as e:
            logger.warning("PRNU analysis error: %s", e)
            elapsed = int((time.monotonic() - start) * 1000)
            return self._make_result([], elapsed, error=str(e))

        elapsed = int((time.monotonic() - start) * 1000)
        result = self._make_result(findings, elapsed)
        # Raw score passthrough for meta-learner (even when no findings)
        result.risk_score = round(score, 4)
        return result

    async def analyze_document(self, doc_bytes: bytes, filename: str) -> ModuleResult:
        return self._make_result([], 0)

    # ------------------------------------------------------------------
    # Noise extraction
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_noise(channel: np.ndarray) -> np.ndarray:
        """
        Extract noise residual using wavelet denoising (BayesShrink).

        Wavelet denoising removes image structure (edges, textures) far better
        than a mean filter, leaving only actual sensor noise + random noise.
        Uses 'db8' wavelet at level 4 with soft thresholding.
        """
        try:
            import pywt

            # Wavelet decomposition (Daubechies-8, 4 levels)
            coeffs = pywt.wavedec2(channel, "db8", level=4)

            # Estimate noise sigma from finest detail coefficients (MAD estimator)
            detail_coeffs = coeffs[-1]  # (cH, cV, cD) at finest level
            # Use diagonal detail for sigma estimation (least image content)
            sigma = np.median(np.abs(detail_coeffs[2])) / 0.6745

            # BayesShrink: threshold = sigma^2 / sigma_signal
            # Apply soft thresholding to all detail coefficients
            denoised_coeffs = [coeffs[0]]  # Keep approximation unchanged
            for detail_level in coeffs[1:]:
                thresholded = []
                for detail in detail_level:
                    sigma_detail = max(np.std(detail), 1e-8)
                    sigma_signal = max(np.sqrt(max(sigma_detail**2 - sigma**2, 0)), 1e-8)
                    threshold = sigma**2 / sigma_signal
                    thresholded.append(pywt.threshold(detail, threshold, mode="soft"))
                denoised_coeffs.append(tuple(thresholded))

            denoised = pywt.waverec2(denoised_coeffs, "db8")

            # Match dimensions (wavelet transform may pad)
            denoised = denoised[: channel.shape[0], : channel.shape[1]]

            return channel - denoised

        except ImportError:
            # Fallback to Wiener filter if PyWavelets not available
            from scipy.signal import wiener
            denoised = wiener(channel, mysize=5)
            return channel - denoised

    @staticmethod
    def _prnu_energy(noise: np.ndarray) -> float:
        """
        Compute PRNU energy as the normalized variance of the noise residual.
        Real cameras have higher PRNU energy due to structured sensor noise.
        """
        # Use robust estimator: median absolute deviation
        median = np.median(noise)
        mad = np.median(np.abs(noise - median))
        # Normalize by image intensity scale
        return float(mad / 255.0)

    @staticmethod
    def _channel_correlation(noise_a: np.ndarray, noise_b: np.ndarray) -> float:
        """
        Compute Pearson correlation between two noise channels.
        Real cameras have correlated noise across R/G/B due to shared sensor.
        AI generators produce independent noise per channel.
        """
        a_flat = noise_a.flatten()
        b_flat = noise_b.flatten()

        # Subsample for speed on large images
        if len(a_flat) > 500_000:
            rng = np.random.RandomState(42)
            idx = rng.choice(len(a_flat), 500_000, replace=False)
            a_flat = a_flat[idx]
            b_flat = b_flat[idx]

        a_std = np.std(a_flat)
        b_std = np.std(b_flat)
        if a_std < 1e-8 or b_std < 1e-8:
            return 0.0

        corr = np.corrcoef(a_flat, b_flat)[0, 1]
        return float(max(0.0, corr))

    @staticmethod
    def _spatial_variance(
        noise_r: np.ndarray, noise_g: np.ndarray, noise_b: np.ndarray
    ) -> float:
        """
        Measure spatial non-uniformity of noise by dividing into blocks
        and computing variance of block-level noise energy.
        Real sensors have position-dependent noise; AI noise is uniform.
        """
        block_size = 64
        h, w = noise_r.shape
        if h < block_size * 2 or w < block_size * 2:
            return 0.5  # Not enough data

        block_energies = []
        for y in range(0, h - block_size + 1, block_size):
            for x in range(0, w - block_size + 1, block_size):
                block_r = noise_r[y:y+block_size, x:x+block_size]
                block_g = noise_g[y:y+block_size, x:x+block_size]
                block_b = noise_b[y:y+block_size, x:x+block_size]
                energy = (np.std(block_r) + np.std(block_g) + np.std(block_b)) / 3
                block_energies.append(energy)

        if len(block_energies) < 4:
            return 0.5

        arr = np.array(block_energies)
        mean_e = np.mean(arr)
        if mean_e < 1e-8:
            return 0.0

        # Coefficient of variation of block energies
        cv = float(np.std(arr) / mean_e)
        return min(1.0, cv)

    @staticmethod
    def _hf_noise_structure(noise: np.ndarray) -> float:
        """
        Analyze high-frequency structure of noise residual.
        Real PRNU has characteristic spectral patterns; AI noise is flat.
        """
        # 2D FFT of noise
        f = np.fft.fft2(noise)
        f_shifted = np.fft.fftshift(f)
        magnitude = np.abs(f_shifted)

        h, w = magnitude.shape
        cy, cx = h // 2, w // 2
        max_r = min(cy, cx)

        if max_r < 10:
            return 0.5

        # Compute radial average in high-frequency band (60-90% of radius)
        hf_start = int(max_r * 0.60)
        hf_end = int(max_r * 0.90)
        lf_end = int(max_r * 0.30)

        y_coords, x_coords = np.ogrid[:h, :w]
        r = np.sqrt((y_coords - cy) ** 2 + (x_coords - cx) ** 2)

        hf_mask = (r >= hf_start) & (r <= hf_end)
        lf_mask = r <= lf_end

        hf_energy = np.mean(magnitude[hf_mask]) if np.any(hf_mask) else 0
        lf_energy = np.mean(magnitude[lf_mask]) if np.any(lf_mask) else 1

        if lf_energy < 1e-8:
            return 0.5

        # Ratio of HF to LF energy in noise
        ratio = float(hf_energy / lf_energy)
        return min(1.0, ratio * 2)
