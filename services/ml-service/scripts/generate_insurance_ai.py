#!/usr/bin/env python3
"""
Generate AI insurance-domain images using open-weight models on GPU + download
from OpenFake/JourneyDB for closed-source generators.

Modes:
  local    — 15 generators on vast.ai GPU (2,200 images)
  openfake — OpenFake + JourneyDB download (3,300 images)
  both     — run both

All images go directly to S3. Supports --resume.

Local generators (15, from 2022-2025):
  SD 1.5, SD 2.1, DeepFloyd IF, SDXL, Playground v2.5, PixArt-Sigma,
  Kolors, AuraFlow v0.3, SD 3.5 Medium, Flux schnell, Flux dev,
  HiDream I1, CogView-3, Qwen-Image (OmniGen), HunyuanImage

OpenFake download (9 closed-source):
  DALL-E 3, Midjourney v6, GPT Image 1, Grok 2, Ideogram 3.0,
  Imagen 4, Stable Diffusion (razne)

JourneyDB download:
  Midjourney (all versions)

Usage (vast.ai GPU):
  python3 -m scripts.generate_insurance_ai \
      --mode local --target 2200 \
      --bucket dent-calibration-data --output-prefix raw_v8/ai_generated

  python3 -m scripts.generate_insurance_ai \
      --mode openfake --target 3300 \
      --bucket dent-calibration-data --output-prefix raw_v8/ai_generated
"""

from __future__ import annotations

import argparse
import csv
import io
import os
import random
import sys
import time
import uuid
from pathlib import Path

try:
    import boto3
except ImportError:
    boto3 = None

try:
    from PIL import Image
except ImportError:
    Image = None


# ── 80+ Insurance prompts ────────────────────────────────────────────

INSURANCE_PROMPTS = {
    "car_damage": [
        "photograph of a car with large dent on front bumper",
        "close up deep scratches car door",
        "broken windshield hail damage",
        "rear end collision sedan",
        "side mirror broken parking",
        "cracked headlight fender bender",
        "SUV dented hood tree branch",
        "rust damage undercarriage",
        "multiple dents car roof hailstorm",
        "paint peeling accident scrape",
        "damaged wheel rim pothole",
        "bumper hanging off collision",
        "total loss car wreck",
        "minor scratch parking lot",
        "car fire damage engine",
        "flooded car interior",
        "tire blowout rim damage",
        "windshield crack spider web",
        "car door won't close bent frame",
        "dashcam footage car accident aftermath",
    ],
    "house_damage": [
        "flooded living room water damage walls",
        "house roof missing tiles storm",
        "fire damaged kitchen burned cabinets",
        "basement mold water leak",
        "cracked foundation wall",
        "collapsed ceiling water damage",
        "tree fallen house roof",
        "tornado debris home",
        "water stains ceiling pipe burst",
        "smoke damage walls living room",
        "broken window storm residential",
        "earthquake damage house wall",
        "frozen pipe burst water damage",
        "roof damage missing shingles close up",
        "garage door damaged storm",
    ],
    "medical": [
        "bruised forearm medical documentation",
        "bandaged hand hospital",
        "swollen ankle ice pack",
        "neck brace car accident",
        "arm plaster cast fracture",
        "burn injury bandage",
        "knee brace sport injury",
        "stitches wound forearm",
        "black eye injury photo",
        "shoulder sling arm",
    ],
    "documents": [
        "scanned car repair invoice",
        "hospital medical bill",
        "insurance claim form filled",
        "mechanic repair estimate",
        "receipt auto body shop",
        "pharmacy prescription receipt",
        "building contractor quote document",
        "dental bill receipt scan",
        "physical therapy invoice",
        "emergency room bill scanned",
    ],
    "general": [
        "blurry phone photo car accident night",
        "overexposed damaged property photo",
        "low quality snapshot water damage",
        "dark grainy house damage storm",
        "amateur smartphone scratched car",
        "security camera footage damage",
        "video still frame accident",
        "drone aerial damage house",
        "before after damage comparison",
        "inspection photo building damage",
    ],
}

STYLE_VARIATIONS = [
    "professional photo",
    "phone camera photo",
    "night photo",
    "close up detail",
    "wide angle view",
]


