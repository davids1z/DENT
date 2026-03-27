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
      <GlassPanel>
        <div className="flex items-start justify-between mb-1">
          <div>
            <h3 className="text-lg font-semibold">Rezultat analize</h3>
            <span className="text-sm text-muted">{displayFileName}</span>
          </div>
          <div className="flex items-center gap-2 flex-shrink-0 flex-wrap justify-end">
            {riskLevel && (
              <span className={cn(
                "px-2.5 py-1 rounded-full text-xs font-medium border",
                riskLevel === "Critical" ? "bg-red-50 text-red-700 border-red-200" :
                riskLevel === "High" ? "bg-orange-50 text-orange-700 border-orange-200" :
                riskLevel === "Medium" ? "bg-amber-50 text-amber-700 border-amber-200" :
                "bg-green-50 text-green-700 border-green-200"
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

      {/* When damages are empty but forensic risk is high → show forensic modules */}
      {i.damages.length === 0 && i.status === "Completed" && (isHighRisk || isMediumRisk) && (
        <div className="space-y-3">
          <h3 className="text-xs font-medium text-muted uppercase tracking-wider">
            Forenzicki moduli ({modules.filter(m => m.riskScore > 0.10).length})
          </h3>
          {modules
            .filter(m => m.riskScore > 0.10 && !m.error)
            .sort((a, b) => b.riskScore - a.riskScore)
            .map((m, idx) => {
              const risk = m.riskScore;
              const color = risk >= 0.65 ? "#ef4444" : risk >= 0.40 ? "#f97316" : risk >= 0.20 ? "#f59e0b" : "#22c55e";
              const levelText = risk >= 0.65 ? "Kritican" : risk >= 0.40 ? "Visok" : risk >= 0.20 ? "Umjeren" : "Nizak";
              return (
                <div key={m.moduleName || idx} className="bg-white border border-gray-100 rounded-xl overflow-hidden shadow-sm">
                  <div className="h-1 w-full" style={{ backgroundColor: color }} />
                  <div className="p-4">
                    <div className="flex items-center gap-3 mb-2">
                      <div className="w-7 h-7 rounded-lg flex items-center justify-center text-xs font-bold flex-shrink-0" style={{ backgroundColor: color, color: "white" }}>
                        {idx + 1}
                      </div>
                      <div className="flex-1 min-w-0">
                        <span className="font-semibold text-sm block">{m.moduleLabel || m.moduleName}</span>
                        {m.findings?.length > 0 && (
                          <span className="text-xs text-slate-400 block truncate">
                            {m.findings[0]?.title || m.findings[0]?.code || ""}
                          </span>
                        )}
                      </div>
                      <span className="px-2.5 py-1 rounded-full text-xs font-medium border flex-shrink-0" style={{ backgroundColor: `${color}10`, color, borderColor: `${color}40` }}>
                        {levelText}
                      </span>
                    </div>
                    <div className="flex items-center gap-2 mt-3">
                      <span className="text-[10px] text-slate-400 flex-shrink-0">Rizik</span>
                      <div className="flex-1 h-1.5 bg-gray-100 rounded-full overflow-hidden">
                        <div className="h-full rounded-full transition-all duration-300" style={{ width: `${risk * 100}%`, backgroundColor: color }} />
                      </div>
                      <span className="text-xs text-slate-500 font-mono">{Math.round(risk * 100)}%</span>
                    </div>
                  </div>
                </div>
              );
            })}
        </div>
      )}

      {/* Low risk: show "all clear" + module summary so user sees WHY it's authentic */}
      {i.damages.length === 0 && i.status === "Completed" && !isHighRisk && !isMediumRisk && (
        <>
          <GlassPanel className="text-center">
            <div className="flex items-center justify-center gap-2 text-green-600 mb-2">
              <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M9 12.75L11.25 15 15 9.75M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
              </svg>
              <span className="font-medium">Nema sumnjivih nalaza</span>
            </div>
            <p className="text-muted text-sm">Svi forenzicki moduli potvrduju autenticnost sadrzaja.</p>
          </GlassPanel>

          {/* Show all modules that ran — proves thorough analysis */}
          {modules.length > 0 && (
            <div className="space-y-2">
              <h3 className="text-xs font-medium text-muted uppercase tracking-wider">
                Provedene provjere ({modules.filter(m => !m.error).length})
              </h3>
              {modules
                .filter(m => !m.error)
                .map((m, idx) => (
                  <div key={m.moduleName || idx} className="flex items-center gap-3 py-2 px-3 rounded-lg bg-green-50/50 border border-green-100">
                    <svg className="w-4 h-4 text-green-500 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
                      <path strokeLinecap="round" strokeLinejoin="round" d="M4.5 12.75l6 6 9-13.5" />
                    </svg>
                    <span className="text-sm text-green-800 flex-1">{m.moduleLabel || m.moduleName}</span>
                    <span className="text-xs text-green-600 font-mono">{Math.round(m.riskScore * 100)}%</span>
                  </div>
                ))}
            </div>
          )}
        </>
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
          "bg-white border border-gray-100 rounded-xl overflow-hidden cursor-pointer transition-all shadow-sm",
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
              <span className="text-xs text-slate-400 block truncate">{sanitizeLlmText(d.description).slice(0, 80)}...</span>
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
            <span className="text-[10px] text-slate-400 flex-shrink-0">Pouzdanost</span>
            <div className="flex-1 h-1.5 bg-gray-100 rounded-full overflow-hidden">
              <div className="h-full rounded-full transition-all duration-300" style={{ width: `${d.confidence * 100}%`, backgroundColor: borderColor }} />
            </div>
            <span className="text-xs text-slate-500 font-mono">{Math.round(d.confidence * 100)}%</span>
          </div>
        </div>

        {expanded && (
          <div className="px-4 pb-4 pt-3 border-t border-gray-50 bg-gray-50/50">
            <p className="text-sm text-slate-600 leading-relaxed mb-3">{sanitizeLlmText(d.description)}</p>
            <div className="grid grid-cols-2 gap-2 text-sm">
              {d.safetyRating && (() => {
                // Override safetyRating based on description content
                // Gemini may describe image as authentic while C# agent labels it Critical
                const desc = (d.description || "").toLowerCase();
                const descSaysAuthentic = ["autentičn", "konzistentn", "realistič", "potvrđuje autentičnost", "ne pokazuje znakove", "nema naznaka"].some(kw => desc.includes(kw));
                const descSaysManipulated = ["manipulacij", "krivotvor", "montaž", "zamućen", "prebrisano", "kopiran"].some(kw => desc.includes(kw));
                const effectiveRating = descSaysAuthentic && !descSaysManipulated ? "Safe" : d.safetyRating;
                return (
                  <div className="bg-white rounded-lg p-2 border border-gray-100">
                    <div className="text-slate-400 text-xs mb-0.5">Verdikt</div>
                    <div className={cn("font-medium", safetyRatingColor(effectiveRating))}>{safetyRatingLabel(effectiveRating)}</div>
                  </div>
                );
              })()}
              {d.damageCause && (
                <div className="bg-white rounded-lg p-2 border border-gray-100">
                  <div className="text-slate-400 text-xs mb-0.5">Kategorija</div>
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
