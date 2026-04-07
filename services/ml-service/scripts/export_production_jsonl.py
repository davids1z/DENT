#!/usr/bin/env python3
"""Export production ForensicResult rows into a labeled JSONL training dataset.

Why this exists
---------------
The DENT production database stores the full module-result JSON for every
analyzed image. After 12 PRs of fixes the system has ~139 production samples
with REAL per-module score logs from REAL insurance traffic. That is the most
valuable labeled dataset in the project — far more valuable than the 14k
synthetic samples we trained probes on, because it reflects the actual
distribution we deploy against.

This script:
  1. Connects to the dent Postgres on 94.72.107.11 via SSH tunnel (or local)
  2. Reads all ForensicResult rows
  3. Outputs JSONL with per-row record:
       {
         "id": "<uuid>",
         "filename": "...",
         "created_at": "...",
         "overall_risk_score": 0.xx,
         "overall_risk_level": "Low|Medium|High|Critical",
         "modules": {<module_name>: {risk_score, risk_level, n_findings}, ...},
         "verdict_probabilities": {authentic, ai_generated, tampered} | null,
         "predicted_source": "...",
         "ground_truth": null   <-- TO BE LABELED MANUALLY
       }
  4. Automatically pre-fills `ground_truth` from a heuristic if --autolabel:
       - filename contains "ai/dalle/midjourney/sd/flux" → "ai_generated"
       - filename contains "tampered/edit/splice" → "tampered"
       - otherwise → "authentic" (insurance traffic is mostly authentic)
  5. The user is expected to spot-check and flip the few wrong ones
     (~30 minutes of work for 139 rows)

Usage
-----
  # Direct (run on the server itself)
  python -m scripts.export_production_jsonl \
      --output data/production_v1.jsonl \
      --autolabel

  # Via SSH from dev machine (uses paramiko / psql tunnel)
  python -m scripts.export_production_jsonl \
      --ssh-host root@94.72.107.11 --ssh-port 2222 \
      --output data/production_v1.jsonl \
      --autolabel
"""
import argparse
import json
import os
import re
import subprocess
import sys
from typing import Any


# Heuristic filename patterns for auto-labeling. Insurance fraud test sets are
# typically labeled in the filename. The user must spot-check.
_AI_FILENAME_PATTERNS = re.compile(
    r"(?:^|[_\-/])(?:ai|dall[\-_]?e|dalle|midjourney|stable[\-_]?diffusion|sd\d|sdxl|"
    r"flux|comfyui|automatic1111|invokeai|firefly|imagen|gemini[\-_]?gen|"
    r"krea|leonardo|playground|ideogram|kandinsky|gen[\-_]?image|fake|generated|"
    r"synthetic|aigen)",
    re.IGNORECASE,
)
_TAMPERED_FILENAME_PATTERNS = re.compile(
    r"(?:^|[_\-/])(?:tampered|edit(?:ed)?|splice|inpaint|copy[\-_]?move|"
    r"forged?|manipulated)",
    re.IGNORECASE,
)


def _autolabel(filename: str | None) -> str:
    """Best-guess label from filename. Insurance default is 'authentic'."""
    if not filename:
        return "authentic"
    if _AI_FILENAME_PATTERNS.search(filename):
        return "ai_generated"
    if _TAMPERED_FILENAME_PATTERNS.search(filename):
        return "tampered"
    return "authentic"


# SQL — selects everything we need into a single TSV stream so we don't need
# psycopg2 installed locally; the SSH path uses `docker exec ... psql -t -A`.
_QUERY = """
SELECT
    "Id"::text || '	' ||
    COALESCE("FileName", '') || '	' ||
    "CreatedAt"::text || '	' ||
    "OverallRiskScore"::text || '	' ||
    "OverallRiskLevel" || '	' ||
    COALESCE("PredictedSource", '') || '	' ||
    "SourceConfidence"::text || '	' ||
    COALESCE("C2paStatus", '') || '	' ||
    REPLACE(REPLACE("ModuleResultsJson", E'\n', ''), E'\t', ' ') || '	' ||
    COALESCE(REPLACE(REPLACE("VerdictProbabilitiesJson", E'\n', ''), E'\t', ' '), '')
FROM "ForensicResults"
ORDER BY "CreatedAt" ASC
"""