def get_all_prompts() -> list[str]:
    """Build full prompt list with style variations."""
    prompts = []
    for category_prompts in INSURANCE_PROMPTS.values():
        for prompt in category_prompts:
            # Add style variations
            for style in STYLE_VARIATIONS:
                prompts.append(f"{prompt}, {style}")
    return prompts


# ── Local generators (15 models, 2022-2025) ──────────────────────────

LOCAL_GENERATORS = {
    "sd15": {
        "model_id": "stable-diffusion-v1-5/stable-diffusion-v1-5",
        "pipeline": "StableDiffusionPipeline",
        "params": {"num_inference_steps": 30, "guidance_scale": 7.5},
        "dtype": "float16",
        "target": 100,
    },
    "sd21": {
        "model_id": "stabilityai/stable-diffusion-2-1",
        "pipeline": "StableDiffusionPipeline",
        "params": {"num_inference_steps": 30, "guidance_scale": 7.5},
        "dtype": "float16",
        "target": 100,
    },
    "deepfloyd_if": {
        "model_id": "DeepFloyd/IF-I-M-v1.0",
        "pipeline": "IFPipeline",
        "params": {"num_inference_steps": 50, "guidance_scale": 7.0},
        "dtype": "float16",
        "target": 100,
    },
    "sdxl": {
        "model_id": "stabilityai/stable-diffusion-xl-base-1.0",
        "pipeline": "StableDiffusionXLPipeline",
        "params": {"num_inference_steps": 30, "guidance_scale": 7.5},
        "dtype": "float16",
        "target": 200,
    },
    "playground_v25": {
        "model_id": "playgroundai/playground-v2.5-1024px-aesthetic",
        "pipeline": "StableDiffusionXLPipeline",
        "params": {"num_inference_steps": 30, "guidance_scale": 3.0},
        "dtype": "float16",
        "target": 100,
    },
    "pixart_sigma": {
        "model_id": "PixArt-alpha/PixArt-Sigma-XL-2-1024-MS",
        "pipeline": "PixArtSigmaPipeline",
        "params": {"num_inference_steps": 20, "guidance_scale": 4.5},
        "dtype": "float16",
        "target": 150,
    },
    "kolors": {
        "model_id": "Kwai-Kolors/Kolors-diffusers",
        "pipeline": "KolorsPipeline",
        "params": {"num_inference_steps": 25, "guidance_scale": 5.0},
        "dtype": "float16",
        "target": 100,
    },
    "auraflow": {
        "model_id": "fal/AuraFlow-v0.3",
        "pipeline": "AuraFlowPipeline",
        "params": {"num_inference_steps": 25, "guidance_scale": 3.5},
        "dtype": "float16",
        "target": 100,
    },
    "sd35_medium": {
        "model_id": "stabilityai/stable-diffusion-3.5-medium",
        "pipeline": "StableDiffusion3Pipeline",
        "params": {"num_inference_steps": 28, "guidance_scale": 5.0},
        "dtype": "bfloat16",
        "target": 200,
    },
    "flux_schnell": {
        "model_id": "black-forest-labs/FLUX.1-schnell",
        "pipeline": "FluxPipeline",
        "params": {"num_inference_steps": 4, "guidance_scale": 0.0},
        "dtype": "bfloat16",
        "target": 300,
    },
    "flux_dev": {
        "model_id": "black-forest-labs/FLUX.1-dev",
        "pipeline": "FluxPipeline",
        "params": {"num_inference_steps": 28, "guidance_scale": 3.5},
        "dtype": "bfloat16",
        "target": 200,
    },
    "hidream": {
        "model_id": "HiDream-ai/HiDream-I1-Dev",
        "pipeline": "AutoPipelineForText2Image",
        "params": {"num_inference_steps": 28, "guidance_scale": 5.0},
        "dtype": "bfloat16",
        "target": 150,
    },
    "cogview3": {
        "model_id": "THUDM/CogView-3-Plus-3B",
        "pipeline": "CogView3PlusPipeline",
        "params": {"num_inference_steps": 50, "guidance_scale": 7.0},
        "dtype": "float16",
        "target": 100,
    },
    "omnigen": {
        "model_id": "Shitao/OmniGen-v1",
        "pipeline": "AutoPipelineForText2Image",
        "params": {"num_inference_steps": 30, "guidance_scale": 3.0},
        "dtype": "float16",
        "target": 100,
    },
    "hunyuan": {
        "model_id": "Tencent-Hunyuan/HunyuanDiT-v1.2-Diffusers",
        "pipeline": "HunyuanDiTPipeline",
        "params": {"num_inference_steps": 50, "guidance_scale": 5.0},
        "dtype": "float16",
        "target": 100,
    },
}

