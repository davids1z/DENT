#!/usr/bin/env python3
"""
Generate AI insurance-domain images using open-weight models on GPU.

Tier 1: Local generation with Flux/SDXL/SD3.5 using insurance prompts
Tier 2: OpenFake download for closed-source generators (DALL-E, MJ, etc.)

Usage (on vast.ai GPU):
  python3 -m scripts.generate_insurance_ai \
      --mode local --target 2000 \
      --bucket dent-calibration-data --output-prefix raw_v8/ai_generated

  python3 -m scripts.generate_insurance_ai \
      --mode openfake --target 3000 \
      --bucket dent-calibration-data --output-prefix raw_v8/ai_generated
"""

from __future__ import annotations

import argparse
import io
import json
import os
import sys
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


# ── Insurance prompts ────────────────────────────────────────────────

INSURANCE_PROMPTS = {
    "car_damage": [
        "photograph of a car with a large dent on the front bumper, parking lot, natural lighting",
        "close up photo of deep scratches on blue car door panel",
        "white car with broken windshield from hail damage, outdoor",
        "rear end collision damage on silver sedan trunk, street",
        "car side mirror broken off from parking accident",
        "red car with cracked headlight after fender bender",
        "SUV with dented hood from fallen tree branch",
        "car undercarriage rust damage inspection photo",
        "multiple dents on car roof from hailstorm",
        "car paint peeling and chipping from accident scrape",
        "damaged car wheel rim after hitting pothole",
        "car bumper hanging off after collision, close up",
    ],
    "house_damage": [
        "flooded living room with water damage on walls and furniture",
        "house roof with missing tiles after severe storm, exterior view",
        "fire damaged kitchen with burned cabinets and smoke stains",
        "basement with mold growing on walls from water leak",
        "cracked exterior house foundation wall, close up",
        "broken window on residential house after burglary",
        "collapsed ceiling from water damage, interior photo",
        "tree fallen on house roof causing structural damage",
        "tornado damage to suburban home, debris scattered",
        "water stains on apartment ceiling from pipe burst",
    ],
    "medical": [
        "photograph of bruised forearm, medical documentation",
        "bandaged hand after minor injury, hospital setting",
        "swollen ankle with ice pack, injury photo",
        "neck brace on patient after car accident, medical",
        "arm in plaster cast, fracture treatment photo",
    ],
    "documents": [
        "scanned car repair invoice on white background, text visible",
        "hospital medical bill printed on paper, document scan",
        "insurance claim form partially filled out, desk photo",
        "car mechanic repair estimate printed document",
        "receipt from auto body shop on counter",
    ],
    "general": [
        "blurry phone photo of car accident scene at night",
        "overexposed photo of damaged property exterior",
        "low quality phone camera snapshot of water damage",
        "dark grainy photo of house damage after storm",
        "amateur smartphone photo of scratched car",
    ],
}


# ── Local generators ─────────────────────────────────────────────────

LOCAL_GENERATORS = {
    "flux_schnell": {
        "model_id": "black-forest-labs/FLUX.1-schnell",
        "pipeline": "FluxPipeline",
        "params": {"num_inference_steps": 4, "guidance_scale": 0.0},
        "dtype": "bfloat16",
        "target": 500,
    },
    "flux_dev": {
        "model_id": "black-forest-labs/FLUX.1-dev",
        "pipeline": "FluxPipeline",
        "params": {"num_inference_steps": 28, "guidance_scale": 3.5},
        "dtype": "bfloat16",
        "target": 400,
    },
    "sdxl": {
        "model_id": "stabilityai/stable-diffusion-xl-base-1.0",
        "pipeline": "StableDiffusionXLPipeline",
        "params": {"num_inference_steps": 30, "guidance_scale": 7.5},
        "dtype": "float16",
        "target": 400,
    },
    "sd35_medium": {
        "model_id": "stabilityai/stable-diffusion-3.5-medium",
        "pipeline": "StableDiffusion3Pipeline",
        "params": {"num_inference_steps": 28, "guidance_scale": 5.0},
        "dtype": "bfloat16",
        "target": 400,
    },
    "hidream": {
        "model_id": "HiDream-ai/HiDream-I1-Dev",
        "pipeline": "HiDreamImagePipeline",
        "params": {"num_inference_steps": 28, "guidance_scale": 5.0},
        "dtype": "bfloat16",
        "target": 300,
    },
}

# OpenFake generators (Tier 2 — closed source, from HuggingFace dataset)
OPENFAKE_GENERATORS = [
    "dall-e-3", "midjourney-v6", "gpt-image-1", "grok-2-image-1212",
    "ideogram-3.0", "imagen-4.0", "stable-diffusion-3.5", "stable-diffusion-xl",
]


