"use client";

import type { DashboardStats as Stats } from "@/lib/api";
import { formatCurrency, damageTypeLabel } from "@/lib/api";

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
      {/* Stat Cards */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <StatCard
          label="Ukupno inspekcija"
          value={stats.totalInspections}
          icon={
            <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M9 12h3.75M9 15h3.75M9 18h3.75m3 .75H18a2.25 2.25 0 002.25-2.25V6.108c0-1.135-.845-2.098-1.976-2.192a48.424 48.424 0 00-1.123-.08m-5.801 0c-.065.21-.1.433-.1.664 0 .414.336.75.75.75h4.5a.75.75 0 00.75-.75 2.25 2.25 0 00-.1-.664m-5.8 0A2.251 2.251 0 0113.5 2.25H15c1.012 0 1.867.668 2.15 1.586m-5.8 0c-.376.023-.75.05-1.124.08C9.095 4.01 8.25 4.973 8.25 6.108V8.25m0 0H4.875c-.621 0-1.125.504-1.125 1.125v11.25c0 .621.504 1.125 1.125 1.125h9.75c.621 0 1.125-.504 1.125-1.125V9.375c0-.621-.504-1.125-1.125-1.125H8.25z" />
            </svg>
          }
        />
        <StatCard
          label="Zavrseno"
          value={stats.completedInspections}
          accent
          icon={
            <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M9 12.75L11.25 15 15 9.75M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
            </svg>
          }
        />
        <StatCard
          label="Prosjecni trosak"
          value={formatCurrency(stats.averageCostMin)}
          sub={stats.averageCostMax > 0 ? `do ${formatCurrency(stats.averageCostMax)}` : undefined}
          icon={
            <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M2.25 18.75a60.07 60.07 0 0115.797 2.101c.727.198 1.453-.342 1.453-1.096V18.75M3.75 4.5v.75A.75.75 0 013 6h-.75m0 0v-.375c0-.621.504-1.125 1.125-1.125H20.25M2.25 6v9m18-10.5v.75c0 .414.336.75.75.75h.75m-1.5-1.5h.375c.621 0 1.125.504 1.125 1.125v9.75c0 .621-.504 1.125-1.125 1.125h-.375m1.5-1.5H21a.75.75 0 00-.75.75v.75m0 0H3.75m0 0h-.375a1.125 1.125 0 01-1.125-1.125V15m1.5 1.5v-.75A.75.75 0 003 15h-.75M15 10.5a3 3 0 11-6 0 3 3 0 016 0zm3 0h.008v.008H18V10.5zm-12 0h.008v.008H6V10.5z" />
            </svg>
          }
        />
        <StatCard
          label="U obradi"
          value={stats.pendingInspections}
          icon={
            <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M12 6v6h4.5m4.5 0a9 9 0 11-18 0 9 9 0 0118 0z" />
            </svg>
          }
        />
      </div>

      {/* Damage Type Distribution */}
      {topDamageTypes.length > 0 && (
        <div className="bg-card rounded-2xl border border-border p-6">
          <h3 className="text-sm font-medium text-muted uppercase tracking-wider mb-4">
            Najcesci tipovi steta
          </h3>
          <div className="space-y-3">
            {topDamageTypes.map(([type, count]) => (
              <div key={type} className="flex items-center gap-3">
                <div className="w-32 text-sm truncate">{damageTypeLabel(type)}</div>
                <div className="flex-1 h-2 bg-background rounded-full overflow-hidden">
                  <div
                    className="h-full bg-accent rounded-full transition-all duration-500"
                    style={{ width: `${(count / totalDamages) * 100}%` }}
                  />
                </div>
                <div className="text-sm text-muted w-8 text-right">{count}</div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function StatCard({
  label,
  value,
  sub,
  accent,
  icon,
}: {
  label: string;
  value: string | number;
  sub?: string;
  accent?: boolean;
  icon: React.ReactNode;
}) {
  return (
    <div className="bg-card rounded-2xl border border-border p-5 hover:border-accent/30 transition-colors">
      <div className="flex items-center gap-2 mb-3">
        <div className={`${accent ? "text-accent" : "text-muted"}`}>{icon}</div>
        <span className="text-xs text-muted uppercase tracking-wider">{label}</span>
      </div>
      <div className={`text-2xl font-bold ${accent ? "text-accent" : ""}`}>{value}</div>
      {sub && <div className="text-xs text-muted mt-1">{sub}</div>}
    </div>
  );
}
