"use client";

import { cn } from "@/lib/cn";
import { getVerdictSentence } from "@/lib/forensicPillars";
import { ExportButton } from "./ExportButton";

interface TrustScoreHeroProps {
  riskScore: number;
  riskLevel: string;
  c2paStatus: string | null;
  predictedSource: string | null;
  sourceConfidence: number;
  totalProcessingTimeMs: number;
  inspectionId: string;
}

function trustColor(trust: number): string {
  if (trust >= 70) return "#16a34a";
  if (trust >= 40) return "#d97706";
  if (trust >= 20) return "#f97316";
  return "#dc2626";
}

function trustBg(riskLevel: string): string {
  switch (riskLevel) {
    case "Low": return "bg-green-500/10 border-green-500/20";
    case "Medium": return "bg-amber-500/10 border-amber-500/20";
    case "High": return "bg-orange-500/10 border-orange-500/20";
    case "Critical": return "bg-red-500/10 border-red-500/20";
    default: return "bg-card border-border";
  }
}

export function TrustScoreHero({
  riskScore,
  riskLevel,
  c2paStatus,
  predictedSource,
  sourceConfidence,
  totalProcessingTimeMs,
  inspectionId,
}: TrustScoreHeroProps) {
  const trust = Math.max(0, 100 - Math.round(riskScore * 100));
  const color = trustColor(trust);
  const verdict = getVerdictSentence(riskLevel, riskScore, c2paStatus);

  // SVG arc gauge
  const size = 160;
  const cx = size / 2;
  const cy = size / 2 + 5;
  const r = size / 2 - 14;
  const strokeWidth = 10;

  function polarToCartesian(angle: number) {
    const rad = (angle * Math.PI) / 180;
    return { x: cx + r * Math.cos(rad), y: cy - r * Math.sin(rad) };
  }

  const bgStart = polarToCartesian(180);
  const bgEnd = polarToCartesian(0);
  const bgArc = `M ${bgStart.x} ${bgStart.y} A ${r} ${r} 0 0 1 ${bgEnd.x} ${bgEnd.y}`;

  // Fill arc: trust 0% = 0deg sweep, trust 100% = 180deg sweep
  const fillAngle = 180 - (trust / 100) * 180;
  const fillEnd = polarToCartesian(fillAngle);
  const largeArc = trust > 50 ? 1 : 0;
  const fillArc = `M ${bgStart.x} ${bgStart.y} A ${r} ${r} 0 ${largeArc} 1 ${fillEnd.x} ${fillEnd.y}`;

  return (
    <div className={cn("rounded-xl border p-6", trustBg(riskLevel))}>
      <div className="flex flex-col md:flex-row items-center gap-6">
        {/* Gauge */}
        <div className="flex-shrink-0 flex flex-col items-center">
          <svg width={size} height={size / 2 + 24} viewBox={`0 0 ${size} ${size / 2 + 24}`}>
            {/* Background arc */}
            <path d={bgArc} fill="none" stroke="#e5e7eb" strokeWidth={strokeWidth} strokeLinecap="round" />
            {/* Fill arc */}
            <path d={fillArc} fill="none" stroke={color} strokeWidth={strokeWidth} strokeLinecap="round" />
            {/* Center text */}
            <text x={cx} y={cy - 12} textAnchor="middle" className="text-3xl font-bold" fill={color}>
              {trust}%
            </text>
            <text x={cx} y={cy + 6} textAnchor="middle" className="text-[11px]" fill="#64748b">
              POVJERENJE
            </text>
          </svg>
        </div>

        {/* Info */}
        <div className="flex-1 text-center md:text-left space-y-3">
          <p className="text-sm font-medium leading-relaxed" style={{ color }}>
            {verdict}
          </p>

          <div className="flex flex-wrap items-center gap-2 justify-center md:justify-start">
            {c2paStatus === "valid" && (
              <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium bg-green-500/15 text-green-600 dark:text-green-400 border border-green-500/20">
                <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M9 12.75L11.25 15 15 9.75M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                </svg>
                C2PA valjan
              </span>
            )}
            {c2paStatus === "ai_generated" && (
              <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium bg-red-500/15 text-red-600 dark:text-red-400 border border-red-500/20">
                C2PA: AI generirano
              </span>
            )}
            {predictedSource && (
              <span className="px-2 py-0.5 rounded-full text-xs font-medium bg-background/60 text-foreground border border-border">
                Izvor: {predictedSource} ({sourceConfidence}%)
              </span>
            )}
            <span className="px-2 py-0.5 rounded-full text-xs text-muted bg-background/40 border border-border">
              {totalProcessingTimeMs}ms
            </span>
          </div>

          <div className="pt-1">
            <ExportButton inspectionId={inspectionId} />
          </div>
        </div>
      </div>
    </div>
  );
}