def generate_local(args):
    """Generate images locally on GPU using open-weight models."""
    import torch
    from diffusers import (
        FluxPipeline,
        StableDiffusionXLPipeline,
        StableDiffusion3Pipeline,
    )

    s3 = boto3.client("s3", region_name=args.region) if boto3 and not args.local_dir else None
    local_out = Path(args.local_dir) if args.local_dir else None
    if local_out:
        local_out.mkdir(parents=True, exist_ok=True)

    all_prompts = []
    for cat_prompts in INSURANCE_PROMPTS.values():
        all_prompts.extend(cat_prompts)

    records = []
    total_generated = 0

    # Scale targets
    total_target_sum = sum(g["target"] for g in LOCAL_GENERATORS.values())
    scale = args.target / total_target_sum

    for gen_name, gen_config in LOCAL_GENERATORS.items():
        gen_target = int(gen_config["target"] * scale)
        print(f"\n=== {gen_name} (target: {gen_target}) ===")

        try:
            dtype = getattr(torch, gen_config["dtype"])
            pipeline_cls = {
                "FluxPipeline": FluxPipeline,
                "StableDiffusionXLPipeline": StableDiffusionXLPipeline,
                "StableDiffusion3Pipeline": StableDiffusion3Pipeline,
            }.get(gen_config["pipeline"])

            if pipeline_cls is None:
                print(f"  Skipping {gen_name}: pipeline {gen_config['pipeline']} not available")
                continue

            pipe = pipeline_cls.from_pretrained(
                gen_config["model_id"],
                torch_dtype=dtype,
            )
            pipe.to("cuda")
            if hasattr(pipe, "enable_model_cpu_offload"):
                pipe.enable_model_cpu_offload()

            prompt_idx = 0
            for i in range(gen_target):
                prompt = all_prompts[prompt_idx % len(all_prompts)]
                prompt_idx += 1

                try:
                    result = pipe(prompt, **gen_config["params"])
                    image = result.images[0]

                    # Save as JPEG
                    buf = io.BytesIO()
                    image.save(buf, format="JPEG", quality=90)
                    jpeg_bytes = buf.getvalue()

                    filename = f"{uuid.uuid4().hex[:12]}.jpg"

                    if s3:
                        s3.put_object(
                            Bucket=args.bucket,
                            Key=f"{args.output_prefix}/{filename}",
                            Body=jpeg_bytes,
                            ContentType="image/jpeg",
                            Metadata={"generator": gen_name, "prompt": prompt[:200]},
                        )
                    elif local_out:
                        (local_out / filename).write_bytes(jpeg_bytes)

                    records.append({
                        "filename": filename,
                        "ground_truth": "ai_generated",
                        "generator": gen_name,
                    })
                    total_generated += 1

                    if total_generated % 50 == 0:
                        print(f"  [{total_generated}/{args.target}] {gen_name}")
                except Exception as e:
                    print(f"  Error generating: {e}")
                    continue

            # Free GPU memory
            del pipe
            torch.cuda.empty_cache()

        except Exception as e:
            print(f"  Failed to load {gen_name}: {e}")
            continue

    # Save labels
    _save_labels(records, s3, args)
    print(f"\nLocal generation done: {total_generated} images")
    return records


def generate_openfake(args):
    """Download AI images from OpenFake dataset on HuggingFace."""
    import requests as req

    s3 = boto3.client("s3", region_name=args.region) if boto3 and not args.local_dir else None
    local_out = Path(args.local_dir) if args.local_dir else None
    if local_out:
        local_out.mkdir(parents=True, exist_ok=True)

    records = []
    total = 0
    per_gen = args.target // len(OPENFAKE_GENERATORS)

    HF_API = "https://datasets-server.huggingface.co/rows"

    for gen in OPENFAKE_GENERATORS:
        print(f"\n=== OpenFake: {gen} (target: {per_gen}) ===")
        gen_count = 0
        offset = 0

        while gen_count < per_gen and offset < 50000:
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
                    import time
                    time.sleep(30)
                    continue

                resp.raise_for_status()
                rows = resp.json().get("rows", [])
                if not rows:
                    break

                offset += len(rows)

                for row in rows:
                    if gen_count >= per_gen:
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
                        img = Image.open(io.BytesIO(img_resp.content)).convert("RGB")

                        w, h = img.size
                        if max(w, h) > 1024:
                            ratio = 1024 / max(w, h)
                            img = img.resize((int(w * ratio), int(h * ratio)), Image.LANCZOS)

                        buf = io.BytesIO()
                        img.save(buf, format="JPEG", quality=90)
                        jpeg_bytes = buf.getvalue()

                        if len(jpeg_bytes) < 3000:
                            continue

                        filename = f"{uuid.uuid4().hex[:12]}.jpg"

                        if s3:
                            s3.put_object(
                                Bucket=args.bucket,
                                Key=f"{args.output_prefix}/{filename}",
                                Body=jpeg_bytes,
                                ContentType="image/jpeg",
                                Metadata={"generator": gen, "source": "openfake"},
                            )
                        elif local_out:
                            (local_out / filename).write_bytes(jpeg_bytes)

                        records.append({
                            "filename": filename,
                            "ground_truth": "ai_generated",
                            "generator": gen,
                        })
                        gen_count += 1
                        total += 1

                        if total % 100 == 0:
                            print(f"  [{total}/{args.target}]")
                    except Exception:
                        continue

            except Exception as e:
                print(f"  Error: {e}")
                import time
                time.sleep(5)
                continue

    _save_labels(records, s3, args)
    print(f"\nOpenFake download done: {total} images")
    return records


def _save_labels(records, s3, args):
    csv_content = "filename,ground_truth,generator\n"
    for rec in records:
        csv_content += f"{rec['filename']},{rec['ground_truth']},{rec.get('generator', '')}\n"
    if s3:
        s3.put_object(
            Bucket=args.bucket,
            Key=f"{args.output_prefix}/labels.csv",
            Body=csv_content.encode(),
            ContentType="text/csv",
        )
    local_out = Path(args.local_dir) if args.local_dir else None
    if local_out:
        (local_out / "labels.csv").write_text(csv_content)


def main():
    parser = argparse.ArgumentParser(description="Generate AI insurance images")
    parser.add_argument("--mode", choices=["local", "openfake", "both"], default="both")
    parser.add_argument("--target", type=int, default=5000)
    parser.add_argument("--bucket", default="dent-calibration-data")
    parser.add_argument("--output-prefix", default="raw_v8/ai_generated")
    parser.add_argument("--region", default="eu-central-1")
    parser.add_argument("--local-dir", default="")
    args = parser.parse_args()

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
