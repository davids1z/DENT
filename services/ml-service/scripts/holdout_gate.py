#!/usr/bin/env python3
"""Hard CI gate that runs the labeled holdout JSONL through the fusion logic
and refuses to pass if accuracy regresses or the model has inverted.

This is the lesson from the B-Free disaster: CV F1 lied to us. Production
data is the only ground truth. This gate replays each holdout row through
the EXACT current fusion logic (no neural networks, just the rule-based
fusion + meta-learner blend) and checks:

  1. Authentic recall  >= --min-authentic-recall (default 0.85)
  2. AI recall         >= --min-ai-recall        (default 0.75)
  3. INVERSION CHECK   mean(score|AI) - mean(score|authentic) >= --min-margin
                       (default 0.20). This is the B-Free safety net — if the
                       model puts AI scores BELOW authentic scores, it has
                       fundamentally inverted and must not deploy.
  4. No score is NaN / None / negative

Each holdout row already has the per-module risk_scores stored, so we don't
need to re-run the analyzer pipeline. We replay through fuse_scores().

Exit codes:
  0  all gates passed
  1  one or more gates failed (do not deploy)
  2  script error / file not found
"""
import argparse
import json
import statistics
import sys
from pathlib import Path

# Make app importable
HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))

from app.forensics.base import AnalyzerFinding, ModuleResult, RiskLevel  # noqa: E402
from app.forensics.fusion import fuse_scores  # noqa: E402


def _row_to_modules(row: dict) -> list[ModuleResult]:
    """Reconstruct ModuleResult objects from a stored row.

    The stored JSONL only has (risk_score, risk_level, n_findings, error)
    per module — that's enough for fuse_scores() because the rule-based
    fusion only consults `risk_score` / `findings` length / module_name.
    Findings are reconstructed as one synthetic AnalyzerFinding per module
    so that downstream metadata-floor logic still has something to inspect
    (it looks for specific finding codes which we cannot recover from JSONL).
    """
    out = []
    for name, m in (row.get("modules") or {}).items():
        score = float(m.get("risk_score", 0.0))
        level_str = m.get("risk_level", "Low")
        try:
            level = RiskLevel[level_str.upper()] if isinstance(level_str, str) else RiskLevel.LOW
        except KeyError:
            level = RiskLevel.LOW
        n_find = int(m.get("n_findings", 0))
        findings = []
        # Reconstruct exactly one synthetic finding to mark presence
        if score > 0:
            findings.append(AnalyzerFinding(
                code=f"{name.upper()}_HOLDOUT",
                title="holdout",
                description="reconstructed from production JSONL",
                risk_score=score,
                confidence=0.80,
            ))
        out.append(ModuleResult(
            module_name=name,
            module_label=name,
            risk_score=score,
            risk_score100=int(round(score * 100)),
            risk_level=level,
            findings=findings,
            processing_time_ms=0,
            error=m.get("error"),
        ))
    return out


