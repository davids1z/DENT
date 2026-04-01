"use client";

import type { DashboardStats as Stats } from "@/lib/api";
import { GlowCard } from "@/components/ui/GlowCard";

interface DashboardStatsProps {
  stats: Stats;
}

export function DashboardStats({ stats }: DashboardStatsProps) {
  const completionRate = stats.totalInspections > 0
    ? Math.round((stats.completedInspections / stats.totalInspections) * 100)
    : 0;

  return (
    <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
      <GlowCard>
        <div className="text-xs text-muted uppercase tracking-wider mb-2">Ukupno analiza</div>
        <div className="text-2xl font-bold">{stats.totalInspections}</div>
      </GlowCard>
      <GlowCard>
        <div className="text-xs text-muted uppercase tracking-wider mb-2">Završeno</div>
        <div className="text-2xl font-bold text-green-600">{stats.completedInspections}</div>
      </GlowCard>
      <GlowCard>
        <div className="text-xs text-muted uppercase tracking-wider mb-2">Uspješnost</div>
        <div className="text-2xl font-bold">{completionRate}%</div>
      </GlowCard>
      <GlowCard>
        <div className="text-xs text-muted uppercase tracking-wider mb-2">U obradi</div>
        <div className="text-2xl font-bold">{stats.pendingInspections}</div>
      </GlowCard>
    </div>
  );
}