# OpenFake generators (closed-source, from HuggingFace dataset)
# Names MUST match model field in OpenFake dataset exactly
OPENFAKE_GENERATORS = {
    "dalle-3": 500,
    "midjourney-6": 500,
    "gpt-image-1": 400,
    "grok-2-image-1212": 300,
    "ideogram-3.0": 300,
    "imagen-4.0": 300,
    "sd-3.5": 300,
}

# JourneyDB — Midjourney images from HuggingFace
JOURNEYDB_TARGET = 400

# DALL-E community dataset
DALLE_COMMUNITY_TARGET = 300


# ── Helpers ──────────────────────────────────────────────────────────

def _standardize_image(img: Image.Image) -> bytes | None:
    """Convert to JPEG, strip EXIF, resize if needed."""
    try:
        if img.mode != "RGB":
            img = img.convert("RGB")
        w, h = img.size
        if max(w, h) > 1024:
            ratio = 1024 / max(w, h)
            img = img.resize((int(w * ratio), int(h * ratio)), Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=90, optimize=True)
        data = buf.getvalue()
        return data if len(data) >= 3000 else None
    except Exception:
        return None


def _get_existing_counts(s3, bucket: str, prefix: str) -> dict[str, int]:
    """Load existing labels.csv and count per generator."""
    counts = {}
    try:
        resp = s3.get_object(Bucket=bucket, Key=f"{prefix}/labels.csv")
        content = resp["Body"].read().decode()
        reader = csv.DictReader(io.StringIO(content))
        for row in reader:
            gen = row.get("generator", "unknown")
            counts[gen] = counts.get(gen, 0) + 1
    except Exception:
        pass
    return counts


def _load_existing_records(s3, bucket: str, prefix: str) -> list[dict]:
    """Load existing labels.csv records for resume."""
    try:
        resp = s3.get_object(Bucket=bucket, Key=f"{prefix}/labels.csv")
        content = resp["Body"].read().decode()
        records = []
        reader = csv.DictReader(io.StringIO(content))
        for row in reader:
            records.append(dict(row))
        return records
    except Exception:
        return []


def _save_labels(records: list[dict], s3, bucket: str, prefix: str):
    """Save labels.csv to S3."""
    csv_buf = io.StringIO()
    writer = csv.DictWriter(
        csv_buf,
        fieldnames=["filename", "ground_truth", "generator", "source"],
    )
    writer.writeheader()
    for rec in records:
        writer.writerow({
            "filename": rec.get("filename", ""),
            "ground_truth": rec.get("ground_truth", "ai_generated"),
            "generator": rec.get("generator", ""),
            "source": rec.get("source", ""),
        })
    s3.put_object(
        Bucket=bucket,
        Key=f"{prefix}/labels.csv",
        Body=csv_buf.getvalue().encode(),
        ContentType="text/csv",
    )


# ── Local generation ─────────────────────────────────────────────────

