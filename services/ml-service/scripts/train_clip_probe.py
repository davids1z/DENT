#!/usr/bin/env python3
"""Train CLIP MLP probe for AI image detection from S3 calibration data.

Extracts CLIP ViT-L/14 embeddings from calibration images on S3,
trains a 2-layer MLP probe (768→256→1), saves weights as probe_weights.npz.

Falls back to LogisticRegression if --linear flag is used.

Usage:
  cd /root/DENT/services/ml-service
  python3 -m scripts.train_clip_probe \
    --bucket dent-calibration-data \
    --s3-prefix train_v7_webp \
    --output models/clip_ai/probe_weights.npz
"""
import argparse
import csv
import io
import os
import sys

import boto3
import numpy as np
from PIL import Image

try:
    from tqdm import tqdm
except ImportError:
    def tqdm(it, **kw):
        total = kw.get("total", "?")
        for i, x in enumerate(it, 1):
            if i % 50 == 0:
                print(f"  [{i}/{total}]", flush=True)
            yield x

VALID_CLASSES = {"authentic", "ai_generated", "tampered"}


def main():
    parser = argparse.ArgumentParser(description="Train CLIP AI detection probe")
    parser.add_argument("--bucket", required=True)
    parser.add_argument("--output", default="models/clip_ai/probe_weights.npz")
    parser.add_argument("--region", default="eu-central-1")
    parser.add_argument("--max-images", type=int, default=0, help="Limit images (0=all)")
    parser.add_argument("--s3-prefix", default="processed", help="S3 prefix for images/labels")
    parser.add_argument("--linear", action="store_true", help="Use LogisticRegression instead of MLP")
    args = parser.parse_args()

    import torch
    from transformers import CLIPModel, CLIPProcessor

    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"Device: {device}")

    print("Loading CLIP ViT-L/14...")
    model = CLIPModel.from_pretrained("openai/clip-vit-large-patch14").to(device)
    processor = CLIPProcessor.from_pretrained("openai/clip-vit-large-patch14")
    model.eval()
    print("CLIP loaded")

    # Load labels from S3
    s3 = boto3.client("s3", region_name=args.region)
    s3_prefix = args.s3_prefix
    resp = s3.get_object(Bucket=args.bucket, Key=f"{s3_prefix}/labels.csv")
    content = resp["Body"].read().decode("utf-8")
    labels = {}
    sources = {}  # track source/generator for per-generator metrics
    for row in csv.DictReader(io.StringIO(content)):
        fn = row.get("filename", "").strip()
        gt = row.get("ground_truth", "").strip().lower()
        if fn and gt in VALID_CLASSES:
            labels[fn] = gt
            sources[fn] = row.get("source", "unknown")

    items = sorted(labels.items())
    if args.max_images > 0:
        items = items[:args.max_images]
    print(f"Processing {len(items)} images")

    # Extract embeddings with batch GPU inference + parallel S3 download
    from concurrent.futures import ThreadPoolExecutor
    BATCH_SIZE = 32
    S3_WORKERS = 8

    embeddings = []
    y_labels = []
    filenames_list = []
    errors = 0

    def _download_image(item):
        fn, gt = item
        try:
            resp = s3.get_object(Bucket=args.bucket, Key=f"{s3_prefix}/{fn}")
            img = Image.open(io.BytesIO(resp["Body"].read())).convert("RGB")
            return fn, gt, img
        except Exception as e:
            return fn, gt, None

    # Process in batches
    for batch_start in tqdm(range(0, len(items), BATCH_SIZE),
                            desc="Extracting CLIP embeddings",
                            total=(len(items) + BATCH_SIZE - 1) // BATCH_SIZE):
        batch_items = items[batch_start:batch_start + BATCH_SIZE]

        # Parallel S3 download
        with ThreadPoolExecutor(max_workers=S3_WORKERS) as pool:
            results = list(pool.map(_download_image, batch_items))

        # Filter successful downloads
        batch_imgs = []
        batch_meta = []
        for fn, gt, img in results:
            if img is not None:
                batch_imgs.append(img)
                batch_meta.append((fn, gt))
            else:
                errors += 1

        if not batch_imgs:
            continue

        # Batch GPU inference
        inputs = processor(images=batch_imgs, return_tensors="pt").to(device)
        with torch.no_grad():
            vision_out = model.vision_model(pixel_values=inputs["pixel_values"])
            pooled = vision_out.pooler_output
            features = model.visual_projection(pooled)
            features = features / features.norm(dim=-1, keepdim=True)
            batch_embeddings = features.cpu().numpy()

        for i, (fn, gt) in enumerate(batch_meta):
            embeddings.append(batch_embeddings[i])
            y_labels.append(0 if gt == "authentic" else 1)
            filenames_list.append(fn)

    X = np.array(embeddings, dtype=np.float32)
    y = np.array(y_labels, dtype=np.int32)
    print(f"\nEmbeddings: {X.shape} ({errors} errors)")
    print(f"Class balance: {(y==0).sum()} authentic, {(y==1).sum()} manipulated")

    from sklearn.preprocessing import StandardScaler
    from sklearn.metrics import classification_report, f1_score
    from sklearn.model_selection import StratifiedKFold

    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X)

    if args.linear:
        _train_linear(X, X_scaled, y, scaler, filenames_list, labels, sources, args)
    else:
        _train_mlp(X, X_scaled, y, scaler, filenames_list, labels, sources, args)