def _run_sql_via_ssh(host: str, port: int, container: str = "dent-postgres-1") -> str:
    """Execute the SELECT remotely and return the raw TSV stream.

    The SQL contains both single-quoted literals AND double-quoted identifiers
    (because Postgres is case-folded otherwise). We can't pass the whole thing
    inside another shell layer without re-escaping every quote, so we instead
    write the SQL to a temp file on the remote and run psql from -f.
    """
    import base64
    sql_b64 = base64.b64encode(_QUERY.encode()).decode()
    # Decode on remote → temp file → psql -f → cleanup
    remote_cmd = (
        f"echo {sql_b64} | base64 -d > /tmp/dent_export.sql && "
        f"docker cp /tmp/dent_export.sql {container}:/tmp/dent_export.sql && "
        f"docker exec {container} psql -U dent -d dent -t -A -F $'\\t' "
        f"-f /tmp/dent_export.sql && "
        f"rm -f /tmp/dent_export.sql && "
        f"docker exec {container} rm -f /tmp/dent_export.sql"
    )
    cmd = ["ssh", "-p", str(port), host, remote_cmd]
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        sys.stderr.write(f"psql failed: {result.stderr}\n")
        sys.exit(1)
    return result.stdout


def _parse_row(line: str) -> dict[str, Any] | None:
    """Parse a single TSV row from the psql output."""
    # 10 columns separated by literal tabs (psql -A -F $'\t')
    parts = line.split("\t")
    if len(parts) < 10:
        return None
    (
        rid,
        filename,
        created_at,
        overall_score,
        overall_level,
        predicted_source,
        source_conf,
        c2pa_status,
        modules_json,
        verdict_json,
    ) = parts[:10]

    try:
        modules_raw = json.loads(modules_json) if modules_json else []
    except json.JSONDecodeError:
        return None

    modules = {}
    for m in modules_raw:
        name = m.get("moduleName") or m.get("module_name")
        if not name:
            continue
        modules[name] = {
            "risk_score": float(m.get("riskScore") or m.get("risk_score") or 0.0),
            "risk_level": m.get("riskLevel") or m.get("risk_level") or "Low",
            "n_findings": len(m.get("findings") or []),
            "error": m.get("error"),
        }

    verdict_probs = None
    if verdict_json:
        try:
            verdict_probs = json.loads(verdict_json)
        except json.JSONDecodeError:
            verdict_probs = None

    return {
        "id": rid,
        "filename": filename or None,
        "created_at": created_at,
        "overall_risk_score": float(overall_score),
        "overall_risk_level": overall_level,
        "predicted_source": predicted_source or None,
        "source_confidence": int(float(source_conf or 0)),
        "c2pa_status": c2pa_status or None,
        "modules": modules,
        "verdict_probabilities": verdict_probs,
        "ground_truth": None,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Export DENT production ForensicResult rows to labeled JSONL")
    parser.add_argument("--output", required=True, help="Path to output JSONL file")
    parser.add_argument("--ssh-host", default="root@94.72.107.11", help="SSH user@host (default production)")
    parser.add_argument("--ssh-port", type=int, default=2222, help="SSH port (default 2222)")
    parser.add_argument("--container", default="dent-postgres-1", help="Postgres container name")
    parser.add_argument("--autolabel", action="store_true", help="Pre-fill ground_truth from filename heuristics")
    parser.add_argument("--from-tsv", help="Read from a local TSV file instead of SSH (for testing)")
    args = parser.parse_args()

    if args.from_tsv:
        with open(args.from_tsv, "r") as f:
            raw = f.read()
    else:
        raw = _run_sql_via_ssh(args.ssh_host, args.ssh_port, args.container)

    rows = []
    for line in raw.splitlines():
        line = line.rstrip()
        if not line:
            continue
        row = _parse_row(line)
        if row is None:
            continue
        if args.autolabel:
            row["ground_truth"] = _autolabel(row["filename"])
        rows.append(row)

    if not rows:
        sys.stderr.write("No rows parsed. Check connection and query.\n")
        return 1

    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
    with open(args.output, "w") as f:
        for row in rows:
            f.write(json.dumps(row) + "\n")

    # Print summary
    print(f"Wrote {len(rows)} rows to {args.output}")
    if args.autolabel:
        from collections import Counter
        c = Counter(r["ground_truth"] for r in rows)
        print(f"Auto-label distribution: {dict(c)}")
        print()
        print("NEXT STEP: spot-check rows where the filename does not clearly")
        print("indicate the class. Look for misclassified AI samples (filename")
        print("does not contain 'ai/dalle/sd/flux/etc') and authentic samples")
        print("with misleading filenames.")
        print()
        print("Quick filter:")
        print(f"  jq -r 'select(.ground_truth==\"ai_generated\") | .filename' {args.output}")
        print(f"  jq -r 'select(.ground_truth==\"authentic\") | .filename' {args.output} | head -30")

    return 0


if __name__ == "__main__":
    sys.exit(main())
