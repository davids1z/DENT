#!/usr/bin/env python3
"""
Fast calibration — runs forensic pipeline DIRECTLY (no HTTP overhead).

Runs ALL 17 modules (including CommFor, NPR, Mesorch, CNN/TruFor, VAE)
except Gemini VLM (API cost). Direct pipeline call = ~2-10s/image on GPU.

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
    parser.add_argument("--worker-id", type=int, default=0, help="Worker index for parallel calibration")
    parser.add_argument("--total-workers", type=int, default=1, help="Total number of parallel workers")
    args = parser.parse_args()

    # Import pipeline directly — no HTTP
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

    # Ensure model weights are downloaded (vast.ai instances start fresh)
    models_dir = Path(__file__).resolve().parent.parent / "models"
    models_dir.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("DENT_FORENSICS_MODEL_CACHE_DIR", str(models_dir))

    # NPR weights (~6MB, from GitHub)
    npr_dir = models_dir / "npr"
    npr_dir.mkdir(parents=True, exist_ok=True)
    npr_path = npr_dir / "NPR.pth"
    if not npr_path.exists():
        print("Downloading NPR weights (~6MB)...")
        import urllib.request
        urllib.request.urlretrieve(
            "https://github.com/chuangchuangtan/NPR-DeepfakeDetection/raw/main/NPR.pth",
            str(npr_path),
        )
        print(f"NPR weights saved to {npr_path}")

    # Mesorch weights (~976MB, from Google Drive)
    mesorch_dir = models_dir / "cnn" / "mesorch"
    mesorch_dir.mkdir(parents=True, exist_ok=True)
    mesorch_path = mesorch_dir / "mesorch-98.pth"
    if not mesorch_path.exists():
        print("Downloading Mesorch weights (~976MB)...")
        try:
            import gdown
            gdown.download(
                id="1PJxKteinMyaAYokKy0JhuzBnBc6bGsau",
                output=str(mesorch_path), quiet=False,
            )
        except Exception as e:
            print(f"WARNING: Mesorch download failed: {e}")

    from app.forensics.pipeline import ForensicPipeline

    print("Initializing forensic pipeline (direct, no HTTP)...")
    pipeline = ForensicPipeline(
        semantic_enabled=False,     # Skip Gemini (API cost)
        cnn_enabled=True,           # TruFor (tampering detection), CatNet disabled in code
        mesorch_enabled=True,       # Mesorch (AAAI 2025, JPEG F1=0.774)
        vae_recon_enabled=True,     # VAE snap-back (AI detection)
        aigen_enabled=True,         # Swin Transformer ensemble
        community_forensics_enabled=True,  # CommFor (CVPR 2025, 4803 generators)
        npr_enabled=True,           # NPR (CVPR 2024, 92.2% accuracy)
        clip_ai_enabled=True,       # CLIP probe
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
    # Parallel worker split: each worker processes only its share
    if args.total_workers > 1:
        to_process = [
            (fn, gt) for i, (fn, gt) in enumerate(to_process)
            if i % args.total_workers == args.worker_id
        ]
        print(f"Worker {args.worker_id}/{args.total_workers}: {len(to_process)} images assigned")
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
