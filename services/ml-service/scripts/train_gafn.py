#!/usr/bin/env python3
"""Train GAFN (Gated Attention Fusion Network) for forensic score fusion.

Usage:
    python -m scripts.train_gafn \
        --data data/labeled_dataset_v8.jsonl \
        --output-dir models/gafn \
        [--epochs 200] [--lr 0.001] [--batch-size 64]

Requires PyTorch. Works on CPU (training is fast — ~1800 params).
"""

import argparse
import json
import os
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

# Add parent for imports
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    import torch
    import torch.nn as nn
    import torch.nn.functional as F
    from torch.utils.data import DataLoader, TensorDataset
except ImportError:
    print("ERROR: PyTorch required. Install with: pip install torch")
    sys.exit(1)

from app.forensics.gafn import (
    FEATURES_PER_MODULE,
    N_CLASSES,
    N_GLOBAL_FEATURES,
    CLASS_NAMES,
    GatedAttentionFusionNetwork,
)
from app.forensics.stacking_meta import MODULE_ORDER

N_MODULES = len(MODULE_ORDER)


def load_dataset(jsonl_path: str) -> tuple[np.ndarray, np.ndarray, dict]:
    """Load JSONL and extract GAFN features.

    Returns (X, y, stats) where:
        X: (N, N_modules*4 + 6) float32
        y: (N,) int64 — 0=authentic, 1=ai_generated, 2=tampered
        stats: class distribution info
    """
    samples = []
    with open(jsonl_path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            samples.append(json.loads(line))

    print(f"Loaded {len(samples)} samples from {jsonl_path}")

    n_features = N_MODULES * FEATURES_PER_MODULE + N_GLOBAL_FEATURES
    X = np.zeros((len(samples), n_features), dtype=np.float32)
    y = np.zeros(len(samples), dtype=np.int64)

    label_map = {"authentic": 0, "ai_generated": 1, "tampered": 2}
    class_counts = defaultdict(int)
    module_coverage = defaultdict(int)

    for idx, sample in enumerate(samples):
        label = sample.get("ground_truth") or sample.get("label", "authentic")
        y[idx] = label_map.get(label, 0)
        class_counts[label] += 1

        modules = sample.get("modules", {})
        n_active = 0
        n_high = 0
        n_low = 0

        for i, mod_name in enumerate(MODULE_ORDER):
            base = i * FEATURES_PER_MODULE
            mod_data = modules.get(mod_name)

            if mod_data is None:
                X[idx, base + 3] = 0.0  # not available
                continue

            risk = float(mod_data.get("risk_score", 0))
            X[idx, base + 0] = risk
            X[idx, base + 3] = 1.0  # available

            findings = mod_data.get("findings", [])
            if findings:
                avg_conf = sum(f.get("confidence", 0) for f in findings) / len(findings)
                n_find = min(len(findings), 10) / 10.0
            else:
                avg_conf = 0.0
                n_find = 0.0

            X[idx, base + 1] = avg_conf
            X[idx, base + 2] = n_find

            n_active += 1
            module_coverage[mod_name] += 1
            if risk >= 0.50:
                n_high += 1
            if risk < 0.15:
                n_low += 1

        # Global features
        g_base = N_MODULES * FEATURES_PER_MODULE
        meta = modules.get("metadata_analysis", {})
        meta_findings = meta.get("findings", [])
        finding_codes = {f.get("code", "") for f in meta_findings}

        X[idx, g_base + 0] = float("META_C2PA_VALID" in finding_codes)
        X[idx, g_base + 1] = float(
            "META_XMP_AI_TOOL_HISTORY" in finding_codes
            or "META_C2PA_AI_GENERATED" in finding_codes
        )
        X[idx, g_base + 2] = float("META_FILENAME_AI_GENERATOR" in finding_codes)
        X[idx, g_base + 3] = n_active / max(N_MODULES, 1)
        X[idx, g_base + 4] = n_high / max(N_MODULES, 1)
        X[idx, g_base + 5] = n_low / max(N_MODULES, 1)

    stats = {
        "n_samples": len(samples),
        "class_counts": dict(class_counts),
        "module_coverage": {
            k: v for k, v in sorted(module_coverage.items(), key=lambda x: -x[1])
        },
    }

    print(f"Classes: {dict(class_counts)}")
    print(f"Module coverage (top 10):")
    for mod, cnt in list(stats["module_coverage"].items())[:10]:
        print(f"  {mod}: {cnt}/{len(samples)} ({cnt/len(samples)*100:.1f}%)")

    return X, y, stats


def train_gafn(
    X: np.ndarray,
    y: np.ndarray,
    epochs: int = 200,
    lr: float = 0.001,
    batch_size: int = 64,
    patience: int = 20,
    n_folds: int = 5,
) -> tuple[dict, dict]:
    """Train GAFN with stratified K-fold CV.

    Returns (best_state_dict, metrics).
    """
    from sklearn.model_selection import StratifiedKFold

    n_features = X.shape[1]
    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"Training on {device}, {n_features} features, {N_MODULES} modules")

    # Class weights for imbalance
    class_counts = np.bincount(y, minlength=N_CLASSES)
    class_weights = len(y) / (N_CLASSES * class_counts + 1)
    class_weights_t = torch.from_numpy(class_weights).float().to(device)
    print(f"Class weights: {class_weights}")

    skf = StratifiedKFold(n_splits=n_folds, shuffle=True, random_state=42)
    fold_metrics = []
    best_model_state = None
    best_f1 = 0.0

    for fold, (train_idx, val_idx) in enumerate(skf.split(X, y)):
        print(f"\n--- Fold {fold+1}/{n_folds} ---")

        X_train = torch.from_numpy(X[train_idx]).to(device)
        y_train = torch.from_numpy(y[train_idx]).to(device)
        X_val = torch.from_numpy(X[val_idx]).to(device)
        y_val = torch.from_numpy(y[val_idx]).to(device)

        train_ds = TensorDataset(X_train, y_train)
        train_dl = DataLoader(train_ds, batch_size=batch_size, shuffle=True)

        model = GatedAttentionFusionNetwork(n_modules=N_MODULES).to(device)
        optimizer = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=1e-4)
        scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=epochs)

        best_val_f1 = 0.0
        patience_counter = 0
        best_fold_state = None

        for epoch in range(epochs):
            # Train
            model.train()
            total_loss = 0
            for xb, yb in train_dl:
                result = model(xb)
                # Focal loss
                ce = F.cross_entropy(result["logits"], yb, weight=class_weights_t, reduction="none")
                pt = torch.exp(-ce)
                focal = ((1 - pt) ** 2 * ce).mean()

                optimizer.zero_grad()
                focal.backward()
                nn.utils.clip_grad_norm_(model.parameters(), 1.0)
                optimizer.step()
                total_loss += focal.item()
            scheduler.step()

            # Validate
            model.eval()
            with torch.no_grad():
                result = model(X_val)
                preds = result["logits"].argmax(dim=1).cpu().numpy()
                y_true = y_val.cpu().numpy()

            # Per-class F1
            from sklearn.metrics import f1_score

            f1 = f1_score(y_true, preds, average="macro", zero_division=0)

            if f1 > best_val_f1:
                best_val_f1 = f1
                patience_counter = 0
                best_fold_state = {k: v.cpu().clone() for k, v in model.state_dict().items()}
            else:
                patience_counter += 1

            if (epoch + 1) % 20 == 0 or patience_counter == 0:
                print(
                    f"  Epoch {epoch+1}: loss={total_loss/len(train_dl):.4f} "
                    f"val_f1={f1:.4f} best={best_val_f1:.4f}"
                )

            if patience_counter >= patience:
                print(f"  Early stopping at epoch {epoch+1}")
                break

        fold_metrics.append(best_val_f1)
        print(f"  Fold {fold+1} best F1: {best_val_f1:.4f}")

        if best_val_f1 > best_f1:
            best_f1 = best_val_f1
            best_model_state = best_fold_state

    mean_f1 = np.mean(fold_metrics)
    std_f1 = np.std(fold_metrics)
    print(f"\n=== CV Results: F1 = {mean_f1:.4f} ± {std_f1:.4f} ===")
    print(f"Best fold F1: {best_f1:.4f}")

    metrics = {
        "cv_f1_mean": round(mean_f1, 4),
        "cv_f1_std": round(std_f1, 4),
        "best_fold_f1": round(best_f1, 4),
        "fold_f1s": [round(f, 4) for f in fold_metrics],
        "n_modules": N_MODULES,
        "n_features": X.shape[1],
        "n_samples": len(y),
        "epochs": epochs,
    }

    return best_model_state, metrics