def generate_local(args):
    """Generate images locally on GPU using 15 open-weight models."""
    import torch

    s3 = boto3.client("s3", region_name=args.region)
    all_prompts = get_all_prompts()
    random.shuffle(all_prompts)

    # Resume
    records = _load_existing_records(s3, args.bucket, args.output_prefix) if args.resume else []
    existing_counts = {}
    for r in records:
        gen = r.get("generator", "")
        existing_counts[gen] = existing_counts.get(gen, 0) + 1

    # Scale targets
    total_target_sum = sum(g["target"] for g in LOCAL_GENERATORS.values())
    scale = args.target / total_target_sum if total_target_sum > 0 else 1.0

    total_generated = len(records)

    for gen_name, gen_config in LOCAL_GENERATORS.items():
        gen_target = int(gen_config["target"] * scale)
        existing = existing_counts.get(gen_name, 0)

        if existing >= gen_target:
            print(f"\n=== {gen_name} — SKIP (already {existing}/{gen_target}) ===")
            continue

        remaining = gen_target - existing
        print(f"\n=== {gen_name} (need: {remaining}, target: {gen_target}) ===")

        try:
            # Dynamic import of pipeline
            dtype = getattr(torch, gen_config["dtype"])
            pipe = _load_pipeline(gen_config["pipeline"], gen_config["model_id"], dtype)

            if pipe is None:
                print(f"  Skipping {gen_name}: pipeline not available")
                continue

            prompt_idx = 0
            gen_count = 0

            for i in range(remaining + 20):  # buffer for failures
                if gen_count >= remaining:
                    break

                prompt = all_prompts[prompt_idx % len(all_prompts)]
                prompt_idx += 1

                try:
                    result = pipe(prompt, **gen_config["params"])
                    image = result.images[0]

                    jpeg_bytes = _standardize_image(image)
                    if jpeg_bytes is None:
                        continue

                    filename = f"{uuid.uuid4().hex[:12]}.jpg"
                    s3.put_object(
                        Bucket=args.bucket,
                        Key=f"{args.output_prefix}/{filename}",
                        Body=jpeg_bytes,
                        ContentType="image/jpeg",
                        Metadata={"generator": gen_name, "prompt": prompt[:200]},
                    )

                    records.append({
                        "filename": filename,
                        "ground_truth": "ai_generated",
                        "generator": gen_name,
                        "source": "local",
                    })
                    gen_count += 1
                    total_generated += 1

                    if gen_count % 25 == 0:
                        print(f"  [{gen_count}/{remaining}] {gen_name}")
                        _save_labels(records, s3, args.bucket, args.output_prefix)

                except Exception as e:
                    print(f"  Error: {e}")
                    continue

            # Free VRAM
            del pipe
            torch.cuda.empty_cache()
            print(f"  {gen_name}: generated {gen_count} images, freed VRAM")

        except Exception as e:
            print(f"  Failed to load {gen_name}: {e}")
            continue

    _save_labels(records, s3, args.bucket, args.output_prefix)
    print(f"\nLocal generation done: {total_generated} total images")
    return records


def _load_pipeline(pipeline_name: str, model_id: str, dtype):
    """Dynamically load a diffusion pipeline."""
    import diffusers

    # Map pipeline names to classes
    pipeline_map = {
        "StableDiffusionPipeline": "StableDiffusionPipeline",
        "StableDiffusionXLPipeline": "StableDiffusionXLPipeline",
        "StableDiffusion3Pipeline": "StableDiffusion3Pipeline",
        "FluxPipeline": "FluxPipeline",
        "PixArtSigmaPipeline": "PixArtSigmaPipeline",
        "KolorsPipeline": "KolorsPipeline",
        "AuraFlowPipeline": "AuraFlowPipeline",
        "HunyuanDiTPipeline": "HunyuanDiTPipeline",
        "CogView3PlusPipeline": "CogView3PlusPipeline",
        "IFPipeline": "IFPipeline",
        "AutoPipelineForText2Image": "AutoPipelineForText2Image",
    }

    cls_name = pipeline_map.get(pipeline_name, pipeline_name)

    try:
        pipeline_cls = getattr(diffusers, cls_name, None)
        if pipeline_cls is None:
            # Try AutoPipeline as fallback
            pipeline_cls = diffusers.AutoPipelineForText2Image
            print(f"  Using AutoPipelineForText2Image for {model_id}")

        pipe = pipeline_cls.from_pretrained(model_id, torch_dtype=dtype)
        pipe.to("cuda")

        # Enable memory optimizations
        if hasattr(pipe, "enable_model_cpu_offload"):
            try:
                pipe.enable_model_cpu_offload()
            except Exception:
                pass

        return pipe

    except Exception as e:
        print(f"  Pipeline load error: {e}")
        return None


# ── OpenFake download ────────────────────────────────────────────────

