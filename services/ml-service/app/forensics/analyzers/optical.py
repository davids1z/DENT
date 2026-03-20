import base64
import io
import logging
import time

import numpy as np
from PIL import Image, ImageFilter

from ..base import AnalyzerFinding, BaseAnalyzer, ModuleResult

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Optional imports
# ---------------------------------------------------------------------------
_HAS_PYWT = False
try:
    import pywt  # noqa: F401

    _HAS_PYWT = True
except ImportError:
    logger.info("PyWavelets not installed, wavelet Moire analysis disabled")

# Jet colormap LUT for FFT spectrum visualization (same approach as ELA/CNN)
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


class OpticalForensicsAnalyzer(BaseAnalyzer):
    """Optical forensics: Moire pattern detection for screen recapture fraud."""

    MODULE_NAME = "optical_forensics"
    MODULE_LABEL = "Opticka forenzika"

    def __init__(self) -> None:
        self._fft_spectrum_b64: str | None = None

    @property
    def fft_spectrum_b64(self) -> str | None:
        return self._fft_spectrum_b64

    async def analyze_image(self, image_bytes: bytes, filename: str) -> ModuleResult:
        start = time.monotonic()
        findings: list[AnalyzerFinding] = []
        self._fft_spectrum_b64 = None

        try:
            img = Image.open(io.BytesIO(image_bytes))
            if img.mode != "RGB":
                img = img.convert("RGB")

            gray = np.array(img.convert("L"), dtype=np.float64)

            # Resize large images to cap processing time (FFT is O(n log n))
            max_dim = 2048
            if max(gray.shape) > max_dim:
                scale = max_dim / max(gray.shape)
                new_h = int(gray.shape[0] * scale)
                new_w = int(gray.shape[1] * scale)
                gray_resized = np.array(
                    img.convert("L").resize((new_w, new_h), Image.LANCZOS),
                    dtype=np.float64,
                )
            else:
                gray_resized = gray

            # --- 2D FFT Analysis ---
            magnitude = self._compute_fft_magnitude(gray_resized)

            # Generate FFT spectrum visualization
            self._fft_spectrum_b64 = self._generate_fft_spectrum(magnitude)

            # --- Signal extraction ---
            radial_deviation = self._radial_power_deviation(magnitude)
            peak_count, peak_ratio = self._detect_periodic_peaks(magnitude)
            angular_kurtosis = self._angular_energy_analysis(magnitude)

            # --- Wavelet analysis ---
            wavelet_hh_ratio = 0.0
            wavelet_anisotropy = 0.0
            if _HAS_PYWT:
                wresult = self._wavelet_moire_analysis(gray_resized)
                wavelet_hh_ratio = max(wresult["hh_ratios"]) if wresult["hh_ratios"] else 0.0
                wavelet_anisotropy = max(wresult["anisotropy"]) if wresult["anisotropy"] else 0.0

            # --- Normalize each signal to [0, 1] ---
            s_radial = min(1.0, radial_deviation / 0.6)
            s_peaks = min(1.0, peak_count / 12.0)
            s_peak_ratio = min(1.0, peak_ratio / 6.0)
            s_kurtosis = min(1.0, max(0.0, (angular_kurtosis - 3.0) / 9.0))
            s_hh = min(1.0, wavelet_hh_ratio / 0.30)
            s_aniso = min(1.0, wavelet_anisotropy / 0.8)

            # --- Shadow consistency analysis (AI generators often fail) ---
            shadow_result = self._shadow_consistency_analysis(gray_resized)
            s_shadow = shadow_result.get("inconsistency_score", 0.0)

            # Add shadow signal to composite (small weight — supportive signal)
            composite = (
                0.18 * s_radial
                + 0.13 * s_peaks
                + 0.18 * s_peak_ratio
                + 0.18 * s_kurtosis
                + 0.13 * s_hh
                + 0.08 * s_aniso
                + 0.12 * s_shadow  # Shadow consistency
            )

            evidence = {
                "radial_deviation": round(radial_deviation, 4),
                "peak_count": peak_count,
                "peak_to_bg_ratio": round(peak_ratio, 4),
                "angular_kurtosis": round(angular_kurtosis, 4),
                "wavelet_hh_ratio": round(wavelet_hh_ratio, 4),
                "wavelet_anisotropy": round(wavelet_anisotropy, 4),
                "shadow_inconsistency": round(s_shadow, 4),
                "composite_score": round(composite, 4),
            }

            if composite > 0.7:
                findings.append(
                    AnalyzerFinding(
                        code="OPT_SCREEN_RECAPTURE",
                        title="Detektirano fotografiranje ekrana (recapture)",
                        description=(
                            f"Analiza frekvencijske domene otkrila je izrazite Moire "
                            f"uzorke (kompozitni rezultat: {composite:.0%}) koji nastaju "
                            "iskljucivo kada se fotografija snima s monitora ili "
                            "zaslona. Interferencija pikselne resetke kamere i "
                            "ekrana stvara karakteristicne periodicne artefakte "
                            "vidljive u FFT spektru. Ovo je snazna indikacija prijevare."
                        ),
                        risk_score=0.95,
                        confidence=0.95,
                        evidence=evidence,
                    )
                )
            elif composite > 0.4:
                findings.append(
                    AnalyzerFinding(
                        code="OPT_MOIRE_SUSPECTED",
                        title="Sumnjivi periodicni uzorci u slici",
                        description=(
                            f"Frekvencijska analiza detektirala je umjereno izrazene "
                            f"periodicne uzorke (kompozitni rezultat: {composite:.0%}). "
                            "Moguca je prisutnost Moire efekata koji ukazuju na "
                            "fotografiranje s ekrana, ali moze se raditi i o "
                            "teksturiranim povrsinama u kadru."
                        ),
                        risk_score=0.50,
                        confidence=0.70,
                        evidence=evidence,
                    )
                )
            elif peak_count > 4:
                findings.append(
                    AnalyzerFinding(
                        code="OPT_FFT_PERIODIC_PEAKS",
                        title="Periodicni vrhovi u frekvencijskom spektru",
                        description=(
                            f"FFT spektar sadrzi {peak_count} periodicnih vrhova "
                            f"(omjer vrh/pozadina: {peak_ratio:.1f}x). "
                            "Ovo moze biti uzrokovano teksturom objekta, "
                            "pravilnim uzorcima u pozadini ili blagim Moire efektom."
                        ),
                        risk_score=0.15,
                        confidence=0.50,
                        evidence=evidence,
                    )
                )

        except Exception as e:
            logger.warning("Optical forensics error: %s", e)
            elapsed = int((time.monotonic() - start) * 1000)
            return self._make_result([], elapsed, error=str(e))

        elapsed = int((time.monotonic() - start) * 1000)
        return self._make_result(findings, elapsed)

    async def analyze_document(self, doc_bytes: bytes, filename: str) -> ModuleResult:
        return self._make_result([], 0)

    # ------------------------------------------------------------------
    # 2D FFT Magnitude Computation
    # ------------------------------------------------------------------

    @staticmethod
    def _compute_fft_magnitude(gray: np.ndarray) -> np.ndarray:
        """Compute 2D FFT log-magnitude spectrum with Hanning window."""
        h, w = gray.shape
        # Apply 2D Hanning window to reduce spectral leakage
        win_h = np.hanning(h)
        win_w = np.hanning(w)
        window = np.outer(win_h, win_w)
        windowed = gray * window

        fft = np.fft.fft2(windowed)
        fft_shifted = np.fft.fftshift(fft)
        magnitude = np.log1p(np.abs(fft_shifted))
        return magnitude

    # ------------------------------------------------------------------
    # Radial Power Spectrum — 1/f Deviation
    # ------------------------------------------------------------------

    @staticmethod
    def _radial_power_deviation(magnitude: np.ndarray) -> float:
        """Measure deviation from natural 1/f^alpha power law."""
        h, w = magnitude.shape
        cy, cx = h // 2, w // 2
        max_r = min(cy, cx)

        if max_r < 10:
            return 0.0

        # Compute radial average
        Y, X = np.ogrid[:h, :w]
        R = np.sqrt((X - cx) ** 2 + (Y - cy) ** 2).astype(int)

        radial = np.zeros(max_r)
        for r in range(1, max_r):
            mask = R == r
            if np.any(mask):
                radial[r] = np.mean(magnitude[mask])

        # Fit power law on log-log scale (skip DC and very low freqs)
        start_r = max(3, max_r // 20)
        valid_r = np.arange(start_r, max_r)
        valid_vals = radial[start_r:max_r]

        if len(valid_vals) < 5 or np.all(valid_vals <= 0):
            return 0.0

        # Handle zeros
        pos_mask = valid_vals > 0
        if np.sum(pos_mask) < 5:
            return 0.0

        log_r = np.log(valid_r[pos_mask].astype(np.float64))
        log_p = np.log(valid_vals[pos_mask])

        # Linear regression on log-log: log_p = -alpha * log_r + c
        coeffs = np.polyfit(log_r, log_p, 1)
        fitted_log = np.polyval(coeffs, log_r)
        fitted = np.exp(fitted_log)
        actual = valid_vals[pos_mask]

        # Mean relative deviation
        residual = float(np.mean(np.abs(actual - fitted) / (fitted + 1e-6)))
        return residual

    # ------------------------------------------------------------------
    # Periodic Peak Detection
    # ------------------------------------------------------------------

    @staticmethod
    def _detect_periodic_peaks(magnitude: np.ndarray) -> tuple[int, float]:
        """Detect periodic peaks indicating grid interference patterns."""
        from scipy.ndimage import gaussian_filter, maximum_filter

        h, w = magnitude.shape
        cy, cx = h // 2, w // 2

        # Subtract smoothed version to isolate peaks
        smoothed = gaussian_filter(magnitude, sigma=5)
        residual = magnitude - smoothed

        # Threshold: mean + 3 * std
        mean_r = float(np.mean(residual))
        std_r = float(np.std(residual))
        threshold = mean_r + 3.0 * std_r

        if std_r < 1e-6:
            return 0, 0.0

        # Local maxima detection
        local_max = maximum_filter(residual, size=11)
        peaks = (residual == local_max) & (residual > threshold)

        # Exclude DC region (center 5% of radius)
        r_excl = min(cy, cx) * 0.05
        Y, X = np.ogrid[:h, :w]
        dc_mask = ((X - cx) ** 2 + (Y - cy) ** 2) < (r_excl ** 2)
        peaks[dc_mask] = False

        # Also exclude border pixels (window artifacts)
        border = 5
        peaks[:border, :] = False
        peaks[-border:, :] = False
        peaks[:, :border] = False
        peaks[:, -border:] = False

        peak_count = int(np.sum(peaks))

        if peak_count == 0:
            return 0, 0.0

        peak_vals = residual[peaks]
        bg_mask = ~peaks & ~dc_mask
        bg_vals = residual[bg_mask]

        peak_strength = float(np.mean(peak_vals))
        bg_strength = float(np.mean(np.abs(bg_vals)))
        ratio = peak_strength / max(bg_strength, 1e-6)

        return peak_count, ratio

    # ------------------------------------------------------------------
    # Angular Energy Concentration
    # ------------------------------------------------------------------

    @staticmethod
    def _angular_energy_analysis(magnitude: np.ndarray) -> float:
        """Compute angular energy kurtosis in mid-frequency band."""
        h, w = magnitude.shape
        cy, cx = h // 2, w // 2
        max_r = min(cy, cx)

        if max_r < 20:
            return 3.0  # Default normal kurtosis

        Y, X = np.mgrid[:h, :w]
        R = np.sqrt((X - cx) ** 2 + (Y - cy) ** 2)
        theta = np.arctan2(Y - cy, X - cx)

        # Mid-frequency band: 10%-50% of max radius
        band_mask = (R > max_r * 0.1) & (R < max_r * 0.5)
        band_mask_flat = band_mask.ravel()

        if np.sum(band_mask_flat) < 100:
            return 3.0

        angles = theta.ravel()[band_mask_flat]
        energies = magnitude.ravel()[band_mask_flat]

        # Bin into 36 angular bins (10 degrees each)
        n_bins = 36
        bins = np.linspace(-np.pi, np.pi, n_bins + 1)
        bin_energy = np.zeros(n_bins)

        for i in range(n_bins):
            mask = (angles >= bins[i]) & (angles < bins[i + 1])
            if np.any(mask):
                bin_energy[i] = float(np.mean(energies[mask]))

        # Kurtosis of angular distribution
        std_e = float(np.std(bin_energy))
        if std_e < 1e-6:
            return 3.0

        mean_e = float(np.mean(bin_energy))
        kurtosis = float(
            np.mean(((bin_energy - mean_e) / std_e) ** 4)
        )
        return kurtosis

    # ------------------------------------------------------------------
    # Wavelet Sub-band Energy Analysis
    # ------------------------------------------------------------------

    @staticmethod
    def _wavelet_moire_analysis(gray: np.ndarray) -> dict:
        """Wavelet decomposition for Moire pattern detection."""
        import pywt

        # Ensure dimensions are even (required for DWT)
        h, w = gray.shape
        if h % 2:
            gray = gray[:-1, :]
        if w % 2:
            gray = gray[:, :-1]

        try:
            coeffs = pywt.wavedec2(gray, "db4", level=3)
        except Exception as e:
            logger.debug("Wavelet decomposition failed: %s", e)
            return {"hh_ratios": [], "anisotropy": [], "cross_scale_corr": 0.0}

        ll_energy = float(np.sum(coeffs[0] ** 2))
        if ll_energy < 1e-6:
            return {"hh_ratios": [], "anisotropy": [], "cross_scale_corr": 0.0}

        hh_ratios: list[float] = []
        anisotropy: list[float] = []
        hh_energies: list[float] = []

        for lh, hl, hh in coeffs[1:]:
            lh_e = float(np.sum(lh ** 2))
            hl_e = float(np.sum(hl ** 2))
            hh_e = float(np.sum(hh ** 2))

            hh_ratio = hh_e / ll_energy
            hh_ratios.append(hh_ratio)
            hh_energies.append(hh_e)

            # Anisotropy: if LH >> HL or vice versa → directional bias
            total_dir = lh_e + hl_e
            if total_dir > 1e-6:
                aniso = abs(lh_e - hl_e) / total_dir
            else:
                aniso = 0.0
            anisotropy.append(aniso)

        # Cross-scale HH correlation (Moire appears at multiple scales)
        cross_scale_corr = 0.0
        if len(hh_energies) >= 2:
            # Normalize and compute correlation between adjacent levels
            hh_arr = np.array(hh_energies)
            if np.std(hh_arr) > 1e-6:
                hh_norm = (hh_arr - np.mean(hh_arr)) / np.std(hh_arr)
                # Simple correlation: similar energy across scales
                cross_scale_corr = float(
                    1.0 - np.std(hh_norm) / max(np.mean(np.abs(hh_norm)), 1e-6)
                )
                cross_scale_corr = max(0.0, min(1.0, cross_scale_corr))

        return {
            "hh_ratios": hh_ratios,
            "anisotropy": anisotropy,
            "cross_scale_corr": cross_scale_corr,
        }

    # ------------------------------------------------------------------
    # Shadow Consistency Analysis
    # ------------------------------------------------------------------

    @staticmethod
    def _shadow_consistency_analysis(gray: np.ndarray) -> dict:
        """Analyze shadow direction consistency.

        AI generators often produce shadows from inconsistent light
        sources. This method:
        1. Detects strong gradients (potential shadow edges)
        2. Clusters gradient directions
        3. Measures angular variance — high variance = inconsistent shadows
        """
        from scipy.ndimage import sobel, gaussian_filter

        # Smooth to reduce noise
        smoothed = gaussian_filter(gray, sigma=2.0)

        # Compute gradients
        gx = sobel(smoothed, axis=1)
        gy = sobel(smoothed, axis=0)

        # Gradient magnitude and direction
        magnitude = np.sqrt(gx ** 2 + gy ** 2)
        direction = np.arctan2(gy, gx)  # [-pi, pi]

        # Select strong gradients (top 10% by magnitude)
        threshold = np.percentile(magnitude, 90)
        strong_mask = magnitude > threshold

        if np.sum(strong_mask) < 50:
            return {"inconsistency_score": 0.0, "dominant_angles": []}

        strong_dirs = direction[strong_mask]

        # Bin directions into 18 bins (20 degrees each)
        n_bins = 18
        bins = np.linspace(-np.pi, np.pi, n_bins + 1)
        hist, _ = np.histogram(strong_dirs, bins=bins)
        hist = hist.astype(np.float64)

        if hist.sum() < 1:
            return {"inconsistency_score": 0.0, "dominant_angles": []}

        # Normalize histogram
        hist_norm = hist / hist.sum()

        # Entropy: high entropy = many directions = inconsistent
        eps = 1e-10
        entropy = -float(np.sum(hist_norm * np.log2(hist_norm + eps)))
        max_entropy = np.log2(n_bins)  # Uniform distribution

        # Concentration ratio: ratio of top-2 bins to total
        sorted_hist = np.sort(hist_norm)[::-1]
        top2_ratio = float(sorted_hist[:2].sum())

        # Inconsistency score:
        # - High entropy + low concentration = many shadow directions = suspicious
        # - Low entropy + high concentration = consistent shadows = natural
        entropy_score = float(np.clip(entropy / max_entropy, 0.0, 1.0))
        conc_score = 1.0 - float(np.clip(top2_ratio / 0.60, 0.0, 1.0))

        inconsistency = entropy_score * 0.6 + conc_score * 0.4

        # Find dominant angles for evidence
        top_bins = np.argsort(hist)[-3:]
        bin_centers = (bins[:-1] + bins[1:]) / 2
        dominant_angles = [round(float(np.degrees(bin_centers[b])), 1) for b in top_bins]

        return {
            "inconsistency_score": float(np.clip(inconsistency, 0.0, 1.0)),
            "dominant_angles": dominant_angles,
            "entropy": round(entropy, 4),
            "top2_concentration": round(top2_ratio, 4),
        }

    # ------------------------------------------------------------------
    # FFT Spectrum Visualization
    # ------------------------------------------------------------------

    @staticmethod
    def _generate_fft_spectrum(magnitude: np.ndarray) -> str:
        """Generate a jet-colormap visualization of the FFT magnitude spectrum."""
        # Normalize to 0-255
        max_val = max(float(np.max(magnitude)), 1e-6)
        normalized = (magnitude / max_val * 255).astype(np.uint8)

        h, w = normalized.shape[:2]
        spectrum = _COLORMAP_LUT[normalized.ravel()].reshape(h, w, 3)

        spectrum_img = Image.fromarray(spectrum)
        # Light blur for smoother visualization
        spectrum_img = spectrum_img.filter(ImageFilter.GaussianBlur(radius=1))

        buffer = io.BytesIO()
        spectrum_img.save(buffer, format="PNG", optimize=True)
        return base64.b64encode(buffer.getvalue()).decode("ascii")
