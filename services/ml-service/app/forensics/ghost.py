"""GHOST — Generalized tHreshOld ShifTing calibration engine.

Based on Esposito et al. (2021): post-hoc threshold optimization via
stratified subsampling and Cohen's Kappa maximization.

Algorithm:
  1. Create N stratified subsamples (default 100, each 20% of data).
  2. For each subsample, evaluate thresholds 0.00–1.00 (step 0.01).
  3. For each threshold × subsample, compute Cohen's Kappa.
  4. Take median Kappa per threshold across subsamples.
  5. Select threshold with maximum median Kappa.

This avoids overfitting to any single train/test split and produces
robust, generalizable thresholds.
"""

import logging
from dataclasses import dataclass

import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class CalibrationResult:
    """Result of calibrating a single threshold."""

    threshold_name: str
    default_threshold: float
    optimal_threshold: float
    median_kappa: float
    kappa_ci_lower: float  # 5th percentile
    kappa_ci_upper: float  # 95th percentile
    default_kappa: float  # Kappa at the original threshold
    n_samples: int


class GHOSTCalibrator:
    """GHOST threshold optimizer using stratified subsampling + Cohen's Kappa."""

    def __init__(
        self,
        n_subsamples: int = 100,
        subsample_fraction: float = 0.20,
        threshold_min: float = 0.00,
        threshold_max: float = 1.00,
        threshold_step: float = 0.01,
        random_seed: int = 42,
    ):
        self.n_subsamples = n_subsamples
        self.subsample_fraction = subsample_fraction
        self.threshold_step = threshold_step
        self.thresholds = np.arange(
            threshold_min, threshold_max + threshold_step / 2, threshold_step
        )
        self.rng = np.random.default_rng(random_seed)

    def calibrate(
        self,
        scores: np.ndarray,
        labels: np.ndarray,
        threshold_name: str,
        default_threshold: float,
    ) -> CalibrationResult:
        """Find the optimal threshold for binary classification.

        Args:
            scores: Array of float scores (0–1) from a module or fusion.
            labels: Binary labels — 1 = manipulated/forged, 0 = authentic.
            threshold_name: Human-readable name for logging.
            default_threshold: The current hardcoded threshold.

        Returns:
            CalibrationResult with optimal threshold and statistics.
        """
        scores = np.asarray(scores, dtype=np.float64)
        labels = np.asarray(labels, dtype=np.int32)

        if len(scores) != len(labels):
            raise ValueError("scores and labels must have the same length")

        n = len(scores)
        if n < 10:
            raise ValueError(f"Need at least 10 samples, got {n}")

        subsample_size = max(4, int(n * self.subsample_fraction))

        # Matrix: (n_subsamples, n_thresholds) → kappa values
        kappa_matrix = np.full(
            (self.n_subsamples, len(self.thresholds)), np.nan
        )

        for i in range(self.n_subsamples):
            indices = self._stratified_subsample(labels, subsample_size)
            sub_scores = scores[indices]
            sub_labels = labels[indices]

            for j, t in enumerate(self.thresholds):
                preds = (sub_scores >= t).astype(np.int32)
                kappa_matrix[i, j] = self._cohens_kappa(preds, sub_labels)

        # Median Kappa per threshold (across subsamples)
        median_kappas = np.nanmedian(kappa_matrix, axis=0)

        # Best threshold = max median kappa
        best_idx = int(np.argmax(median_kappas))
        optimal_threshold = float(self.thresholds[best_idx])
        best_median_kappa = float(median_kappas[best_idx])

        # Confidence interval from the best threshold's kappa distribution
        best_kappas = kappa_matrix[:, best_idx]
        valid_kappas = best_kappas[~np.isnan(best_kappas)]
        ci_lower = float(np.percentile(valid_kappas, 5)) if len(valid_kappas) > 0 else 0.0
        ci_upper = float(np.percentile(valid_kappas, 95)) if len(valid_kappas) > 0 else 0.0

        # Kappa at the default threshold for comparison
        default_idx = int(np.argmin(np.abs(self.thresholds - default_threshold)))
        default_kappa = float(median_kappas[default_idx])

        result = CalibrationResult(
            threshold_name=threshold_name,
            default_threshold=default_threshold,
            optimal_threshold=optimal_threshold,
            median_kappa=best_median_kappa,
            kappa_ci_lower=ci_lower,
            kappa_ci_upper=ci_upper,
            default_kappa=default_kappa,
            n_samples=n,
        )

        logger.info(
            "GHOST %s: default=%.2f (κ=%.3f) → optimal=%.2f (κ=%.3f, CI=[%.3f, %.3f]), n=%d",
            threshold_name,
            default_threshold,
            default_kappa,
            optimal_threshold,
            best_median_kappa,
            ci_lower,
            ci_upper,
            n,
        )

        return result

    def _stratified_subsample(
        self, labels: np.ndarray, size: int
    ) -> np.ndarray:
        """Create a stratified subsample preserving class proportions."""
        pos_idx = np.where(labels == 1)[0]
        neg_idx = np.where(labels == 0)[0]

        n_pos = len(pos_idx)
        n_neg = len(neg_idx)
        total = n_pos + n_neg

        if total == 0:
            return np.array([], dtype=np.int64)

        # Proportional allocation (at least 1 per class if available)
        n_pos_sample = max(1, round(size * n_pos / total)) if n_pos > 0 else 0
        n_neg_sample = max(1, round(size * n_neg / total)) if n_neg > 0 else 0

        # Clamp to available
        n_pos_sample = min(n_pos_sample, n_pos)
        n_neg_sample = min(n_neg_sample, n_neg)

        pos_chosen = self.rng.choice(pos_idx, size=n_pos_sample, replace=False)
        neg_chosen = self.rng.choice(neg_idx, size=n_neg_sample, replace=False)

        return np.concatenate([pos_chosen, neg_chosen])

    @staticmethod
    def _cohens_kappa(predictions: np.ndarray, labels: np.ndarray) -> float:
        """Compute Cohen's Kappa for binary classification.

        κ = (p_o - p_e) / (1 - p_e)
        where p_o = observed agreement, p_e = expected agreement by chance.
        """
        n = len(predictions)
        if n == 0:
            return 0.0

        tp = int(np.sum((predictions == 1) & (labels == 1)))
        tn = int(np.sum((predictions == 0) & (labels == 0)))
        fp = int(np.sum((predictions == 1) & (labels == 0)))
        fn = int(np.sum((predictions == 0) & (labels == 1)))

        p_o = (tp + tn) / n  # observed agreement

        # Expected agreement by chance
        p_yes = ((tp + fp) / n) * ((tp + fn) / n)
        p_no = ((tn + fn) / n) * ((tn + fp) / n)
        p_e = p_yes + p_no

        if p_e >= 1.0:
            return 1.0 if p_o >= 1.0 else 0.0

        return (p_o - p_e) / (1.0 - p_e)