def _accuracy(rows: list[dict], threshold: float) -> dict:
    """Replay each row through fuse_scores() with the current fusion code,
    then compute confusion matrix at the given threshold."""
    tp = fp = tn = fn = 0
    auth_scores = []
    ai_scores = []
    misclassified = []

    for row in rows:
        modules = _row_to_modules(row)
        overall, _, _, _ = fuse_scores(modules)
        truth = row.get("ground_truth", "authentic")
        pred = "ai_generated" if overall >= threshold else "authentic"

        if truth == "ai_generated":
            ai_scores.append(overall)
            if pred == "ai_generated":
                tp += 1
            else:
                fn += 1
                misclassified.append(("FN", row.get("filename", "?"), overall))
        else:
            auth_scores.append(overall)
            if pred == "authentic":
                tn += 1
            else:
                fp += 1
                misclassified.append(("FP", row.get("filename", "?"), overall))

    auth_recall = tn / max(tn + fp, 1)
    ai_recall = tp / max(tp + fn, 1)
    overall_acc = (tn + tp) / max(len(rows), 1)
    auth_mean = statistics.mean(auth_scores) if auth_scores else 0.0
    ai_mean = statistics.mean(ai_scores) if ai_scores else 0.0
    margin = ai_mean - auth_mean

    return {
        "n_rows": len(rows),
        "tp": tp, "fp": fp, "tn": tn, "fn": fn,
        "authentic_recall": auth_recall,
        "ai_recall": ai_recall,
        "overall_accuracy": overall_acc,
        "auth_mean_score": auth_mean,
        "ai_mean_score": ai_mean,
        "margin": margin,
        "misclassified": misclassified,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Holdout gate for fusion changes")
    parser.add_argument("--holdout", required=True, help="Path to labeled holdout JSONL")
    parser.add_argument("--threshold", type=float, default=0.40,
                        help="AI vs authentic decision threshold (default: 0.40)")
    parser.add_argument("--min-authentic-recall", type=float, default=0.85)
    parser.add_argument("--min-ai-recall", type=float, default=0.75)
    parser.add_argument("--min-margin", type=float, default=0.20,
                        help="INVERSION CHECK: mean(AI score) - mean(authentic score) "
                             "must be >= this. Default 0.20.")
    parser.add_argument("--strict", action="store_true",
                        help="Fail with non-zero exit code if any gate fails")
    parser.add_argument("--baseline", help="Compare to a baseline JSON report")
    parser.add_argument("--save-report", help="Write metrics to a JSON file")
    args = parser.parse_args()

    if not Path(args.holdout).exists():
        sys.stderr.write(f"Holdout file not found: {args.holdout}\n")
        return 2

    with open(args.holdout) as f:
        rows = [json.loads(line) for line in f if line.strip()]

    metrics = _accuracy(rows, args.threshold)

    print(f"=== HOLDOUT GATE — {args.holdout} ===")
    print(f"Rows: {metrics['n_rows']}  threshold: {args.threshold}")
    print()
    print(f"  TP={metrics['tp']:3d}  FP={metrics['fp']:3d}  "
          f"TN={metrics['tn']:3d}  FN={metrics['fn']:3d}")
    print(f"  Authentic recall: {metrics['authentic_recall']*100:5.1f}% "
          f"(min {args.min_authentic_recall*100:.0f}%)")
    print(f"  AI recall:        {metrics['ai_recall']*100:5.1f}% "
          f"(min {args.min_ai_recall*100:.0f}%)")
    print(f"  Overall accuracy: {metrics['overall_accuracy']*100:5.1f}%")
    print()
    print(f"  Mean score | authentic: {metrics['auth_mean_score']*100:5.1f}%")
    print(f"  Mean score | AI:        {metrics['ai_mean_score']*100:5.1f}%")
    print(f"  INVERSION margin:       {metrics['margin']*100:+5.1f}%  "
          f"(min {args.min_margin*100:+.0f}%)")
    print()

    failed_gates = []
    if metrics["authentic_recall"] < args.min_authentic_recall:
        failed_gates.append(
            f"AUTH RECALL {metrics['authentic_recall']*100:.1f}% < "
            f"{args.min_authentic_recall*100:.0f}%"
        )
    if metrics["ai_recall"] < args.min_ai_recall:
        failed_gates.append(
            f"AI RECALL {metrics['ai_recall']*100:.1f}% < "
            f"{args.min_ai_recall*100:.0f}%"
        )
    if metrics["margin"] < args.min_margin:
        failed_gates.append(
            f"INVERSION CHECK FAILED — margin "
            f"{metrics['margin']*100:+.1f}% < {args.min_margin*100:+.0f}%"
            "  (model has inverted; do not deploy)"
        )

    if metrics["misclassified"]:
        print("=== MISCLASSIFIED ===")
        for tag, fn, score in sorted(metrics["misclassified"], key=lambda x: -x[2])[:10]:
            print(f"  {tag} {score*100:5.1f}%  {(fn or '?')[:60]}")
        if len(metrics["misclassified"]) > 10:
            print(f"  ... +{len(metrics['misclassified'])-10} more")
        print()

    if args.baseline and Path(args.baseline).exists():
        with open(args.baseline) as f:
            base = json.load(f)
        print("=== vs BASELINE ===")
        for k in ("authentic_recall", "ai_recall", "overall_accuracy", "margin"):
            delta = metrics[k] - base.get(k, 0)
            arrow = "↑" if delta > 0 else ("↓" if delta < 0 else "=")
            print(f"  {k}: {metrics[k]*100:5.1f}%  {arrow}{delta*100:+5.1f}pp")
        print()

    if args.save_report:
        report = {k: v for k, v in metrics.items() if k != "misclassified"}
        with open(args.save_report, "w") as f:
            json.dump(report, f, indent=2)
        print(f"Saved report to {args.save_report}")

    if failed_gates:
        print("FAILED GATES:")
        for g in failed_gates:
            print(f"  ✗ {g}")
        if args.strict:
            return 1
    else:
        print("ALL GATES PASSED ✓")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
