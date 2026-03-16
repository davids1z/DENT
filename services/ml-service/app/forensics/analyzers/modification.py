import base64
import io
import logging
import time

import numpy as np
from PIL import Image, ImageFilter

from ..base import AnalyzerFinding, BaseAnalyzer, ModuleResult

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Try importing OpenCV for CLAHE; fall back to numpy implementation
# ---------------------------------------------------------------------------
_HAS_CV2 = False
try:
    import cv2

    _HAS_CV2 = True
except ImportError:
    logger.info("opencv not available, using numpy fallback for CLAHE")

# ---------------------------------------------------------------------------
# Jet-style colormap LUT (256 entries, blue→cyan→green→yellow→red)
# ---------------------------------------------------------------------------
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


class ModificationAnalyzer(BaseAnalyzer):
    MODULE_NAME = "modification_detection"
    MODULE_LABEL = "Detekcija modifikacija"

    def __init__(self, ela_quality: int = 95, ela_scale: int = 20):
        self.ela_quality = ela_quality
        self.ela_scale = ela_scale
        self._ela_heatmap_b64: str | None = None

    @property
    def ela_heatmap_b64(self) -> str | None:
        return self._ela_heatmap_b64

    async def analyze_image(self, image_bytes: bytes, filename: str) -> ModuleResult:
        start = time.monotonic()
        findings: list[AnalyzerFinding] = []
        self._ela_heatmap_b64 = None

        try:
            img = Image.open(io.BytesIO(image_bytes))
            if img.mode != "RGB":
                img = img.convert("RGB")

            # 1. Enhanced ELA with CLAHE
            ela_result = self._perform_ela(img)
            if ela_result:
                anomaly_ratio, heatmap_b64 = ela_result
                self._ela_heatmap_b64 = heatmap_b64
                self._evaluate_ela(anomaly_ratio, findings)

            # 2. JPEG 8x8 block grid detection
            self._check_jpeg_block_grid(img, filename, findings)

            # 3. Multi-quality JPEG ghost detection
            self._jpeg_ghost_detection(img, findings)

            # 4. Copy-move self-correlation
            self._check_copy_move(img, findings)

        except Exception as e:
            logger.warning("Modification analysis error: %s", e)
            elapsed = int((time.monotonic() - start) * 1000)
            return self._make_result([], elapsed, error=str(e))

        elapsed = int((time.monotonic() - start) * 1000)
        return self._make_result(findings, elapsed)

    async def analyze_document(self, doc_bytes: bytes, filename: str) -> ModuleResult:
        return self._make_result([], 0)

    # ------------------------------------------------------------------
    # Enhanced ELA with CLAHE histogram equalization
    # ------------------------------------------------------------------

    def _perform_ela(self, img: Image.Image) -> tuple[float, str] | None:
        """Perform Error Level Analysis with CLAHE enhancement."""
        # Re-save at fixed JPEG quality
        buffer = io.BytesIO()
        img.save(buffer, format="JPEG", quality=self.ela_quality)
        buffer.seek(0)
        resaved = Image.open(buffer)

        # Compute absolute difference
        original_arr = np.array(img, dtype=np.float32)
        resaved_arr = np.array(resaved, dtype=np.float32)
        diff = np.abs(original_arr - resaved_arr)

        # Amplify the difference
        ela_arr = np.clip(diff * self.ela_scale, 0, 255).astype(np.uint8)

        # Convert to grayscale for analysis
        gray = np.mean(ela_arr, axis=2).astype(np.float32)

        # Apply CLAHE for local contrast enhancement
        enhanced = self._apply_clahe(gray)

        # Threshold on CLAHE-enhanced image
        mean_val = float(np.mean(enhanced))
        std_val = float(np.std(enhanced))
        threshold = mean_val + 2.0 * std_val
        total_pixels = enhanced.size
        anomalous_pixels = int(np.sum(enhanced > threshold))
        anomaly_ratio = anomalous_pixels / total_pixels if total_pixels > 0 else 0.0

        # Generate heatmap from CLAHE-enhanced ELA
        heatmap_b64 = self._generate_heatmap(enhanced)

        return anomaly_ratio, heatmap_b64

    def _apply_clahe(self, gray: np.ndarray) -> np.ndarray:
        """Apply Contrast Limited Adaptive Histogram Equalization."""
        max_val = max(float(np.max(gray)), 1.0)
        normalized = (gray / max_val * 255).astype(np.uint8)

        if _HAS_CV2:
            clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
            return clahe.apply(normalized).astype(np.float32)

        # Numpy fallback: global histogram equalization
        hist, _ = np.histogram(normalized.flatten(), 256, [0, 256])
        cdf = hist.cumsum()
        cdf_m = np.ma.masked_equal(cdf, 0)
        cdf_m = (cdf_m - cdf_m.min()) * 255 / (cdf_m.max() - cdf_m.min())
        cdf_final = np.ma.filled(cdf_m, 0).astype(np.uint8)
        return cdf_final[normalized].astype(np.float32)

    def _evaluate_ela(
        self, anomaly_ratio: float, findings: list[AnalyzerFinding]
    ) -> None:
        """Evaluate ELA anomaly ratio and add findings."""
        if anomaly_ratio >= 0.15:
            findings.append(
                AnalyzerFinding(
                    code="MOD_ELA_HIGH_ANOMALY",
                    title="Visoka razina ELA anomalija",
                    description=(
                        f"Error Level Analysis otkriva {anomaly_ratio:.1%} piksela s "
                        "anomalnim razinama kompresije. Ovo snazno ukazuje na "
                        "montazu ili naknadnu obradu dijelova slike."
                    ),
                    risk_score=min(0.80, 0.40 + anomaly_ratio * 2),
                    confidence=0.85,
                    evidence={"anomaly_ratio": round(anomaly_ratio, 4)},
                )
            )
        elif anomaly_ratio >= 0.05:
            findings.append(
                AnalyzerFinding(
                    code="MOD_ELA_MODERATE_ANOMALY",
                    title="Umjerena ELA anomalija",
                    description=(
                        f"Error Level Analysis otkriva {anomaly_ratio:.1%} piksela s "
                        "razlicitim razinama kompresije. Moguca lokalna modifikacija "
                        "ili doslikavanje na dijelovima slike."
                    ),
                    risk_score=0.30 + anomaly_ratio,
                    confidence=0.70,
                    evidence={"anomaly_ratio": round(anomaly_ratio, 4)},
                )
            )
        elif anomaly_ratio >= 0.02:
            findings.append(
                AnalyzerFinding(
                    code="MOD_ELA_LOW_ANOMALY",
                    title="Niska ELA anomalija",
                    description=(
                        f"Error Level Analysis pokazuje {anomaly_ratio:.1%} piksela s "
                        "blagim odstupanjima. Vjerojatno normalno za sliku "
                        "komprimiranu vise puta."
                    ),
                    risk_score=0.10,
                    confidence=0.50,
                    evidence={"anomaly_ratio": round(anomaly_ratio, 4)},
                )
            )

    # ------------------------------------------------------------------
    # JPEG 8x8 Block Grid Detection
    # ------------------------------------------------------------------

    def _check_jpeg_block_grid(
        self,
        img: Image.Image,
        filename: str,
        findings: list[AnalyzerFinding],
    ) -> None:
        """Detect JPEG 8x8 block boundary artifacts in non-JPEG images."""
        gray = np.array(img.convert("L"), dtype=np.float32)
        h, w = gray.shape

        if h < 32 or w < 32:
            return

        # Horizontal gradient (column-wise differences)
        dx = np.abs(np.diff(gray, axis=1))
        # Vertical gradient (row-wise differences)
        dy = np.abs(np.diff(gray, axis=0))

        # Analyze column boundaries (every 8th pixel)
        cols = dx.shape[1]
        boundary_cols = [c for c in range(7, cols, 8)]
        if not boundary_cols or len(boundary_cols) < 3:
            return
        non_boundary_cols = [c for c in range(cols) if c % 8 != 7]
        if not non_boundary_cols:
            return

        boundary_energy_h = float(np.mean(dx[:, boundary_cols]))
        non_boundary_energy_h = float(np.mean(dx[:, non_boundary_cols]))

        # Analyze row boundaries
        rows = dy.shape[0]
        boundary_rows = [r for r in range(7, rows, 8)]
        if not boundary_rows or len(boundary_rows) < 3:
            return
        non_boundary_rows = [r for r in range(rows) if r % 8 != 7]
        if not non_boundary_rows:
            return

        boundary_energy_v = float(np.mean(dy[boundary_rows, :]))
        non_boundary_energy_v = float(np.mean(dy[non_boundary_rows, :]))

        # Combined ratio
        avg_boundary = (boundary_energy_h + boundary_energy_v) / 2
        avg_non_boundary = (non_boundary_energy_h + non_boundary_energy_v) / 2
        ratio = avg_boundary / max(avg_non_boundary, 1e-6)

        is_non_jpeg = filename.lower().endswith((".png", ".webp", ".bmp", ".tiff", ".tif"))

        if ratio > 1.5 and is_non_jpeg:
            findings.append(
                AnalyzerFinding(
                    code="MOD_JPEG_BLOCK_GRID",
                    title="JPEG blokovi otkriveni u ne-JPEG formatu",
                    description=(
                        f"Slika u ne-JPEG formatu sadrzi vidljive JPEG 8x8 blok artefakte "
                        f"(omjer energije granica: {ratio:.2f}x). Ovo dokazuje da je "
                        "slika izvorno bila JPEG te je prepakirane u drugi format "
                        "kako bi se prikrili tragovi kompresije."
                    ),
                    risk_score=0.25,
                    confidence=0.80,
                    evidence={
                        "boundary_ratio": round(ratio, 3),
                        "format": filename.rsplit(".", 1)[-1].lower() if "." in filename else "unknown",
                    },
                )
            )
        elif ratio > 2.0:
            findings.append(
                AnalyzerFinding(
                    code="MOD_JPEG_DOUBLE_COMPRESSION",
                    title="Znakovi dvostruke JPEG kompresije",
                    description=(
                        f"Izrazito jaki JPEG blok artefakti (omjer: {ratio:.2f}x) "
                        "ukazuju na dvostruku kompresiju s razlicitim poravnanjem "
                        "mreze, sto moze nastati pri montazi iz razlicitih izvora."
                    ),
                    risk_score=0.15,
                    confidence=0.65,
                    evidence={"boundary_ratio": round(ratio, 3)},
                )
            )

    # ------------------------------------------------------------------
    # Multi-Quality JPEG Ghost Detection
    # ------------------------------------------------------------------

    def _jpeg_ghost_detection(
        self, img: Image.Image, findings: list[AnalyzerFinding]
    ) -> None:
        """Detect mixed compression histories via multi-quality JPEG ghost analysis."""
        qualities = [60, 70, 75, 80, 85, 90, 95]
        block_size = 32
        original_arr = np.array(img, dtype=np.float32)
        h, w = original_arr.shape[:2]

        h_blocks = h // block_size
        w_blocks = w // block_size

        if h_blocks < 3 or w_blocks < 3:
            return

        # Crop to exact block multiples
        cropped = original_arr[: h_blocks * block_size, : w_blocks * block_size]

        # For each quality, compute block-wise Mean Absolute Error
        block_min_mae = np.full((h_blocks, w_blocks), float("inf"))
        block_best_q = np.zeros((h_blocks, w_blocks), dtype=np.int32)

        for q in qualities:
            buf = io.BytesIO()
            img_cropped = Image.fromarray(
                cropped.astype(np.uint8) if cropped.dtype != np.uint8 else cropped
            )
            img_cropped.save(buf, format="JPEG", quality=q)
            buf.seek(0)
            resaved = np.array(Image.open(buf), dtype=np.float32)

            # Ensure same shape after JPEG round-trip
            resaved = resaved[: h_blocks * block_size, : w_blocks * block_size]
            if resaved.shape != cropped.shape:
                continue

            diff = np.abs(cropped - resaved)
            # Mean across channels
            diff_gray = np.mean(diff, axis=2) if diff.ndim == 3 else diff

            # Compute block-wise MAE
            for by in range(h_blocks):
                for bx in range(w_blocks):
                    block = diff_gray[
                        by * block_size : (by + 1) * block_size,
                        bx * block_size : (bx + 1) * block_size,
                    ]
                    mae = float(np.mean(block))
                    if mae < block_min_mae[by, bx]:
                        block_min_mae[by, bx] = mae
                        block_best_q[by, bx] = q

        # Analyze Q* variance across blocks
        q_std = float(np.std(block_best_q))
        q_unique = len(np.unique(block_best_q))

        # If blocks minimize at very different quality levels → mixed compression
        if q_std > 10 and q_unique >= 3:
            findings.append(
                AnalyzerFinding(
                    code="MOD_JPEG_GHOST",
                    title="JPEG Ghost: mijesane razine kompresije",
                    description=(
                        f"Razliciti dijelovi slike minimiziraju gresku pri razlicitim "
                        f"JPEG kvalitetama (std={q_std:.1f}, {q_unique} razina). "
                        "Ovo ukazuje da su dijelovi slike izrezani iz izvora "
                        "s drugacijom povijesti kompresije — tipicno za montazu."
                    ),
                    risk_score=min(0.60, 0.20 + q_std / 50),
                    confidence=0.75,
                    evidence={
                        "quality_std": round(q_std, 2),
                        "unique_qualities": q_unique,
                        "quality_distribution": {
                            str(q): int(np.sum(block_best_q == q)) for q in qualities
                        },
                    },
                )
            )
        elif q_std > 5 and q_unique >= 2:
            findings.append(
                AnalyzerFinding(
                    code="MOD_JPEG_GHOST",
                    title="JPEG Ghost: blaga nekonzistentnost kompresije",
                    description=(
                        f"Umjerena varijacija optimalne JPEG kvalitete medu blokovima "
                        f"(std={q_std:.1f}). Moguca manja modifikacija ili "
                        "visestruko spremanje s razlicitim postavkama."
                    ),
                    risk_score=0.15,
                    confidence=0.55,
                    evidence={
                        "quality_std": round(q_std, 2),
                        "unique_qualities": q_unique,
                    },
                )
            )

    # ------------------------------------------------------------------
    # Copy-Move Self-Correlation (DCT-based)
    # ------------------------------------------------------------------

    def _check_copy_move(
        self, img: Image.Image, findings: list[AnalyzerFinding]
    ) -> None:
        """Detect copy-move forgery via DCT block feature self-correlation."""
        gray = np.array(img.convert("L"), dtype=np.float32)
        h, w = gray.shape

        block_size = 64
        stride = 32  # 50% overlap

        if h < block_size * 2 or w < block_size * 2:
            return

        # Extract blocks and compute DCT features
        blocks: list[tuple[int, int, np.ndarray]] = []

        for y in range(0, h - block_size + 1, stride):
            for x in range(0, w - block_size + 1, stride):
                block = gray[y : y + block_size, x : x + block_size]
                # Simple frequency feature: use 2D DCT via numpy
                # Approximate DCT with real FFT
                fft = np.fft.fft2(block)
                # Take magnitude of top-left 8x8 (low-frequency) coefficients
                feature = np.abs(fft[:8, :8]).flatten()
                # Normalize
                norm = np.linalg.norm(feature)
                if norm > 1e-6:
                    feature = feature / norm
                blocks.append((y, x, feature))

        if len(blocks) < 4:
            return

        # Find similar block pairs using vectorized cosine similarity
        n_blocks = len(blocks)
        features = np.array([b[2] for b in blocks])

        # Compute pairwise cosine similarity in batches to avoid memory issues
        # For large images, limit to max 500 blocks
        if n_blocks > 500:
            # Sample evenly spaced blocks
            indices = np.linspace(0, n_blocks - 1, 500, dtype=int)
            blocks = [blocks[i] for i in indices]
            features = features[indices]
            n_blocks = len(blocks)

        # Cosine similarity matrix (features already normalized)
        sim_matrix = features @ features.T

        # Find pairs with high similarity but significant spatial distance
        min_distance = block_size  # Minimum spatial distance to consider
        matching_pairs: list[tuple[int, int, float]] = []

        for i in range(n_blocks):
            for j in range(i + 1, n_blocks):
                if sim_matrix[i, j] > 0.95:
                    y1, x1 = blocks[i][0], blocks[i][1]
                    y2, x2 = blocks[j][0], blocks[j][1]
                    dist = np.sqrt((y1 - y2) ** 2 + (x1 - x2) ** 2)
                    if dist > min_distance:
                        matching_pairs.append((i, j, float(sim_matrix[i, j])))

        if len(matching_pairs) >= 3:
            avg_sim = np.mean([p[2] for p in matching_pairs])
            findings.append(
                AnalyzerFinding(
                    code="MOD_COPY_MOVE_DETECTED",
                    title="Otkrivena copy-move manipulacija",
                    description=(
                        f"Pronadeno {len(matching_pairs)} parova blokova s izrazito "
                        f"visokom slicnoscu (prosj. {avg_sim:.3f}) na razlicitim "
                        "pozicijama. Ovo snazno ukazuje da je dio slike kopiran "
                        "i zalijepljen na drugo mjesto."
                    ),
                    risk_score=min(0.65, 0.30 + len(matching_pairs) * 0.02),
                    confidence=0.75,
                    evidence={
                        "matching_pairs": len(matching_pairs),
                        "average_similarity": round(avg_sim, 4),
                    },
                )
            )
        elif len(matching_pairs) >= 1:
            avg_sim = np.mean([p[2] for p in matching_pairs])
            findings.append(
                AnalyzerFinding(
                    code="MOD_COPY_MOVE_SUSPECTED",
                    title="Moguca copy-move manipulacija",
                    description=(
                        f"Pronaen {len(matching_pairs)} par(ova) slicnih blokova na "
                        f"razlicitim pozicijama (prosj. slicnost {avg_sim:.3f}). "
                        "Moguci pokazatelj copy-move uredivanja."
                    ),
                    risk_score=0.20,
                    confidence=0.55,
                    evidence={
                        "matching_pairs": len(matching_pairs),
                        "average_similarity": round(avg_sim, 4),
                    },
                )
            )

    # ------------------------------------------------------------------
    # Improved Heatmap Generation (Jet colormap via LUT)
    # ------------------------------------------------------------------

    def _generate_heatmap(self, gray: np.ndarray) -> str:
        """Generate a jet-colormap ELA heatmap as base64 PNG."""
        # Normalize to 0-255
        if gray.dtype != np.uint8:
            max_val = max(float(np.max(gray)), 1.0)
            normalized = (gray / max_val * 255).astype(np.uint8)
        else:
            normalized = gray

        # Apply jet colormap via LUT
        h, w = normalized.shape[:2]
        heatmap = _COLORMAP_LUT[normalized.ravel()].reshape(h, w, 3)

        heatmap_img = Image.fromarray(heatmap)

        # Apply slight blur for smoother visualization
        heatmap_img = heatmap_img.filter(ImageFilter.GaussianBlur(radius=1))

        buffer = io.BytesIO()
        heatmap_img.save(buffer, format="PNG", optimize=True)
        return base64.b64encode(buffer.getvalue()).decode("ascii")
