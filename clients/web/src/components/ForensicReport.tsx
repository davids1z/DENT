"use client";

import { useState } from "react";
import type { ForensicResult } from "@/lib/api";
import { forensicModuleLabel, fraudRiskColor, fraudRiskLabel } from "@/lib/api";
import { cn } from "@/lib/cn";

interface ForensicReportProps {
  result: ForensicResult;
}

export function ForensicReport({ result }: ForensicReportProps) {
  const [expanded, setExpanded] = useState(true);

  if (result.modules.length === 0) return null;

  const modulesWithFindings = result.modules.filter(
    (m) => m.findings.length > 0 || m.error
  ).length;

  return (
    <div className="bg-card border border-border rounded-xl overflow-hidden">
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full flex items-center justify-between px-4 py-3 text-left hover:bg-card-hover transition-colors"
      >
        <div className="flex items-center gap-2">
          <ShieldSearchIcon />
          <span className="text-sm font-medium">Forenzicki izvjestaj</span>
          <span className="text-xs text-muted">
            ({modulesWithFindings}/{result.modules.length} modula s nalazima)
          </span>
        </div>
        <div className="flex items-center gap-2">
          <span className="text-xs text-muted">
            {result.totalProcessingTimeMs}ms
          </span>
          <svg
            className={cn(
              "w-4 h-4 text-muted transition-transform",
              expanded && "rotate-180"
            )}
            fill="none"
            viewBox="0 0 24 24"
            stroke="currentColor"
            strokeWidth={1.5}
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              d="M19.5 8.25l-7.5 7.5-7.5-7.5"
            />
          </svg>
        </div>
      </button>

      {expanded && (
        <div className="px-4 pb-4 space-y-3">
          {/* Overall risk bar */}
          <div className="px-3 py-2 bg-card rounded-lg">
            <div className="flex items-center justify-between mb-1">
              <span className="text-xs text-muted">Ukupni rizik</span>
              <span
                className={cn(
                  "text-xs font-bold",
                  fraudRiskColor(result.overallRiskLevel)
                )}
              >
                {Math.round(result.overallRiskScore * 100)}% -{" "}
                {fraudRiskLabel(result.overallRiskLevel)}
              </span>
            </div>
            <div className="h-2 bg-border rounded-full overflow-hidden">
              <div
                className={cn(
                  "h-full rounded-full transition-all",
                  result.overallRiskLevel === "Low" && "bg-green-500",
                  result.overallRiskLevel === "Medium" && "bg-amber-500",
                  result.overallRiskLevel === "High" && "bg-orange-500",
                  result.overallRiskLevel === "Critical" && "bg-red-500"
                )}
                style={{ width: `${Math.round(result.overallRiskScore * 100)}%` }}
              />
            </div>
          </div>

          {/* Modules */}
          {result.modules.map((mod, i) => (
            <ModuleCard key={i} module={mod} />
          ))}
        </div>
      )}
    </div>
  );
}

function ModuleCard({
  module: mod,
}: {
  module: ForensicResult["modules"][number];
}) {
  const [open, setOpen] = useState(false);
  const hasFindings = mod.findings.length > 0;
  const riskPct = Math.round(mod.riskScore * 100);

  return (
    <div
      className={cn(
        "rounded-lg border text-sm",
        mod.error
          ? "border-red-500/20 bg-red-500/10"
          : hasFindings
            ? "border-amber-500/20 bg-amber-500/10"
            : "border-border bg-card/50"
      )}
    >
      <button
        onClick={() => setOpen(!open)}
        className="w-full flex items-center justify-between px-3 py-2 text-left"
      >
        <div className="flex items-center gap-2 min-w-0">
          <span className="font-medium truncate">
            {forensicModuleLabel(mod.moduleName)}
          </span>
          {mod.error && (
            <span className="text-[10px] px-1.5 py-0.5 bg-red-500/15 text-red-600 dark:text-red-400 rounded">
              Greska
            </span>
          )}
        </div>
        <div className="flex items-center gap-2 flex-shrink-0">
          <span className="text-xs text-muted">{mod.processingTimeMs}ms</span>
          <div className="w-16 h-1.5 bg-border rounded-full overflow-hidden">
            <div
              className={cn(
                "h-full rounded-full",
                mod.riskLevel === "Low" && "bg-green-500",
                mod.riskLevel === "Medium" && "bg-amber-500",
                mod.riskLevel === "High" && "bg-orange-500",
                mod.riskLevel === "Critical" && "bg-red-500"
              )}
              style={{ width: `${riskPct}%` }}
            />
          </div>
          <span
            className={cn(
              "text-xs font-mono w-8 text-right",
              fraudRiskColor(mod.riskLevel)
            )}
          >
            {riskPct}%
          </span>
          <svg
            className={cn(
              "w-3 h-3 text-muted transition-transform",
              open && "rotate-180"
            )}
            fill="none"
            viewBox="0 0 24 24"
            stroke="currentColor"
            strokeWidth={2}
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              d="M19.5 8.25l-7.5 7.5-7.5-7.5"
            />
          </svg>
        </div>
      </button>

      {open && (
        <div className="px-3 pb-2 space-y-1.5">
          {mod.error && (
            <p className="text-xs text-red-600">{mod.error}</p>
          )}
          {mod.findings.map((f, j) => (
            <div
              key={j}
              className="flex items-start gap-2 px-2 py-1.5 bg-background/60 rounded border border-border"
            >
              <div
                className={cn(
                  "w-1.5 h-1.5 rounded-full mt-1.5 flex-shrink-0",
                  f.riskScore >= 0.5
                    ? "bg-red-500"
                    : f.riskScore >= 0.25
                      ? "bg-amber-500"
                      : "bg-green-500"
                )}
              />
              <div className="min-w-0 flex-1">
                <div className="flex items-center justify-between gap-2">
                  <span className="text-xs font-medium">{f.title}</span>
                  <span className="text-[10px] font-mono text-muted flex-shrink-0">
                    {Math.round(f.confidence * 100)}% sig.
                  </span>
                </div>
                <p className="text-[11px] text-muted mt-0.5 leading-relaxed">
                  {f.description}
                </p>
              </div>
            </div>
          ))}
          {!mod.error && mod.findings.length === 0 && (
            <p className="text-xs text-muted px-2 py-1">Nema nalaza</p>
          )}
        </div>
      )}
    </div>
  );
}

function ShieldSearchIcon() {
  return (
    <svg
      className="w-4 h-4 text-muted"
      fill="none"
      viewBox="0 0 24 24"
      stroke="currentColor"
      strokeWidth={1.5}
    >
      <path
        strokeLinecap="round"
        strokeLinejoin="round"
        d="M9 12.75L11.25 15 15 9.75m-3-7.036A11.959 11.959 0 013.598 6 11.99 11.99 0 003 9.749c0 5.592 3.824 10.29 9 11.623 5.176-1.332 9-6.03 9-11.622 0-1.31-.21-2.571-.598-3.751h-.152c-3.196 0-6.1-1.248-8.25-3.285z"
      />
    </svg>
  );
}
