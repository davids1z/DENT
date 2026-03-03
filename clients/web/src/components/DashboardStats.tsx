"use client";

import type { DashboardStats as Stats } from "@/lib/api";
import { formatCurrency, damageTypeLabel } from "@/lib/api";
import { GlowCard } from "@/components/ui/GlowCard";
import { GlassPanel } from "@/components/ui/GlassPanel";

interface DashboardStatsProps {
  stats: Stats;
}

export function DashboardStats({ stats }: DashboardStatsProps) {
  const topDamageTypes = Object.entries(stats.damageTypeDistribution)
    .sort((a, b) => b[1] - a[1])
    .slice(0, 5);
  const totalDamages = topDamageTypes.reduce((sum, [, count]) => sum + count, 0);

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <GlowCard>
          <div className="text-xs text-muted uppercase tracking-wider mb-2">Ukupno inspekcija</div>
          <div className="text-2xl font-bold">{stats.totalInspections}</div>
        </GlowCard>
        <GlowCard>
          <div className="text-xs text-muted uppercase tracking-wider mb-2">Završeno</div>
          <div className="text-2xl font-bold text-green-600">{stats.completedInspections}</div>
        </GlowCard>
        <GlowCard>
          <div className="text-xs text-muted uppercase tracking-wider mb-2">Prosječni trošak</div>
          <div className="text-2xl font-bold">{formatCurrency(stats.averageCostMin)}</div>
          {stats.averageCostMax > 0 && <div className="text-xs text-muted mt-1">do {formatCurrency(stats.averageCostMax)}</div>}
        </GlowCard>
        <GlowCard>
          <div className="text-xs text-muted uppercase tracking-wider mb-2">U obradi</div>
          <div className="text-2xl font-bold">{stats.pendingInspections}</div>
        </GlowCard>
      </div>
      {topDamageTypes.length > 0 && (
        <GlassPanel>
          <h3 className="text-sm font-medium text-muted uppercase tracking-wider mb-4">Najčešći tipovi šteta</h3>
          <div className="space-y-3">
            {topDamageTypes.map(([type, count]) => (
              <div key={type} className="flex items-center gap-3">
                <div className="w-32 text-sm truncate">{damageTypeLabel(type)}</div>
                <div className="flex-1 h-2 bg-gray-100 rounded-full overflow-hidden">
                  <div className="h-full rounded-full bg-accent" style={{ width: `${(count / totalDamages) * 100}%` }} />
                </div>
                <div className="text-sm text-muted w-8 text-right font-mono">{count}</div>
              </div>
            ))}
          </div>
        </GlassPanel>
      )}
    </div>
  );
}
