"use client";

import type { Inspection } from "@/lib/api";
import {
  formatCurrency,
  severityColor,
  severityBg,
  damageTypeLabel,
  carPartLabel,
} from "@/lib/api";

interface DamageReportProps {
  inspection: Inspection;
}

export function DamageReport({ inspection }: DamageReportProps) {
  const i = inspection;

  return (
    <div className="space-y-6 animate-fade-in">
      {/* Vehicle Info & Summary */}
      <div className="bg-card rounded-2xl border border-border p-6">
        <div className="flex items-start justify-between mb-4">
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
          <div className="flex items-center gap-2">
            {i.isDriveable !== null && (
              <span
                className={`px-3 py-1 rounded-full text-xs font-medium border ${
                  i.isDriveable
                    ? "bg-green-400/10 text-green-400 border-green-400/20"
                    : "bg-red-400/10 text-red-400 border-red-400/20"
                }`}
              >
                {i.isDriveable ? "Vozno" : "Nije vozno"}
              </span>
            )}
            {i.urgencyLevel && (
              <span
                className={`px-3 py-1 rounded-full text-xs font-medium border ${severityBg(
                  i.urgencyLevel
                )} ${severityColor(i.urgencyLevel)}`}
              >
                {i.urgencyLevel} hitnost
              </span>
            )}
          </div>
        </div>
        {i.summary && <p className="text-muted text-sm leading-relaxed">{i.summary}</p>}
      </div>

      {/* Cost Estimate */}
      <div className="bg-card rounded-2xl border border-border p-6">
        <h3 className="text-sm font-medium text-muted uppercase tracking-wider mb-3">
          Ukupna procjena troska
        </h3>
        <div className="flex items-baseline gap-2">
          <span className="text-3xl font-bold text-accent">
            {formatCurrency(i.totalEstimatedCostMin)}
          </span>
          {i.totalEstimatedCostMax && i.totalEstimatedCostMax !== i.totalEstimatedCostMin && (
            <>
              <span className="text-muted">-</span>
              <span className="text-3xl font-bold text-accent">
                {formatCurrency(i.totalEstimatedCostMax)}
              </span>
            </>
          )}
        </div>
      </div>

      {/* Individual Damages */}
      <div className="space-y-3">
        <h3 className="text-sm font-medium text-muted uppercase tracking-wider">
          Detektirane stete ({i.damages.length})
        </h3>
        {i.damages.map((d, idx) => (
          <div
            key={d.id || idx}
            className="bg-card rounded-2xl border border-border p-5 hover:border-accent/30 transition-colors"
            style={{ animationDelay: `${idx * 100}ms` }}
          >
            <div className="flex items-start justify-between mb-3">
              <div className="flex items-center gap-3">
                <div
                  className={`w-2 h-2 rounded-full ${
                    d.severity === "Critical"
                      ? "bg-red-400"
                      : d.severity === "Severe"
                      ? "bg-orange-400"
                      : d.severity === "Moderate"
                      ? "bg-yellow-400"
                      : "bg-green-400"
                  }`}
                />
                <div>
                  <span className="font-medium">{damageTypeLabel(d.damageType)}</span>
                  <span className="text-muted mx-2">na</span>
                  <span className="font-medium">{carPartLabel(d.carPart)}</span>
                </div>
              </div>
              <span
                className={`px-2.5 py-0.5 rounded-full text-xs font-medium border ${severityBg(
                  d.severity
                )} ${severityColor(d.severity)}`}
              >
                {d.severity}
              </span>
            </div>

            <p className="text-sm text-muted mb-3">{d.description}</p>

            <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 text-sm">
              <div className="bg-background/50 rounded-lg p-2.5">
                <div className="text-muted text-xs mb-0.5">Trosak</div>
                <div className="font-medium">
                  {formatCurrency(d.estimatedCostMin)}
                  {d.estimatedCostMax && d.estimatedCostMax !== d.estimatedCostMin
                    ? ` - ${formatCurrency(d.estimatedCostMax)}`
                    : ""}
                </div>
              </div>
              {d.laborHours && (
                <div className="bg-background/50 rounded-lg p-2.5">
                  <div className="text-muted text-xs mb-0.5">Rad</div>
                  <div className="font-medium">{d.laborHours}h</div>
                </div>
              )}
              {d.repairMethod && (
                <div className="bg-background/50 rounded-lg p-2.5 col-span-2">
                  <div className="text-muted text-xs mb-0.5">Metoda popravka</div>
                  <div className="font-medium">{d.repairMethod}</div>
                </div>
              )}
            </div>

            {d.partsNeeded && (
              <div className="mt-2 text-xs text-muted">
                Potrebni dijelovi: {d.partsNeeded}
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
