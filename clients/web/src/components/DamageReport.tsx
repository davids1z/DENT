"use client";

import { useState, useEffect, useRef } from "react";
import type { Inspection } from "@/lib/api";
import {
  formatCurrency,
  severityColor,
  severityBg,
  damageTypeLabel,
  carPartLabel,
  severityLabel,
  urgencyLabel,
  repairCategoryLabel,
  repairCategoryColor,
  safetyRatingLabel,
  safetyRatingColor,
} from "@/lib/api";
import { GlassPanel } from "@/components/ui/GlassPanel";
import { cn } from "@/lib/cn";

interface DamageReportProps {
  inspection: Inspection;
  selectedDamageIndex?: number | null;
  onSelectDamage?: (index: number | null) => void;
}

export function DamageReport({ inspection, selectedDamageIndex, onSelectDamage }: DamageReportProps) {
  const i = inspection;

  return (
    <div className="space-y-4">
      <GlassPanel>
        <div className="flex items-start justify-between mb-3">
          <div>
            <h3 className="text-lg font-semibold">
              {i.vehicleMake && i.vehicleModel
                ? `${i.vehicleMake} ${i.vehicleModel}${i.vehicleYear ? ` (${i.vehicleYear})` : ""}`
                : "Nepoznato vozilo"}
            </h3>
            {i.vehicleColor && (
              <span className="text-sm text-muted">Boja: {i.vehicleColor}</span>
            )}
          </div>
          <div className="flex items-center gap-2 flex-shrink-0 flex-wrap justify-end">
            {i.isDriveable !== null && (
              <span className={cn(
                "px-2.5 py-1 rounded-full text-xs font-medium border",
                i.isDriveable
                  ? "bg-green-50 text-green-700 border-green-200"
                  : "bg-red-50 text-red-700 border-red-200"
              )}>
                {i.isDriveable ? "Vozno" : "Nije vozno"}
              </span>
            )}
            {i.urgencyLevel && (
              <span className={cn(
                "px-2.5 py-1 rounded-full text-xs font-medium border",
                severityBg(i.urgencyLevel), severityColor(i.urgencyLevel)
              )}>
                {urgencyLabel(i.urgencyLevel)} hitnost
              </span>
            )}
          </div>
        </div>
        {i.summary && <p className="text-muted text-sm leading-relaxed">{i.summary}</p>}
      </GlassPanel>

      {(i.totalEstimatedCostMin != null || i.totalEstimatedCostMax != null || i.grossTotal != null) && (
        <GlassPanel>
          <h3 className="text-xs font-medium text-muted uppercase tracking-wider mb-2">Ukupna procjena troska</h3>
          {i.grossTotal != null ? (
            <div>
              <div className="text-2xl font-bold text-accent mb-2">{formatCurrency(i.grossTotal)}</div>
              <div className="grid grid-cols-3 gap-2 text-xs">
                {i.laborTotal != null && (
                  <div className="bg-gray-50 rounded-lg p-2">
                    <div className="text-muted mb-0.5">Rad</div>
                    <div className="font-medium">{formatCurrency(i.laborTotal)}</div>
                  </div>
                )}
                {i.partsTotal != null && (
                  <div className="bg-gray-50 rounded-lg p-2">
                    <div className="text-muted mb-0.5">Dijelovi</div>
                    <div className="font-medium">{formatCurrency(i.partsTotal)}</div>
                  </div>
                )}
                {i.materialsTotal != null && (
                  <div className="bg-gray-50 rounded-lg p-2">
                    <div className="text-muted mb-0.5">Materijali</div>
                    <div className="font-medium">{formatCurrency(i.materialsTotal)}</div>
                  </div>
                )}
              </div>
            </div>
          ) : (
            <div className="flex items-baseline gap-2">
              <span className="text-2xl font-bold text-accent">{formatCurrency(i.totalEstimatedCostMin)}</span>
              {i.totalEstimatedCostMax && i.totalEstimatedCostMax !== i.totalEstimatedCostMin && (
                <>
                  <span className="text-muted">-</span>
                  <span className="text-2xl font-bold text-accent">{formatCurrency(i.totalEstimatedCostMax)}</span>
                </>
              )}
            </div>
          )}
        </GlassPanel>
      )}

      {i.damages.length > 0 && (
        <div className="space-y-3">
          <h3 className="text-xs font-medium text-muted uppercase tracking-wider">Detektirane štete ({i.damages.length})</h3>
          {i.damages.map((d, idx) => (
            <DamageCard
              key={d.id || idx}
              damage={d}
              index={idx}
              isSelected={selectedDamageIndex === idx}
              onSelect={() => onSelectDamage?.(selectedDamageIndex === idx ? null : idx)}
            />
          ))}
        </div>
      )}

      {i.damages.length === 0 && i.status === "Completed" && (
        <GlassPanel className="text-center">
          <p className="text-muted">Nisu detektirana oštećenja na vozilu.</p>
        </GlassPanel>
      )}
    </div>
  );
}