def generate_openfake(args):
    """Download AI images from OpenFake + JourneyDB on HuggingFace."""
    import requests as req

    s3 = boto3.client("s3", region_name=args.region)

    # Resume
    records = _load_existing_records(s3, args.bucket, args.output_prefix) if args.resume else []
    existing_counts = {}
    for r in records:
        gen = r.get("generator", "")
        existing_counts[gen] = existing_counts.get(gen, 0) + 1

    HF_API = "https://datasets-server.huggingface.co/rows"
    total_new = 0

    # ── Part 1: OpenFake ──────────────────────────────────────────
    for gen, target in OPENFAKE_GENERATORS.items():
        existing = existing_counts.get(gen, 0)
        if existing >= target:
            print(f"\n=== OpenFake: {gen} — SKIP ({existing}/{target}) ===")
            continue

        remaining = target - existing
        print(f"\n=== OpenFake: {gen} (need: {remaining}/{target}) ===")
        gen_count = 0
        offset = 0

        while gen_count < remaining and offset < 100000:
            try:
                resp = req.get(HF_API, params={
                    "dataset": "ComplexDataLab/OpenFake",
                    "config": "default",
                    "split": "train",
                    "offset": offset,
                    "length": 100,
                }, timeout=60)

                if resp.status_code == 429:
                    print("  Rate limited, sleeping 30s...")
                    time.sleep(30)
                    continue

                if resp.status_code != 200:
                    offset += 100
                    continue

                rows = resp.json().get("rows", [])
                if not rows:
                    break

                offset += len(rows)

                for row in rows:
                    if gen_count >= remaining:
                        break
                    r = row.get("row", {})
                    if r.get("label") != "fake":
                        continue
                    model = r.get("model", "")
                    if gen.lower() not in model.lower().replace(" ", "-"):
                        continue

                    img_data = r.get("image", {})
                    img_url = img_data.get("src", "")
                    if not img_url:
                        continue

                    try:
                        img_resp = req.get(img_url, timeout=30)
                        img = Image.open(io.BytesIO(img_resp.content))
                        jpeg_bytes = _standardize_image(img)
                        if jpeg_bytes is None:
                            continue

                        filename = f"{uuid.uuid4().hex[:12]}.jpg"
                        s3.put_object(
                            Bucket=args.bucket,
                            Key=f"{args.output_prefix}/{filename}",
                            Body=jpeg_bytes,
                            ContentType="image/jpeg",
                            Metadata={"generator": gen, "source": "openfake"},
                        )

                        records.append({
                            "filename": filename,
                            "ground_truth": "ai_generated",
                            "generator": gen,
                            "source": "openfake",
                        })
                        gen_count += 1
                        total_new += 1

                        if total_new % 100 == 0:
                            print(f"  [{total_new}] downloading...")
                            _save_labels(records, s3, args.bucket, args.output_prefix)
                    except Exception:
                        continue

                time.sleep(0.5)

            except Exception as e:
                print(f"  Error: {e}")
                time.sleep(5)
                continue

        print(f"  {gen}: downloaded {gen_count}")

    # ── Part 2: JourneyDB (Midjourney) ────────────────────────────
    mj_existing = existing_counts.get("midjourney_journeydb", 0)
    if mj_existing < JOURNEYDB_TARGET:
        remaining_mj = JOURNEYDB_TARGET - mj_existing
        print(f"\n=== JourneyDB: Midjourney (need: {remaining_mj}/{JOURNEYDB_TARGET}) ===")
        mj_count = 0

        try:
            from datasets import load_dataset
            ds = load_dataset("JourneyDB/JourneyDB", split="train", streaming=True)

            for item in ds:
                if mj_count >= remaining_mj:
                    break

                try:
                    img = None
                    for key in ["image", "Image", "img"]:
                        if key in item and item[key] is not None:
                            val = item[key]
                            if isinstance(val, Image.Image):
                                img = val
                            elif isinstance(val, bytes):
                                img = Image.open(io.BytesIO(val))
                            break

                    if img is None:
                        continue

                    jpeg_bytes = _standardize_image(img)
                    if jpeg_bytes is None:
                        continue

                    filename = f"{uuid.uuid4().hex[:12]}.jpg"
                    s3.put_object(
                        Bucket=args.bucket,
                        Key=f"{args.output_prefix}/{filename}",
                        Body=jpeg_bytes,
                        ContentType="image/jpeg",
                        Metadata={"generator": "midjourney", "source": "journeydb"},
                    )

                    records.append({
                        "filename": filename,
                        "ground_truth": "ai_generated",
                        "generator": "midjourney_journeydb",
                        "source": "journeydb",
                    })
                    mj_count += 1
                    total_new += 1

                    if mj_count % 50 == 0:
                        print(f"  JourneyDB: [{mj_count}/{remaining_mj}]")
                        _save_labels(records, s3, args.bucket, args.output_prefix)

                except Exception:
                    continue

            print(f"  JourneyDB: downloaded {mj_count}")

        except Exception as e:
            print(f"  JourneyDB failed: {e}")

    # ── Part 3: DALL-E community ──────────────────────────────────
    dalle_existing = existing_counts.get("dalle3_community", 0)
    if dalle_existing < DALLE_COMMUNITY_TARGET:
        remaining_dalle = DALLE_COMMUNITY_TARGET - dalle_existing
        print(f"\n=== DALL-E Community (need: {remaining_dalle}/{DALLE_COMMUNITY_TARGET}) ===")
        dalle_count = 0

        try:
            from datasets import load_dataset
            ds = load_dataset("laion/dalle-3-dataset", split="train", streaming=True)

            for item in ds:
                if dalle_count >= remaining_dalle:
                    break

                try:
                    img = None
                    for key in ["image", "Image", "img"]:
                        if key in item and item[key] is not None:
                            val = item[key]
                            if isinstance(val, Image.Image):
                                img = val
                            elif isinstance(val, bytes):
                                img = Image.open(io.BytesIO(val))
                            break

                    if img is None:
                        continue

                    jpeg_bytes = _standardize_image(img)
                    if jpeg_bytes is None:
                        continue

                    filename = f"{uuid.uuid4().hex[:12]}.jpg"
                    s3.put_object(
                        Bucket=args.bucket,
                        Key=f"{args.output_prefix}/{filename}",
                        Body=jpeg_bytes,
                        ContentType="image/jpeg",
                        Metadata={"generator": "dalle3", "source": "dalle3_community"},
                    )

                    records.append({
                        "filename": filename,
                        "ground_truth": "ai_generated",
                        "generator": "dalle3_community",
                        "source": "dalle3_community",
                    })
                    dalle_count += 1
                    total_new += 1

                    if dalle_count % 50 == 0:
                        print(f"  DALL-E community: [{dalle_count}/{remaining_dalle}]")

                except Exception:
                    continue

            print(f"  DALL-E community: downloaded {dalle_count}")

        except Exception as e:
            print(f"  DALL-E community failed: {e}")

    _save_labels(records, s3, args.bucket, args.output_prefix)
    print(f"\nOpenFake/download done: {total_new} new images, {len(records)} total")
    return records


# ── Main ─────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Generate AI insurance images")
    parser.add_argument("--mode", choices=["local", "openfake", "both"], default="both")
    parser.add_argument("--target", type=int, default=5500)
    parser.add_argument("--bucket", default="dent-calibration-data")
    parser.add_argument("--output-prefix", default="raw_v8/ai_generated")
    parser.add_argument("--region", default="eu-central-1")
    parser.add_argument("--resume", action="store_true", help="Resume from existing S3 data")
    parser.add_argument(
        "--generators", default="all",
        help="Comma-separated generator names for local mode (or 'all')",
    )
    args = parser.parse_args()

    if boto3 is None:
        print("ERROR: pip install boto3")
        sys.exit(1)

    if args.mode in ("local", "both"):
        local_target = args.target if args.mode == "local" else int(args.target * 0.4)
        args_local = argparse.Namespace(**{**vars(args), "target": local_target})
        generate_local(args_local)

    if args.mode in ("openfake", "both"):
        of_target = args.target if args.mode == "openfake" else int(args.target * 0.6)
        args_of = argparse.Namespace(**{**vars(args), "target": of_target})
        generate_openfake(args_of)


if __name__ == "__main__":
    main()
