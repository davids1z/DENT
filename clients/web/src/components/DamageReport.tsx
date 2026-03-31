"use client";

import { useState, useEffect, useRef } from "react";
import type { Inspection, ForensicResult } from "@/lib/api";
import {
  severityColor,
  severityBg,
  severityLabel,
  safetyRatingLabel,
  safetyRatingColor,
} from "@/lib/api";
import { sanitizeLlmText, deriveFindingCategory } from "@/lib/forensicPillars";
import { GlassPanel } from "@/components/ui/GlassPanel";
import { cn } from "@/lib/cn";

interface DamageReportProps {
  inspection: Inspection;
  selectedDamageIndex?: number | null;
  onSelectDamage?: (index: number | null) => void;
  forensicResult?: ForensicResult | null;
}

export function DamageReport({ inspection, selectedDamageIndex, onSelectDamage, forensicResult }: DamageReportProps) {
  const i = inspection;
  const fr = forensicResult || i.forensicResult;
  const riskScore = fr?.overallRiskScore ?? i.fraudRiskScore ?? 0;
  const riskLevel = fr?.overallRiskLevel ?? i.fraudRiskLevel ?? "Low";
  const isHighRisk = riskScore >= 0.40;
  const isMediumRisk = riskScore >= 0.15;

  // Forensic module results from the active file's ForensicResult
  const modules = fr?.modules ?? [];

  // Show the active file's name if we have per-file forensic data
  const displayFileName = fr?.fileName || i.originalFileName;

  return (
    <div className="space-y-4">
      <GlassPanel className="p-3 sm:p-5">
        <div className="flex items-start justify-between gap-2 mb-1">
          <div className="min-w-0">
            <h3 className="text-base sm:text-lg font-semibold">Rezultat analize</h3>
            <span className="text-xs sm:text-sm text-muted block truncate">{displayFileName}</span>
          </div>
          <div className="flex items-center gap-2 flex-shrink-0">
            {riskLevel && (
              <span className={cn(
                "px-2 py-0.5 sm:px-2.5 sm:py-1 rounded-full text-[10px] sm:text-xs font-medium border whitespace-nowrap",
                riskLevel === "Critical" ? "bg-red-500/10 text-red-600 dark:text-red-400 border-red-500/20" :
                riskLevel === "High" ? "bg-orange-500/10 text-orange-600 dark:text-orange-400 border-orange-500/20" :
                riskLevel === "Medium" ? "bg-amber-500/10 text-amber-600 dark:text-amber-400 border-amber-500/20" :
                "bg-green-500/10 text-green-600 dark:text-green-400 border-green-500/20"
              )}>
                {riskLevel === "Low" ? "Niska" : riskLevel === "Medium" ? "Srednja" : riskLevel === "High" ? "Visoka" : "Kriticna"} hitnost
              </span>
            )}
          </div>
        </div>
      </GlassPanel>

      {i.damages.length > 0 && (
        <div className="space-y-3">
          <h3 className="text-xs font-medium text-muted uppercase tracking-wider">Detektirani nalazi ({i.damages.length})</h3>
          {i.damages.map((d, idx) => (
            <FindingCard
              key={d.id || idx}
              damage={d}
              index={idx}
              isSelected={selectedDamageIndex === idx}
              onSelect={() => onSelectDamage?.(selectedDamageIndex === idx ? null : idx)}
              forensicResult={forensicResult}
            />
          ))}
        </div>
      )}

      {/* Low risk: show "all clear" banner */}
      {i.damages.length === 0 && i.status === "Completed" && !isHighRisk && !isMediumRisk && (
        <GlassPanel className="text-center">
          <div className="flex items-center justify-center gap-2 text-green-600 mb-2">
            <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M9 12.75L11.25 15 15 9.75M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
            </svg>
            <span className="font-medium">Nema sumnjivih nalaza</span>
          </div>
          <p className="text-muted text-sm">Svi forenzicki moduli potvrduju autenticnost sadrzaja.</p>
        </GlassPanel>
      )}

      {/* Unified module list — same layout for ALL risk levels */}
      {i.damages.length === 0 && i.status === "Completed" && modules.length > 0 && (
        <div className="space-y-2">
          <h3 className="text-xs font-medium text-muted uppercase tracking-wider">
            Provedene provjere ({modules.filter(m => !m.error).length})
          </h3>
          {modules
            .filter(m => !m.error)
            .sort((a, b) => b.riskScore - a.riskScore)
            .map((m, idx) => {
              const risk = m.riskScore;
              const iconColor = risk >= 0.65 ? "text-red-500" : risk >= 0.40 ? "text-orange-500" : risk >= 0.20 ? "text-amber-500" : "text-green-500";
              const bgColor = risk >= 0.65 ? "bg-red-500/10 border-red-500/15" : risk >= 0.40 ? "bg-orange-500/10 border-orange-500/15" : risk >= 0.20 ? "bg-amber-500/10 border-amber-500/15" : "bg-green-500/10 border-green-500/15";
              const textColor = risk >= 0.65 ? "text-red-600 dark:text-red-400" : risk >= 0.40 ? "text-orange-600 dark:text-orange-400" : risk >= 0.20 ? "text-amber-600 dark:text-amber-400" : "text-green-600 dark:text-green-400";
              const isPass = risk < 0.20;
              return (
                <div key={m.moduleName || idx} className={cn("flex items-center gap-3 py-2 px-3 rounded-lg border", bgColor)}>
                  {isPass ? (
                    <svg className={cn("w-4 h-4 flex-shrink-0", iconColor)} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
                      <path strokeLinecap="round" strokeLinejoin="round" d="M4.5 12.75l6 6 9-13.5" />
                    </svg>
                  ) : (
                    <svg className={cn("w-4 h-4 flex-shrink-0", iconColor)} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                      <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v3.75m-9.303 3.376c-.866 1.5.217 3.374 1.948 3.374h14.71c1.73 0 2.813-1.874 1.948-3.374L13.949 3.378c-.866-1.5-3.032-1.5-3.898 0L2.697 16.126zM12 15.75h.007v.008H12v-.008z" />
                    </svg>
                  )}
                  <span className={cn("text-sm flex-1", textColor)}>{m.moduleLabel || m.moduleName}</span>
                  <span className={cn("text-xs font-mono", textColor)}>{Math.round(risk * 100)}%</span>
                </div>
              );
            })}
        </div>
      )}
    </div>
  );
}