function DamageCard({ damage: d, index, isSelected, onSelect }: {
  damage: Inspection["damages"][0]; index: number; isSelected: boolean; onSelect: () => void;
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
  const borderColor = d.repairCategory ? repairCategoryColor(d.repairCategory) : severityColorMap[d.severity] || "#71717a";

  return (
    <div ref={cardRef}>
      <div
        className={cn("bg-card border border-border rounded-xl overflow-hidden cursor-pointer transition-colors", isSelected && "ring-1 ring-accent/30")}
        style={{ borderLeftWidth: "3px", borderLeftColor: borderColor }}
      >
        <div className="p-4" onClick={() => { setExpanded(!expanded); onSelect(); }}>
          <div className="flex items-start justify-between mb-2">
            <div className="flex items-center gap-2 min-w-0">
              <div className="w-5 h-5 rounded-full flex items-center justify-center text-[10px] font-bold flex-shrink-0" style={{ backgroundColor: borderColor, color: "white" }}>{index + 1}</div>
              <span className="font-medium text-sm">{damageTypeLabel(d.damageType)}</span>
              <span className="text-muted text-xs">&mdash;</span>
              <span className="text-sm text-muted truncate">{carPartLabel(d.carPart)}</span>
            </div>
            <div className="flex items-center gap-2 flex-shrink-0 ml-2">
              <span className={cn("px-2 py-0.5 rounded-full text-xs font-medium border", severityBg(d.severity), severityColor(d.severity))}>{severityLabel(d.severity)}</span>
              {d.repairCategory && (
                <span className="px-2 py-0.5 rounded-full text-xs font-medium border" style={{ backgroundColor: `${borderColor}15`, borderColor: `${borderColor}30`, color: borderColor }}>{repairCategoryLabel(d.repairCategory)}</span>
              )}
              <svg className={cn("w-4 h-4 text-muted transition-transform", expanded && "rotate-180")} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M19.5 8.25l-7.5 7.5-7.5-7.5" />
              </svg>
            </div>
          </div>
          <p className="text-sm text-muted leading-relaxed">{d.description}</p>
          <div className="flex items-center gap-2 mt-2">
            <div className="flex-1 h-1 bg-gray-100 rounded-full overflow-hidden">
              <div className="h-full rounded-full" style={{ width: `${d.confidence * 100}%`, backgroundColor: borderColor }} />
            </div>
            <span className="text-[10px] text-muted font-mono">{Math.round(d.confidence * 100)}%</span>
          </div>
        </div>
        {expanded && (
          <div className="px-4 pb-4 pt-1 border-t border-border">
            <div className="grid grid-cols-2 sm:grid-cols-3 gap-2 text-sm">
              {(d.estimatedCostMin != null || d.estimatedCostMax != null) && (
                <div className="bg-gray-50 rounded-lg p-2">
                  <div className="text-muted text-xs mb-0.5">Trošak</div>
                  <div className="font-medium text-accent">{formatCurrency(d.estimatedCostMin)}{d.estimatedCostMax && d.estimatedCostMax !== d.estimatedCostMin ? ` - ${formatCurrency(d.estimatedCostMax)}` : ""}</div>
                </div>
              )}
              {d.laborHours != null && (<div className="bg-gray-50 rounded-lg p-2"><div className="text-muted text-xs mb-0.5">Sati rada</div><div className="font-medium">{d.laborHours}h</div></div>)}
              {d.repairMethod && (<div className="bg-gray-50 rounded-lg p-2 col-span-2 sm:col-span-1"><div className="text-muted text-xs mb-0.5">Metoda popravka</div><div className="font-medium">{d.repairMethod}</div></div>)}
            </div>
            <div className="grid grid-cols-2 sm:grid-cols-3 gap-2 text-sm mt-2">
              {d.safetyRating && (<div className="bg-gray-50 rounded-lg p-2"><div className="text-muted text-xs mb-0.5">Sigurnost</div><div className={cn("font-medium", safetyRatingColor(d.safetyRating))}>{safetyRatingLabel(d.safetyRating)}</div></div>)}
              {d.materialType && (<div className="bg-gray-50 rounded-lg p-2"><div className="text-muted text-xs mb-0.5">Materijal</div><div className="font-medium">{d.materialType}</div></div>)}
              {d.damageCause && (<div className="bg-gray-50 rounded-lg p-2 col-span-2 sm:col-span-1"><div className="text-muted text-xs mb-0.5">Uzrok</div><div className="font-medium">{d.damageCause}</div></div>)}
            </div>
            {d.partsNeeded && (<div className="mt-2 text-xs text-muted"><span className="text-foreground/60">Dijelovi:</span> {d.partsNeeded}</div>)}
            {d.repairOperations && (<div className="mt-2"><div className="text-xs text-foreground/60 mb-1">Operacije popravka:</div><div className="text-xs text-muted leading-relaxed bg-gray-50 rounded-lg p-2">{d.repairOperations}</div></div>)}
          </div>
        )}
      </div>
    </div>
  );
}
