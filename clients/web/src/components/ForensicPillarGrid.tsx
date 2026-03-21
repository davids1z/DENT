"use client";

import type { ForensicResult } from "@/lib/api";
import { groupModulesIntoPillars } from "@/lib/forensicPillars";
import { ForensicPillarCard } from "./ForensicPillarCard";

interface ForensicPillarGridProps {
  result: ForensicResult;
  originalImageUrl: string;
}

export function ForensicPillarGrid({ result, originalImageUrl }: ForensicPillarGridProps) {
  const pillars = groupModulesIntoPillars(result.modules, result);

  if (pillars.length === 0) return null;

  return (
    <div>
      <h3 className="text-xs font-medium text-muted uppercase tracking-wider mb-3">
        Forenzicki moduli ({pillars.length} stupova)
      </h3>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
        {pillars.map((p) => (
          <ForensicPillarCard key={p.pillar.id} data={p} originalImageUrl={originalImageUrl} />
        ))}
      </div>
    </div>
  );
}
