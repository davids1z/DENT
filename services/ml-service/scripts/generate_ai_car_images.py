#!/usr/bin/env python3
"""
Generate AI car damage images using Gemini 2.5 Flash Image and upload to S3.

Uses Google AI Studio API (free tier, 15 req/min for image generation).
Generates insurance-relevant car damage photos with varied prompts.

Usage:
  export GOOGLE_API_KEY=AIza...
  python -m scripts.generate_ai_car_images \
    --bucket dent-calibration-data \
    --count 1000
"""

import argparse
import base64
import io
import random
import sys
import time
import uuid

import boto3
import requests
from PIL import Image

# Diverse prompts for insurance-relevant AI car damage photos
DAMAGE_TYPES = [
    "large dent on the front bumper",
    "cracked windshield with spiderweb pattern",
    "scratched side panel with exposed metal",
    "broken headlight assembly",
    "crushed rear bumper from rear-end collision",
    "dented driver side door",
    "scraped paint on the fender",
    "smashed tail light",
    "bent car hood after frontal collision",
    "broken side mirror",
    "flat tire with rim damage",
    "hail damage dents on roof",
    "keyed scratch along entire side",
    "cracked front grille",
    "damaged wheel well and fender",
    "peeling paint and rust damage",
    "broken rear window",
    "dented quarter panel from side impact",
    "bumper hanging off after collision",
    "crushed front end from high speed crash",
]

CAR_TYPES = [
    "silver sedan", "black SUV", "white hatchback", "red sports car",
    "blue compact car", "grey minivan", "dark green pickup truck",
    "silver station wagon", "black luxury sedan", "white crossover",
    "old beige sedan", "navy blue coupe", "brown family car",
    "metallic grey SUV", "pearl white sedan",
]

LOCATIONS = [
    "parking lot", "residential street", "highway shoulder",
    "garage", "body shop", "intersection",
    "gas station", "apartment complex parking", "shopping mall parking",
    "suburban driveway", "rainy road", "gravel road",
]

CONDITIONS = [
    "natural daylight, slightly overcast",
    "bright sunny day, harsh shadows",
    "evening golden hour lighting",
    "night time with flash photography",
    "rainy weather, wet surfaces",
    "cloudy winter day",
    "early morning light",
    "fluorescent garage lighting",
    "sunset backlit",
    "overcast day, flat lighting",
]

CAMERA_STYLES = [
    "smartphone photo, insurance claim documentation",
    "phone camera, slightly blurry",
    "DSLR quality, sharp detail",
    "phone photo taken in a hurry",
    "close up detail shot",
    "wide angle showing full car",
    "medium shot from 3 meters away",
    "low angle showing underside damage",
    "overhead shot of roof damage",
    "diagonal front quarter view",
]


def build_prompt():
    """Generate a random insurance-relevant car damage photo prompt."""
    damage = random.choice(DAMAGE_TYPES)
    car = random.choice(CAR_TYPES)
    location = random.choice(LOCATIONS)
    condition = random.choice(CONDITIONS)
    camera = random.choice(CAMERA_STYLES)

    return (
        f"Generate a realistic photo of a {car} with {damage}, "
        f"located in a {location}. {condition}. "
        f"The photo style is {camera}. "
        f"Make it look like a real insurance claim photo."
    )


def generate_image(api_key: str, prompt: str, model: str = "gemini-2.5-flash-image") -> bytes | None:
    """Generate an image using Gemini API. Returns JPEG bytes or None."""
    try:
        resp = requests.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}",
            headers={"Content-Type": "application/json"},
            json={
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {"responseModalities": ["TEXT", "IMAGE"]},
            },
            timeout=60,
        )

        if resp.status_code == 429:
            return "RATE_LIMITED"
        if resp.status_code != 200:
            return None

        parts = resp.json().get("candidates", [{}])[0].get("content", {}).get("parts", [])
        for p in parts:
            if "inlineData" in p:
                raw = base64.b64decode(p["inlineData"]["data"])
                img = Image.open(io.BytesIO(raw)).convert("RGB")
                w, h = img.size
                if max(w, h) > 1024:
                    ratio = 1024 / max(w, h)
                    img = img.resize((int(w * ratio), int(h * ratio)), Image.LANCZOS)
                buf = io.BytesIO()
                img.save(buf, format="JPEG", quality=90)
                return buf.getvalue()
        return None
    except Exception:
        return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--bucket", required=True)
    parser.add_argument("--count", type=int, default=1000)
    parser.add_argument("--api-key", default=None, help="Google AI API key (or set GOOGLE_API_KEY env)")
    parser.add_argument("--region", default="eu-central-1")
    parser.add_argument("--model", default="gemini-2.5-flash-image")
    args = parser.parse_args()

    import os
    api_key = args.api_key or os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        print("ERROR: Set --api-key or GOOGLE_API_KEY env var")
        sys.exit(1)

    s3 = boto3.client("s3", region_name=args.region)

    # Check current count
    paginator = s3.get_paginator("list_objects_v2")
    current = 0
    for page in paginator.paginate(Bucket=args.bucket, Prefix="raw/ai_generated/"):
        current += len(page.get("Contents", []))
    remaining = args.count - current
    print(f"Current AI images: {current}, generating {remaining} more", flush=True)

    count = 0
    rate_limit_hits = 0

    while count < remaining:
        prompt = build_prompt()
        result = generate_image(api_key, prompt, args.model)

        if result == "RATE_LIMITED":
            rate_limit_hits += 1
            wait = min(60, 10 * rate_limit_hits)
            print(f"  Rate limited, waiting {wait}s...", flush=True)
            time.sleep(wait)
            continue

        if result is None:
            time.sleep(2)
            continue

        rate_limit_hits = 0
        name = uuid.uuid4().hex[:12] + ".jpg"
        s3.put_object(
            Bucket=args.bucket,
            Key=f"raw/ai_generated/{name}",
            Body=result,
            ContentType="image/jpeg",
            Metadata={"source": f"gemini_{args.model}", "prompt": prompt[:200]},
        )
        count += 1
        if count % 10 == 0:
            print(f"  {count}/{remaining} generated...", flush=True)

        # Stay under rate limit (15 req/min = 4s between requests)
        time.sleep(4.5)

    print(f"\nDone: {count} AI car images generated → s3://{args.bucket}/raw/ai_generated/")
    print(f"Total on S3: {current + count}")


if __name__ == "__main__":
    main()