def _train_mlp(X, X_scaled, y, scaler, filenames_list, labels, sources, args):
    """Train 2-layer MLP probe (768→256→1) with PyTorch."""
    import torch
    import torch.nn as nn
    from sklearn.metrics import classification_report, f1_score
    from sklearn.model_selection import StratifiedKFold

    input_dim = X_scaled.shape[1]
    hidden_dim = 256

    class MLPProbe(nn.Module):
        def __init__(self):
            super().__init__()
            self.fc1 = nn.Linear(input_dim, hidden_dim)
            self.relu = nn.ReLU()
            self.dropout = nn.Dropout(0.2)
            self.fc2 = nn.Linear(hidden_dim, 1)

        def forward(self, x):
            x = self.fc1(x)
            x = self.relu(x)
            x = self.dropout(x)
            x = self.fc2(x)
            return x.squeeze(-1)

    device = "cuda" if torch.cuda.is_available() else "cpu"

    # Class weights for balanced training
    n_pos = (y == 1).sum()
    n_neg = (y == 0).sum()
    pos_weight = torch.tensor([n_neg / n_pos], dtype=torch.float32).to(device)

    # 5-fold cross-validation
    print("\n=== 5-fold Cross-Validation (MLP 768→256→1) ===")
    skf = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)
    all_preds = np.zeros(len(y), dtype=np.int32)

    for fold, (train_idx, val_idx) in enumerate(skf.split(X_scaled, y)):
        mlp = MLPProbe().to(device)
        optimizer = torch.optim.Adam(mlp.parameters(), lr=1e-3, weight_decay=1e-4)
        criterion = nn.BCEWithLogitsLoss(pos_weight=pos_weight)

        X_train = torch.tensor(X_scaled[train_idx], dtype=torch.float32).to(device)
        y_train = torch.tensor(y[train_idx], dtype=torch.float32).to(device)
        X_val = torch.tensor(X_scaled[val_idx], dtype=torch.float32).to(device)

        # Train
        mlp.train()
        for epoch in range(50):
            optimizer.zero_grad()
            logits = mlp(X_train)
            loss = criterion(logits, y_train)
            loss.backward()
            optimizer.step()

        # Predict
        mlp.eval()
        with torch.no_grad():
            val_logits = mlp(X_val).cpu().numpy()
            val_preds = (val_logits > 0).astype(np.int32)
            all_preds[val_idx] = val_preds

        fold_f1 = f1_score(y[val_idx], val_preds, average="macro")
        print(f"  Fold {fold+1}: F1={fold_f1:.3f}")

    print(classification_report(y, all_preds, target_names=["authentic", "manipulated"], digits=3))
    cv_f1 = f1_score(y, all_preds, average="macro")
    print(f"Macro-F1: {cv_f1:.3f}")

    # Per-generator metrics
    _print_per_generator_metrics(y, all_preds, filenames_list, labels, sources)

    # Train final model on all data
    print("\nTraining final MLP on all data...")
    final_mlp = MLPProbe().to(device)
    optimizer = torch.optim.Adam(final_mlp.parameters(), lr=1e-3, weight_decay=1e-4)
    criterion = nn.BCEWithLogitsLoss(pos_weight=pos_weight)

    X_all = torch.tensor(X_scaled, dtype=torch.float32).to(device)
    y_all = torch.tensor(y, dtype=torch.float32).to(device)

    final_mlp.train()
    for epoch in range(80):
        optimizer.zero_grad()
        logits = final_mlp(X_all)
        loss = criterion(logits, y_all)
        loss.backward()
        optimizer.step()
        if (epoch + 1) % 20 == 0:
            print(f"  Epoch {epoch+1}: loss={loss.item():.4f}")

    # Extract weights as numpy for inference (no PyTorch dependency at runtime)
    final_mlp.eval()
    final_mlp.cpu()
    w1 = final_mlp.fc1.weight.detach().numpy()  # (256, 768)
    b1 = final_mlp.fc1.bias.detach().numpy()    # (256,)
    w2 = final_mlp.fc2.weight.detach().numpy()  # (1, 256)
    b2 = final_mlp.fc2.bias.detach().numpy()    # (1,)

    # Transform W1 to work on raw (unscaled) embeddings:
    # scaled_x = (x - mean) / scale
    # fc1(scaled_x) = W1 @ scaled_x + b1 = W1 @ ((x - mean) / scale) + b1
    #               = (W1 / scale) @ x + (b1 - W1 @ (mean / scale))
    w1_raw = w1 / scaler.scale_[np.newaxis, :]  # (256, 768)
    b1_raw = b1 - w1_raw @ scaler.mean_         # (256,)

    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
    np.savez(
        args.output,
        probe_type="mlp",
        w1=w1_raw.astype(np.float32),
        b1=b1_raw.astype(np.float32),
        w2=w2.astype(np.float32),
        b2=b2.astype(np.float32),
    )
    print(f"\nSaved MLP probe to {args.output}")
    print(f"  W1: {w1_raw.shape}, b1: {b1_raw.shape}")
    print(f"  W2: {w2.shape}, b2: {b2.shape}")
    print(f"  CV Macro-F1: {cv_f1:.3f}")

    # Sanity check
    h = np.maximum(0, X @ w1_raw.T + b1_raw)  # ReLU
    logits = h @ w2.T + b2
    probs = 1 / (1 + np.exp(-logits.flatten()))
    print(f"  Auth mean prob: {probs[y==0].mean():.3f}")
    print(f"  Manip mean prob: {probs[y==1].mean():.3f}")


