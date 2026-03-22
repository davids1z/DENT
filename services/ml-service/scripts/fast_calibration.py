#!/usr/bin/env python3
"""
Fast calibration — runs forensic pipeline DIRECTLY (no HTTP overhead).

Skips heavy modules (VAE, CNN, Semantic/Gemini) and runs only fast ones:
metadata, modification, optical, spectral, clip, prnu, ai_generation.

Expected: ~5-10s per image on GPU vs 100s+ through HTTP API.

Usage:
  cd /root/DENT/services/ml-service
  export AWS_ACCESS_KEY_ID=... AWS_SECRET_ACCESS_KEY=... AWS_DEFAULT_REGION=eu-central-1
  python3 -m scripts.fast_calibration \
    --bucket dent-calibration-data \
    --output data/labeled_dataset.jsonl \
    --resume
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import io
import json
import os
import sys
import time
from pathlib import Path

import boto3

try:
    from tqdm import tqdm
except ImportError:
    def tqdm(it, **kw):
        total = kw.get("total", "?")
        for i, x in enumerate(it, 1):
            if i % 10 == 0:
                print(f"  [{i}/{total}]", flush=True)
            yield x

S3_PREFIX = "processed"
VALID_CLASSES = {"authentic", "ai_generated", "tampered"}

# Heavy modules to skip — saves 80%+ of processing time
SKIP_MODULES = {
    "semantic_forensics",          # Gemini API call (~10-30s)
    "vae_reconstruction",          # VAE encode/decode + VGG16 (~30-40s)
    "deep_modification_detection", # CAT-Net/TruFor (~20s)
}


def load_labels(s3, bucket: str) -> dict[str, str]:
    resp = s3.get_object(Bucket=bucket, Key=f"{S3_PREFIX}/labels.csv")
    content = resp["Body"].read().decode("utf-8")
    labels = {}
    for row in csv.DictReader(io.StringIO(content)):
        fn = row.get("filename", "").strip()
        gt = row.get("ground_truth", "").strip().lower()
        if fn and gt in VALID_CLASSES:
            labels[fn] = gt
    return labels


def load_existing(path: str) -> set[str]:
    done = set()
    if os.path.exists(path):
        with open(path) as f:
            for line in f:
                try:
                    done.add(json.loads(line).get("id", ""))
                except json.JSONDecodeError:
                    pass
    return done


def result_to_jsonl(filename: str, gt: str, report) -> dict:
    modules = {}
    for mod in report.modules:
        findings = []
        for f in mod.findings:
            findings.append({
                "code": f.code,
                "confidence": f.confidence,
                "risk_score": f.risk_score,
            })
        modules[mod.module_name] = {
            "risk_score": mod.risk_score,
            "findings": findings,
        }
    return {
        "id": filename,
        "ground_truth": gt,
        "overall_risk_score": report.overall_risk_score,
        "modules": modules,
    }


async def main():
    parser = argparse.ArgumentParser(description="Fast direct-pipeline calibration")
    parser.add_argument("--bucket", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--region", default="eu-central-1")
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()

    # Import pipeline directly — no HTTP
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from app.forensics.pipeline import ForensicPipeline

    print("Initializing forensic pipeline (direct, no HTTP)...")
    pipeline = ForensicPipeline(
        semantic_enabled=False,     # Skip Gemini
        cnn_enabled=False,          # Skip CAT-Net/TruFor
        vae_recon_enabled=False,    # Skip VAE (heaviest module)
        # Keep these fast modules:
        aigen_enabled=True,         # Swin Transformer (~5s on GPU)
        clip_ai_enabled=True,       # CLIP (~2s)
        spectral_enabled=True,      # FFT (~1s)
        optical_enabled=True,       # Moire/perspective (~1s)
        prnu_enabled=True,          # PRNU (~1s)
    )
    print("Pipeline ready!")

    s3 = boto3.client("s3", region_name=args.region)

    labels = load_labels(s3, args.bucket)
    print(f"Labels: {len(labels)} ({sum(1 for v in labels.values() if v=='authentic')} auth, "
          f"{sum(1 for v in labels.values() if v=='ai_generated')} ai, "
          f"{sum(1 for v in labels.values() if v=='tampered')} tamp)")

    done = load_existing(args.output) if args.resume else set()
    if done:
        print(f"Resume: {len(done)} already done")

    to_process = [(fn, gt) for fn, gt in labels.items() if fn not in done]
    print(f"To process: {len(to_process)}")

    if not to_process:
        print("Nothing to do!")
        return

    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    mode = "a" if args.resume else "w"
    processed = 0
    errors = 0

    with open(args.output, mode) as out_f:
        for filename, gt in tqdm(to_process, desc="Analyzing", total=len(to_process)):
            try:
                # Download from S3
                resp = s3.get_object(Bucket=args.bucket, Key=f"{S3_PREFIX}/{filename}")
                image_bytes = resp["Body"].read()

                # Run pipeline DIRECTLY — no HTTP overhead
                report = await pipeline.analyze(image_bytes, filename)

                record = result_to_jsonl(filename, gt, report)
                out_f.write(json.dumps(record, ensure_ascii=False) + "\n")
                out_f.flush()
                processed += 1

            except Exception as e:
                errors += 1
                if errors <= 10:
                    print(f"  Error {filename}: {e}")

    print(f"\nDone: {processed} processed, {errors} errors")
    print(f"Output: {args.output}")

    # Count classes
    counts = {}
    with open(args.output) as f:
        for line in f:
            try:
                gt = json.loads(line).get("ground_truth", "?")
                counts[gt] = counts.get(gt, 0) + 1
            except:
                pass
    for cls in VALID_CLASSES:
        print(f"  {cls}: {counts.get(cls, 0)}")

    print(f"\nNext: python3 -m scripts.calibrate_ghost --data {args.output} --tiers 1,2")


if __name__ == "__main__":
    asyncio.run(main())
