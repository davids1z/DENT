"use client";

import type { Inspection, ForensicResult } from "@/lib/api";
import { fraudRiskLabel } from "@/lib/api";
import { cn } from "@/lib/cn";

interface GroupFile {
  url: string;
  fileName: string;
  sortOrder: number;
  forensicResult: ForensicResult | null;
}

interface GroupOverviewCardProps {
  inspection: Inspection;
  files: GroupFile[];
}

export function GroupOverviewCard({ inspection, files }: GroupOverviewCardProps) {
  const riskLevel = inspection.fraudRiskLevel ?? "Low";

  const completedFiles = files.filter((f) => f.forensicResult);

  // Exact average of per-file risk scores
  const avgRisk = completedFiles.length > 0
    ? completedFiles.reduce((sum, f) => sum + (f.forensicResult?.overallRiskScore || 0), 0) / completedFiles.length
    : 0;
  const avgRiskPct = avgRisk * 100;

  const highRiskCount = completedFiles.filter(
    (f) => f.forensicResult && ["High", "Critical"].includes(f.forensicResult.overallRiskLevel)
  ).length;

  // Exact total time in ms → display in seconds with 2 decimals
  const totalTimeMs = completedFiles.reduce((sum, f) => sum + (f.forensicResult?.totalProcessingTimeMs || 0), 0);
  const crossFindings = inspection.crossImageReport?.findings?.length ?? 0;

  // Gauge color based on average
  const gaugeStroke =
    avgRiskPct <= 15 ? "#34D399" :
    avgRiskPct <= 35 ? "#2DD4BF" :
    avgRiskPct <= 55 ? "#FBBF24" :
    avgRiskPct <= 75 ? "#F97316" : "#EF4444";

  const compact = files.length > 20;

  return (
    <div className="bg-card border border-border rounded-2xl p-5 sm:p-6">
      <div className="flex items-start gap-4 sm:gap-6">
        {/* Risk gauge — shows exact average */}
        <div className="flex-shrink-0">
          <div className="relative w-20 h-20 sm:w-24 sm:h-24">
            <svg viewBox="0 0 100 100" className="w-full h-full -rotate-90">
              <circle cx="50" cy="50" r="42" fill="none" stroke="currentColor" strokeWidth="8" className="text-border opacity-50" />
              <circle
                cx="50" cy="50" r="42" fill="none" strokeWidth="8"
                strokeDasharray={`${avgRiskPct * 2.64} 264`}
                strokeLinecap="round"
                stroke={gaugeStroke}
              />
            </svg>
            <div className="absolute inset-0 flex flex-col items-center justify-center">
              <span className="text-lg sm:text-xl font-bold">{avgRiskPct.toFixed(1)}%</span>
            </div>
          </div>
        </div>

        {/* Info */}
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 mb-2">
            <span className="px-3 py-1 rounded-full text-xs font-semibold bg-card text-muted border border-border">
              {fraudRiskLabel(riskLevel)}
            </span>
            <span className="text-xs text-muted">Skupna analiza</span>
          </div>

          <h3 className="font-heading font-semibold text-base sm:text-lg mb-3">
            Analiza skupine od {files.length} datoteka
          </h3>

          {/* Stats row */}
          <div className="flex flex-wrap gap-x-5 gap-y-2 text-xs sm:text-sm">
            {highRiskCount > 0 && (
              <div>
                <span className="text-muted">Visokorizičnih: </span>
                <span className="font-medium">{highRiskCount}</span>
              </div>
            )}
            {crossFindings > 0 && (
              <div>
                <span className="text-muted">Nekonzistentnosti: </span>
                <span className="font-medium">{crossFindings}</span>
              </div>
            )}
            <div>
              <span className="text-muted">Vrijeme: </span>
              <span className="font-medium">{(totalTimeMs / 1000).toFixed(2)}s</span>
            </div>
          </div>
        </div>
      </div>

      {/* Per-file risk — exact decimals */}
      <div className="mt-4 pt-4 border-t border-border">
        <div className={cn("flex flex-wrap", compact ? "gap-1" : "gap-2")}>
          {files.map((file, idx) => {
            const fr = file.forensicResult;
            const pct = fr ? (fr.overallRiskScore * 100).toFixed(1) : "—";
            const name = file.fileName.length > 15 ? file.fileName.slice(0, 12) + "…" : file.fileName;
            return (
              <div key={idx} className="flex items-center gap-1.5 px-2.5 py-1 rounded-lg bg-background border border-border text-xs">
                <span className="text-muted truncate">{name}</span>
                <span className="font-mono font-medium tabular-nums">{pct}%</span>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
