"use client";

import type { Inspection, ForensicResult } from "@/lib/api";
import { fraudRiskLabel, fraudRiskColor } from "@/lib/api";
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
  const riskScore = inspection.fraudRiskScore ?? 0;
  const riskLevel = inspection.fraudRiskLevel ?? "Low";
  const riskPercent = Math.round(riskScore * 100);

  // Compute stats
  const completedFiles = files.filter((f) => f.forensicResult);
  const avgRisk = completedFiles.length > 0
    ? completedFiles.reduce((sum, f) => sum + (f.forensicResult?.overallRiskScore || 0), 0) / completedFiles.length
    : 0;
  const highRiskCount = completedFiles.filter(
    (f) => f.forensicResult && ["High", "Critical"].includes(f.forensicResult.overallRiskLevel)
  ).length;
  const totalTimeMs = completedFiles.reduce((sum, f) => sum + (f.forensicResult?.totalProcessingTimeMs || 0), 0);

  const crossFindings = inspection.crossImageReport?.findings?.length ?? 0;

  return (
    <div className="bg-card border border-border rounded-2xl p-5 sm:p-6">
      <div className="flex items-start gap-4 sm:gap-6">
        {/* Risk gauge */}
        <div className="flex-shrink-0">
          <div className="relative w-20 h-20 sm:w-24 sm:h-24">
            <svg viewBox="0 0 100 100" className="w-full h-full -rotate-90">
              <circle cx="50" cy="50" r="42" fill="none" stroke="currentColor" strokeWidth="8" className="text-border" />
              <circle
                cx="50" cy="50" r="42" fill="none" strokeWidth="8"
                strokeDasharray={`${riskPercent * 2.64} 264`}
                strokeLinecap="round"
                className={cn(
                  riskLevel === "Critical" ? "text-red-500" :
                  riskLevel === "High" ? "text-orange-500" :
                  riskLevel === "Medium" ? "text-amber-500" : "text-green-500"
                )}
                stroke="currentColor"
              />
            </svg>
            <div className="absolute inset-0 flex flex-col items-center justify-center">
              <span className="text-lg sm:text-xl font-bold">{riskPercent}%</span>
            </div>
          </div>
        </div>

        {/* Info */}
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 mb-2">
            <span className={cn(
              "px-3 py-1 rounded-full text-xs font-semibold",
              riskLevel === "Critical" ? "bg-red-500/15 text-red-500" :
              riskLevel === "High" ? "bg-orange-500/15 text-orange-500" :
              riskLevel === "Medium" ? "bg-amber-500/15 text-amber-500" :
              "bg-green-500/15 text-green-500"
            )}>
              {fraudRiskLabel(riskLevel)}
            </span>
            <span className="text-xs text-muted">Skupna analiza</span>
          </div>

          <h3 className="font-heading font-semibold text-base sm:text-lg mb-3">
            Analiza skupine od {files.length} datoteka
          </h3>

          {/* Stats row */}
          <div className="flex flex-wrap gap-x-5 gap-y-2 text-xs sm:text-sm">
            <div>
              <span className="text-muted">Prosjecan rizik: </span>
              <span className="font-medium">{Math.round(avgRisk * 100)}%</span>
            </div>
            {highRiskCount > 0 && (
              <div>
                <span className="text-muted">Visokorizicnih: </span>
                <span className="font-medium text-red-500">{highRiskCount}</span>
              </div>
            )}
            {crossFindings > 0 && (
              <div>
                <span className="text-muted">Nekonzistentnosti: </span>
                <span className="font-medium text-amber-500">{crossFindings}</span>
              </div>
            )}
            <div>
              <span className="text-muted">Vrijeme: </span>
              <span className="font-medium">{(totalTimeMs / 1000).toFixed(1)}s</span>
            </div>
          </div>
        </div>
      </div>

      {/* File risk strip */}
      <div className="mt-4 flex gap-1.5">
        {files.map((file, idx) => {
          const fr = file.forensicResult;
          const level = fr?.overallRiskLevel || "Low";
          const bg = level === "Critical" ? "bg-red-500" : level === "High" ? "bg-orange-500" : level === "Medium" ? "bg-amber-500" : "bg-green-500";
          return (
            <div key={idx} className="flex-1 group relative">
              <div className={cn("h-2 rounded-full", bg)} />
              <div className="absolute -top-8 left-1/2 -translate-x-1/2 px-2 py-0.5 bg-card border border-border rounded text-[10px] text-nowrap opacity-0 group-hover:opacity-100 transition-opacity pointer-events-none z-10">
                {file.fileName.length > 20 ? file.fileName.slice(0, 17) + "..." : file.fileName}: {fr ? `${fr.overallRiskScore100}%` : "..."}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
