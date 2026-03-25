#!/usr/bin/env python3
"""Train DINOv2 linear probe for AI image detection from S3 calibration data.

Extracts DINOv2-base CLS embeddings from calibration images on S3,
trains a logistic regression probe, saves weights as dinov2_probe_weights.npz.

Usage:
  cd /root/DENT/services/ml-service
  python3 -m scripts.train_dinov2_probe \
    --bucket dent-calibration-data \
    --output models/dinov2/dinov2_probe_weights.npz
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

S3_PREFIX = "processed"
VALID_CLASSES = {"authentic", "ai_generated", "tampered"}


def main():
    parser = argparse.ArgumentParser(description="Train DINOv2 AI detection probe")
    parser.add_argument("--bucket", required=True)
    parser.add_argument("--output", default="models/dinov2/dinov2_probe_weights.npz")
    parser.add_argument("--region", default="eu-central-1")
    parser.add_argument("--max-images", type=int, default=0, help="Limit images (0=all)")
    args = parser.parse_args()

    import torch
    from transformers import AutoImageProcessor, AutoModel

    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"Device: {device}")

    print("Loading DINOv2-base...")
    processor = AutoImageProcessor.from_pretrained("facebook/dinov2-base")
    model = AutoModel.from_pretrained("facebook/dinov2-base").to(device)
    model.eval()
    print("DINOv2 loaded")

    # Load labels from S3
    s3 = boto3.client("s3", region_name=args.region)
    resp = s3.get_object(Bucket=args.bucket, Key=f"{S3_PREFIX}/labels.csv")
    content = resp["Body"].read().decode("utf-8")
    labels = {}
    for row in csv.DictReader(io.StringIO(content)):
        fn = row.get("filename", "").strip()
        gt = row.get("ground_truth", "").strip().lower()
        if fn and gt in VALID_CLASSES:
            labels[fn] = gt

    items = sorted(labels.items())
    if args.max_images > 0:
        items = items[:args.max_images]
    print(f"Processing {len(items)} images")

    # Extract embeddings
    embeddings = []
    y_labels = []
    errors = 0

    for filename, gt in tqdm(items, desc="Extracting DINOv2 embeddings", total=len(items)):
        try:
            resp = s3.get_object(Bucket=args.bucket, Key=f"{S3_PREFIX}/{filename}")
            image_bytes = resp["Body"].read()
            img = Image.open(io.BytesIO(image_bytes)).convert("RGB")

            inputs = processor(images=img, return_tensors="pt").to(device)
            with torch.no_grad():
                outputs = model(**inputs)
                # CLS token from last hidden state
                cls_embedding = outputs.last_hidden_state[:, 0, :]  # (1, 768)
                embedding = cls_embedding.cpu().numpy().flatten()  # (768,)
                # L2 normalize
                norm = np.linalg.norm(embedding)
                if norm > 0:
                    embedding = embedding / norm

            embeddings.append(embedding)
            y_labels.append(0 if gt == "authentic" else 1)
        except Exception as e:
            errors += 1
            if errors <= 5:
                print(f"  Error {filename}: {e}")

    X = np.array(embeddings, dtype=np.float32)
    y = np.array(y_labels, dtype=np.int32)
    print(f"\nEmbeddings: {X.shape} ({errors} errors)")
    print(f"Class balance: {(y==0).sum()} authentic, {(y==1).sum()} manipulated")

    # Train logistic regression probe
    from sklearn.linear_model import LogisticRegression
    from sklearn.model_selection import cross_val_predict
    from sklearn.metrics import classification_report, f1_score
    from sklearn.preprocessing import StandardScaler

    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X)

    print("\n=== 5-fold Cross-Validation ===")
    lr = LogisticRegression(C=1.0, max_iter=1000, class_weight="balanced", random_state=42)
    y_pred = cross_val_predict(lr, X_scaled, y, cv=5)
    print(classification_report(y, y_pred, target_names=["authentic", "manipulated"], digits=3))
    f1 = f1_score(y, y_pred, average="macro")
    print(f"Macro-F1: {f1:.3f}")

    # Train final model
    lr.fit(X_scaled, y)

    # Transform weights to work on raw L2-normalized embeddings
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
    print(f"\nSaved probe to {args.output}")
    print(f"  Weights: {w_raw.shape}, bias: {b_raw:.4f}")
    print(f"  Macro-F1: {f1:.3f}")

    # Sanity check
    logits = X @ w_raw + b_raw
    probs = 1 / (1 + np.exp(-logits))
    print(f"  Auth mean prob: {probs[y==0].mean():.3f}")
    print(f"  Manip mean prob: {probs[y==1].mean():.3f}")


if __name__ == "__main__":
    main()
