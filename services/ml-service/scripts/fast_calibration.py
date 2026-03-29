#!/usr/bin/env python3
"""
Fast calibration — runs forensic pipeline DIRECTLY (no HTTP overhead).

Module config matches production (docker-compose.server.yml):
  Enabled: CLIP, CommFor, EfficientNet, SAFE, DINOv2, B-Free, SPAI, Mesorch, PRNU
  Disabled: CNN/TruFor, optical, semantic, spectral, VAE, aigen, NPR

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

S3_PREFIX = "train_v7"
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

    # SAFE checkpoint (~6MB, from GitHub)
    safe_dir = models_dir / "safe_ai"
    safe_dir.mkdir(parents=True, exist_ok=True)
    safe_path = safe_dir / "checkpoint-best.pth"
    if not safe_path.exists():
        print("Downloading SAFE checkpoint (~6MB)...")
        try:
            import urllib.request
            urllib.request.urlretrieve(
                "https://github.com/Purdue-M2/SAFE/raw/main/ckpt/checkpoint-best.pth",
                str(safe_path),
            )
            print(f"SAFE checkpoint saved to {safe_path}")
        except Exception as e:
            print(f"WARNING: SAFE download failed: {e}")

    # SPAI TorchScript (~560MB, from S3)
    spai_dir = models_dir / "spai"
    spai_dir.mkdir(parents=True, exist_ok=True)
    spai_path = spai_dir / "spai_full.pt"
    if not spai_path.exists():
        print("Downloading SPAI TorchScript (~560MB from S3)...")
        try:
            s3_dl = boto3.client("s3", region_name=args.region)
            s3_dl.download_file(args.bucket, "models/spai_full.pt", str(spai_path))
            print(f"SPAI model saved to {spai_path}")
        except Exception as e:
            print(f"WARNING: SPAI download failed: {e}")

    # Probe weights (should be in repo from git clone)
    dinov2_dir = models_dir / "dinov2"
    dinov2_dir.mkdir(parents=True, exist_ok=True)
    dinov2_probe = dinov2_dir / "dinov2_probe_weights.npz"
    if not dinov2_probe.exists():
        print("WARNING: DINOv2 probe weights not found — DINOv2 will use heuristic fallback")

    clip_dir = models_dir / "clip_ai"
    clip_dir.mkdir(parents=True, exist_ok=True)
    clip_probe = clip_dir / "probe_weights.npz"
    if not clip_probe.exists():
        print("WARNING: CLIP probe weights not found — CLIP will use heuristic fallback")

    from app.forensics.pipeline import ForensicPipeline

    print("Initializing forensic pipeline (direct, no HTTP)...")
    # Module config MUST match production (docker-compose.server.yml)
    pipeline = ForensicPipeline(
        # Enabled on production
        clip_ai_enabled=True,
        community_forensics_enabled=True,
        efficientnet_ai_enabled=True,
        safe_ai_enabled=True,
        dinov2_ai_enabled=True,
        bfree_enabled=True,
        spai_enabled=True,
        mesorch_enabled=True,
        prnu_enabled=True,
        # Disabled on production
        semantic_enabled=False,
        cnn_enabled=False,
        vae_recon_enabled=False,
        aigen_enabled=False,
        npr_enabled=False,
        spectral_enabled=False,
        optical_enabled=False,
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

    to_process = sorted([(fn, gt) for fn, gt in labels.items() if fn not in done])
    # Parallel worker split: each worker processes only its share
    # IMPORTANT: sorted() ensures deterministic order across Python versions
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