def _train_linear(X, X_scaled, y, scaler, filenames_list, labels, sources, args):
    """Train LogisticRegression probe (backward compatible)."""
    from sklearn.linear_model import LogisticRegression
    from sklearn.model_selection import cross_val_predict
    from sklearn.metrics import classification_report, f1_score

    print("\n=== 5-fold Cross-Validation (Linear) ===")
    lr = LogisticRegression(C=1.0, max_iter=1000, class_weight="balanced", random_state=42)
    y_pred = cross_val_predict(lr, X_scaled, y, cv=5)
    print(classification_report(y, y_pred, target_names=["authentic", "manipulated"], digits=3))
    f1 = f1_score(y, y_pred, average="macro")
    print(f"Macro-F1: {f1:.3f}")

    _print_per_generator_metrics(y, y_pred, filenames_list, labels, sources)

    lr.fit(X_scaled, y)
    w_scaled = lr.coef_[0]
    b_scaled = lr.intercept_[0]
    w_raw = w_scaled / scaler.scale_
    b_raw = b_scaled - (scaler.mean_ / scaler.scale_) @ w_scaled

    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
    np.savez(
        args.output,
        weights=w_raw.astype(np.float32),
        bias=np.array([b_raw], dtype=np.float32),
    )
    print(f"\nSaved linear probe to {args.output}")
    print(f"  Weights: {w_raw.shape}, bias: {b_raw:.4f}")
    print(f"  Macro-F1: {f1:.3f}")

    logits = X @ w_raw + b_raw
    probs = 1 / (1 + np.exp(-logits))
    print(f"  Auth mean prob: {probs[y==0].mean():.3f}")
    print(f"  Manip mean prob: {probs[y==1].mean():.3f}")


def _print_per_generator_metrics(y, y_pred, filenames_list, labels, sources):
    """Print F1 scores broken down by generator/source."""
    from sklearn.metrics import f1_score
    from collections import defaultdict

    # Group by ground truth class and source
    generator_results = defaultdict(lambda: {"y_true": [], "y_pred": []})

    for i, fn in enumerate(filenames_list):
        gt = labels.get(fn, "unknown")
        src = sources.get(fn, "unknown")
        # For AI images, try to extract generator from source
        if gt == "ai_generated":
            key = f"AI:{src.split('/')[0] if '/' in src else src}"
        elif gt == "tampered":
            key = f"TAMP:{src.split('/')[0] if '/' in src else src}"
        else:
            key = "authentic"
        generator_results[key]["y_true"].append(y[i])
        generator_results[key]["y_pred"].append(y_pred[i])

    print("\n=== Per-Source Metrics ===")
    print(f"{'Source':<35} {'Count':>6} {'Acc':>6} {'F1':>6}")
    print("-" * 55)
    for key in sorted(generator_results.keys()):
        data = generator_results[key]
        yt = np.array(data["y_true"])
        yp = np.array(data["y_pred"])
        acc = (yt == yp).mean()
        # F1 only makes sense within-class, show accuracy instead
        print(f"{key:<35} {len(yt):>6} {acc:>6.1%}")


if __name__ == "__main__":
    main()
