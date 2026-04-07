#!/usr/bin/env python3
"""Apply known label corrections + report rows that need manual review.

The auto-labeler in export_production_jsonl.py uses filename heuristics. It
catches obvious cases (anything with "ai/dall-e/sd/flux/midjourney/generated")
but misses cases where the filename is opaque (car4.webp, IMG-20250217.jpg).

This script:
  1. Loads production_v1.jsonl
  2. Applies known overrides (hard-coded filename → label map)
  3. Flags rows where the score and label disagree strongly:
     - Authentic + score >= 0.65   (likely AI mislabeled)
     - AI + score < 0.20           (likely authentic mislabeled)
  4. Writes production_v1_corrected.jsonl
  5. Prints a manual-review todo list

The user reviews the output, then accepts or further corrects the file.
"""
import argparse
import json
from collections import Counter


# Known ground-truth overrides. Add to this list as more test images are
# identified during manual review.
_KNOWN_LABELS: dict[str, str] = {
    # AI generators we have tested manually
    "car4.webp": "ai_generated",          # AI-generated car crash image
    # The Gemini_Generated_Image files are caught by autolabel already

    # Authentic test photos we have tested manually
    "car5.jpg": "authentic",              # Real car damage photo
    "car6.jpg": "authentic",              # Real car damage photo
    "IMG-20250217-WA0003.jpg": "authentic",   # WhatsApp phone photo, real

    # Documents — typically authentic insurance policies
    "Polica Osiguranja HR.pdf": "authentic",
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--review-threshold-high", type=float, default=0.65,
                        help="Authentic rows scoring above this need manual review")
    parser.add_argument("--review-threshold-low", type=float, default=0.20,
                        help="AI rows scoring below this need manual review")
    args = parser.parse_args()

    rows = []
    with open(args.input) as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))

    n_overrides = 0
    review_needed = []

    for r in rows:
        fn = (r.get("filename") or "").strip()
        # 1) Apply known overrides (case-insensitive exact match)
        for known_fn, known_label in _KNOWN_LABELS.items():
            if fn.lower() == known_fn.lower():
                if r.get("ground_truth") != known_label:
                    r["ground_truth"] = known_label
                    n_overrides += 1
                break

        # 2) Flag suspicious score/label disagreements
        score = r.get("overall_risk_score", 0.0)
        label = r.get("ground_truth", "authentic")
        if label == "authentic" and score >= args.review_threshold_high:
            review_needed.append((score, label, fn or "(no filename)", r["id"]))
        elif label == "ai_generated" and score < args.review_threshold_low:
            review_needed.append((score, label, fn or "(no filename)", r["id"]))

    # Write corrected file
    with open(args.output, "w") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")

    # Summary
    counts = Counter(r["ground_truth"] for r in rows)
    print(f"Loaded {len(rows)} rows from {args.input}")
    print(f"Applied {n_overrides} hard-coded label overrides")
    print(f"Wrote {len(rows)} rows to {args.output}")
    print()
    print(f"Final label distribution: {dict(counts)}")
    print()
    if review_needed:
        review_needed.sort(reverse=True)
        print(f"=== ROWS NEEDING MANUAL REVIEW ({len(review_needed)}) ===")
        print("(authentic + score>=0.65 OR ai_generated + score<0.20)")
        print()
        print(f"  {'score':>6} {'label':<14} filename")
        for score, label, fn, _ in review_needed[:30]:
            print(f"  {score*100:5.1f}% {label:<14} {fn[:60]}")
        if len(review_needed) > 30:
            print(f"  ... +{len(review_needed)-30} more")
        print()
        print("To override more labels, edit _KNOWN_LABELS in this script and re-run.")
    else:
        print("No rows need manual review. Labels look consistent with scores.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