function FindingCard({ damage: d, index, isSelected, onSelect, forensicResult }: {
  damage: Inspection["damages"][0]; index: number; isSelected: boolean; onSelect: () => void; forensicResult?: ForensicResult | null;
}) {
  const [expanded, setExpanded] = useState(false);
  const cardRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (isSelected && !expanded) {
      setExpanded(true);
      cardRef.current?.scrollIntoView({ behavior: "smooth", block: "nearest" });
    }
  }, [isSelected]);

  const severityColorMap: Record<string, string> = {
    Critical: "#ef4444", Severe: "#f97316", Moderate: "#f59e0b", Minor: "#22c55e",
  };
  const borderColor = severityColorMap[d.severity] || "#71717a";

  return (
    <div ref={cardRef}>
      <div
        className={cn(
          "bg-background border border-border rounded-xl overflow-hidden cursor-pointer transition-all shadow-sm",
          isSelected && "ring-2 ring-accent/20"
        )}
      >
        {/* Top severity stripe */}
        <div className="h-1 w-full" style={{ backgroundColor: borderColor }} />

        <div className="p-4" onClick={() => { setExpanded(!expanded); onSelect(); }}>
          <div className="flex items-center gap-3 mb-2">
            <div
              className="w-7 h-7 rounded-lg flex items-center justify-center text-xs font-bold flex-shrink-0"
              style={{ backgroundColor: borderColor, color: "white" }}
            >
              {index + 1}
            </div>
            <div className="flex-1 min-w-0">
              <span className="font-semibold text-sm block">{deriveFindingCategory(d, forensicResult ?? null)}</span>
              <span className="text-xs text-muted-light block truncate">{sanitizeLlmText(d.description).slice(0, 80)}...</span>
            </div>
            <span className={cn("px-2.5 py-1 rounded-full text-xs font-medium border flex-shrink-0", severityBg(d.severity), severityColor(d.severity))}>
              {severityLabel(d.severity)}
            </span>
            <svg className={cn("w-4 h-4 text-muted transition-transform flex-shrink-0", expanded && "rotate-180")} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M19.5 8.25l-7.5 7.5-7.5-7.5" />
            </svg>
          </div>

          {/* Confidence bar */}
          <div className="flex items-center gap-2 mt-3">
            <span className="text-[10px] text-muted-light flex-shrink-0">Pouzdanost</span>
            <div className="flex-1 h-1.5 bg-card-hover rounded-full overflow-hidden">
              <div className="h-full rounded-full transition-all duration-300" style={{ width: `${d.confidence * 100}%`, backgroundColor: borderColor }} />
            </div>
            <span className="text-xs text-muted font-mono">{Math.round(d.confidence * 100)}%</span>
          </div>
        </div>

        {expanded && (
          <div className="px-4 pb-4 pt-3 border-t border-border bg-card/50">
            <p className="text-sm text-muted leading-relaxed mb-3">{sanitizeLlmText(d.description)}</p>
            <div className="grid grid-cols-2 gap-2 text-sm">
              {d.safetyRating && (
                <div className="bg-background rounded-lg p-2 border border-border">
                  <div className="text-muted-light text-xs mb-0.5">Verdikt</div>
                  <div className={cn("font-medium", safetyRatingColor(d.safetyRating))}>{safetyRatingLabel(d.safetyRating)}</div>
                </div>
              )}
              {d.damageCause && (
                <div className="bg-background rounded-lg p-2 border border-border">
                  <div className="text-muted-light text-xs mb-0.5">Kategorija</div>
                  <div className="font-medium">{deriveFindingCategory(d, forensicResult ?? null)}</div>
                </div>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
