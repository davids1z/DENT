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
              <span className="px-2 py-0.5 sm:px-2.5 sm:py-1 rounded-full text-[10px] sm:text-xs font-medium border whitespace-nowrap bg-card text-muted border-border">
                {riskLevel === "Low" ? "Niska" : riskLevel === "Medium" ? "Srednja" : riskLevel === "High" ? "Visoka" : "Kritična"} hitnost
              </span>
            )}
          </div>
        </div>
      </GlassPanel>

      {(i.damages?.length ?? 0) > 0 && (
        <div className="space-y-3">
          <h3 className="text-xs font-medium text-muted uppercase tracking-wider">Detektirani nalazi ({(i.damages?.length ?? 0)})</h3>
          {(i.damages ?? []).map((d, idx) => (
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
      {(i.damages?.length ?? 0) === 0 && i.status === "Completed" && !isHighRisk && !isMediumRisk && (
        <GlassPanel className="text-center">
          <div className="flex items-center justify-center gap-2 text-green-600 mb-2">
            <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M9 12.75L11.25 15 15 9.75M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
            </svg>
            <span className="font-medium">Nema sumnjivih nalaza</span>
          </div>
          <p className="text-muted text-sm">Svi forenzički moduli potvrđuju autentičnost sadržaja.</p>
        </GlassPanel>
      )}

      {/* Module check list — clean, neutral rows */}
      {(i.damages?.length ?? 0) === 0 && i.status === "Completed" && modules.length > 0 && (
        <div>
          <div className="flex items-center justify-between mb-3">
            <h3 className="text-xs font-medium text-muted uppercase tracking-wider">
              Provedene provjere ({modules.filter(m => !m.error).length})
            </h3>
            <span className="text-[10px] text-muted">0% = čisto · 100% = sumnjivo</span>
          </div>
          <div className="border border-border rounded-xl overflow-hidden divide-y divide-border">
            {modules
              .filter(m => !m.error)
              .sort((a, b) => b.riskScore - a.riskScore)
              .map((m, idx) => {
                const pct = m.riskScore100;
                const barColor = m.riskScore >= 0.40 ? "bg-foreground" : "bg-muted/40";
                return (
                  <div key={m.moduleName || idx} className="flex items-center gap-3 py-2.5 px-3.5 bg-card">
                    <span className="text-sm text-foreground flex-1">{m.moduleLabel || m.moduleName}</span>
                    <div className="w-16 h-1.5 rounded-full bg-border overflow-hidden flex-shrink-0">
                      <div className={cn("h-full rounded-full", barColor)} style={{ width: `${pct}%` }} />
                    </div>
                    <span className={cn("text-xs font-mono w-8 text-right flex-shrink-0", m.riskScore >= 0.40 ? "text-foreground font-medium" : "text-muted")}>{pct}%</span>
                  </div>
                );
              })}
          </div>
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
