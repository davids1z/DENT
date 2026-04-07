"use client";

import { useState } from "react";
import type { ForensicResult } from "@/lib/api";
import { groupModulesIntoPillars } from "@/lib/forensicPillars";
import { ForensicPillarCard } from "./ForensicPillarCard";

interface ForensicPillarGridProps {
  result: ForensicResult;
  originalImageUrl: string;
}

// 2026-04-07 — "Verdict-driven UI" redesign.
//
// The previous implementation rendered every pillar (AI / Tampering /
// Metadata / Documents) as an equally-prominent card on every analysis.
// On a clearly-AI image you'd see "Detekcija manipulacija ✓ 0% Čisto"
// and "Metapodaci ✓ 10% Čisto" taking up half the screen with no useful
// information. The user feedback: "if it's AI, just show me AI; if it's
// tampered, just show me tampering; don't make me parse three pillars
// every time".
//
// New behaviour:
//   1. Pillars marked `isSignificant` (score ≥ 0.20 OR has a finding OR
//      errored) get the full ForensicPillarCard treatment.
//   2. Insignificant pillars are hidden behind a single "Sve čisto"
//      summary card listing them as compact chips. Click to expand.
//   3. If EVERY pillar is insignificant (a fully clean image), the
//      grid renders just the summary card with all chips visible.
//
// Final overall score is unchanged — this is purely presentation. The
// fusion in services/ml-service/app/forensics/fusion.py still considers
// every module's contribution.
export function ForensicPillarGrid({ result, originalImageUrl }: ForensicPillarGridProps) {
  const [expanded, setExpanded] = useState(false);
  const pillars = groupModulesIntoPillars(result.modules, result);

  if (pillars.length === 0) return null;

  const significant = pillars.filter((p) => p.isSignificant);
  const cleanPillars = pillars.filter((p) => !p.isSignificant);

  return (
    <div>
      <h3 className="text-xs font-medium text-muted uppercase tracking-wider mb-3">
        Forenzicki moduli ({pillars.length} stupova{cleanPillars.length > 0 ? `, ${cleanPillars.length} čisto` : ""})
      </h3>

      {significant.length > 0 && (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3 mb-3">
          {significant.map((p) => (
            <ForensicPillarCard
              key={p.pillar.id}
              data={p}
              originalImageUrl={originalImageUrl}
            />
          ))}
        </div>
      )}

      {cleanPillars.length > 0 && (
        <div className="rounded-lg border border-emerald-500/20 bg-emerald-500/5 p-3">
          <button
            type="button"
            onClick={() => setExpanded((v) => !v)}
            className="w-full flex items-center justify-between text-sm text-emerald-300 hover:text-emerald-200 transition"
          >
            <span className="flex items-center gap-2">
              <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M9 12.75L11.25 15 15 9.75M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
              </svg>
              {cleanPillars.length === pillars.length
                ? "Svi forenzički stupovi su čisti"
                : `${cleanPillars.length} dodatn${cleanPillars.length === 1 ? "i stup" : "a stupa"} bez nalaza`}
            </span>
            <span className="text-xs text-muted">
              {cleanPillars.map((p) => p.pillar.label).join(" · ")}
              <span className="ml-2">{expanded ? "▴" : "▾"}</span>
            </span>
          </button>

          {expanded && (
            <div className="mt-3 grid grid-cols-1 md:grid-cols-2 gap-3">
              {cleanPillars.map((p) => (
                <ForensicPillarCard
                  key={p.pillar.id}
                  data={p}
                  originalImageUrl={originalImageUrl}
                />
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