def main():
    parser = argparse.ArgumentParser(description="Train GAFN fusion network")
    parser.add_argument("--data", required=True, help="JSONL dataset path")
    parser.add_argument("--output-dir", default="models/gafn", help="Output directory")
    parser.add_argument("--epochs", type=int, default=200)
    parser.add_argument("--lr", type=float, default=0.001)
    parser.add_argument("--batch-size", type=int, default=64)
    parser.add_argument("--patience", type=int, default=20)
    parser.add_argument("--folds", type=int, default=5)
    args = parser.parse_args()

    # Load data
    X, y, stats = load_dataset(args.data)

    if len(X) < 100:
        print(f"ERROR: Only {len(X)} samples — need at least 100 for training")
        sys.exit(1)

    # Train
    best_state, metrics = train_gafn(
        X, y,
        epochs=args.epochs,
        lr=args.lr,
        batch_size=args.batch_size,
        patience=args.patience,
        n_folds=args.folds,
    )

    # Save
    os.makedirs(args.output_dir, exist_ok=True)
    weights_path = os.path.join(args.output_dir, "gafn_weights.pt")

    checkpoint = {
        "model_state_dict": best_state,
        "module_order": MODULE_ORDER,
        "n_modules": N_MODULES,
        "n_features": X.shape[1],
        "metrics": metrics,
        "class_names": CLASS_NAMES,
    }
    torch.save(checkpoint, weights_path)
    print(f"\nSaved GAFN weights to {weights_path}")

    # Also save metrics as JSON
    metrics_path = os.path.join(args.output_dir, "gafn_metrics.json")
    with open(metrics_path, "w") as f:
        json.dump({**metrics, **stats}, f, indent=2)
    print(f"Saved metrics to {metrics_path}")

    n_params = sum(v.numel() for v in best_state.values())
    print(f"\nModel: {n_params} parameters, {N_MODULES} modules, {X.shape[1]} features")
    print(f"CV F1: {metrics['cv_f1_mean']:.4f} ± {metrics['cv_f1_std']:.4f}")


if __name__ == "__main__":
    main()
