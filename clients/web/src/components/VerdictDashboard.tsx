"use client";

import { useEffect, useState } from "react";
import { cn } from "@/lib/cn";
import { ExportButton } from "./ExportButton";

interface VerdictDashboardProps {
  riskScore: number;
  riskLevel: string;
  c2paStatus: string | null;
  predictedSource: string | null;
  sourceConfidence: number;
  totalProcessingTimeMs: number;
  inspectionId: string;
}

// 3-class verdict from risk score
type VerdictClass = "authentic" | "ai_generated" | "tampered";

function getVerdict(riskScore: number, riskLevel: string): {
  cls: VerdictClass;
  label: string;
  confidence: number;
  color: string;
  glow: string;
  bg: string;
  scores: { authentic: number; ai_generated: number; tampered: number };
} {
  const risk = riskScore * 100;

  if (riskLevel === "Critical" || risk >= 75) {
    const conf = Math.min(99.5, 70 + risk * 0.35);
    return {
      cls: "ai_generated",
      label: "UMJETNO GENERIRANA SLIKA",
      confidence: conf,
      color: "#a855f7",
      glow: "drop-shadow(0 0 12px rgba(168,85,247,0.5))",
      bg: "bg-purple-950/30 border-purple-500/30",
      scores: {
        authentic: Math.max(0.5, 100 - conf - (100 - conf) * 0.4),
        ai_generated: conf,
        tampered: Math.max(0.5, (100 - conf) * 0.4),
      },
    };
  }

  if (riskLevel === "High" || risk >= 40) {
    const conf = Math.min(85, 40 + risk * 0.6);
    return {
      cls: "tampered",
      label: "DIGITALNO IZMIJENJENA SLIKA",
      confidence: conf,
      color: "#f97316",
      glow: "drop-shadow(0 0 12px rgba(249,115,22,0.5))",
      bg: "bg-orange-950/30 border-orange-500/30",
      scores: {
        authentic: Math.max(2, 100 - conf - conf * 0.15),
        ai_generated: Math.max(2, conf * 0.15),
        tampered: conf,
      },
    };
  }

  const conf = Math.min(99, 60 + (100 - risk) * 0.4);
  return {
    cls: "authentic",
    label: "AUTENTIČNA FOTOGRAFIJA",
    confidence: conf,
    color: "#22c55e",
    glow: "drop-shadow(0 0 12px rgba(34,197,94,0.5))",
    bg: "bg-green-950/20 border-green-500/20",
    scores: {
      authentic: conf,
      ai_generated: Math.max(0.5, (100 - conf) * 0.6),
      tampered: Math.max(0.5, (100 - conf) * 0.4),
    },
  };
}

// ── Animated Gauge ─────────────────────────────────────────────────

function Gauge({
  value,
  color,
  glow,
  animated,
}: {
  value: number;
  color: string;
  glow: string;
  animated: boolean;
}) {
  const size = 200;
  const cx = size / 2;
  const cy = size / 2 + 8;
  const r = size / 2 - 18;
  const strokeWidth = 14;

  const startAngle = 180;
  const endAngle = 0;
  const sweepAngle = (value / 100) * 180;
  const currentAngle = startAngle - (animated ? sweepAngle : 0);

  function polarToCartesian(angle: number) {
    const rad = (angle * Math.PI) / 180;
    return { x: cx + r * Math.cos(rad), y: cy - r * Math.sin(rad) };
  }

  const bgStart = polarToCartesian(startAngle);
  const bgEnd = polarToCartesian(endAngle);
  const bgArc = `M ${bgStart.x} ${bgStart.y} A ${r} ${r} 0 0 1 ${bgEnd.x} ${bgEnd.y}`;

  const fillEnd = polarToCartesian(currentAngle);
  const largeArc = sweepAngle > 90 ? 1 : 0;
  const fillArc = `M ${bgStart.x} ${bgStart.y} A ${r} ${r} 0 ${largeArc} 1 ${fillEnd.x} ${fillEnd.y}`;

  return (
    <svg width={size} height={size / 2 + 30} viewBox={`0 0 ${size} ${size / 2 + 30}`}>
      {/* Glow filter */}
      <defs>
        <filter id="gauge-glow">
          <feGaussianBlur stdDeviation="3" result="blur" />
          <feMerge>
            <feMergeNode in="blur" />
            <feMergeNode in="SourceGraphic" />
          </feMerge>
        </filter>
        <linearGradient id="gauge-gradient" x1="0%" y1="0%" x2="100%" y2="0%">
          <stop offset="0%" stopColor={color} stopOpacity="0.6" />
          <stop offset="100%" stopColor={color} stopOpacity="1" />
        </linearGradient>
      </defs>

      {/* Background arc */}
      <path
        d={bgArc}
        fill="none"
        stroke="#1e1e2e"
        strokeWidth={strokeWidth}
        strokeLinecap="round"
      />

      {/* Fill arc with glow */}
      <path
        d={fillArc}
        fill="none"
        stroke="url(#gauge-gradient)"
        strokeWidth={strokeWidth}
        strokeLinecap="round"
        filter="url(#gauge-glow)"
        style={{
          transition: animated ? "none" : "all 1.5s cubic-bezier(0.4, 0, 0.2, 1)",
        }}
      />

      {/* Center text */}
      <text
        x={cx}
        y={cy - 14}
        textAnchor="middle"
        fill={color}
        fontSize="36"
        fontWeight="bold"
        style={{ filter: glow, opacity: animated ? 1 : 0, transition: "opacity 0.5s ease-in 1.2s" }}
      >
        {animated ? value.toFixed(1) : "0.0"}%
      </text>
      <text x={cx} y={cy + 8} textAnchor="middle" fill="#94a3b8" fontSize="11" letterSpacing="2">
        POUZDANOST
      </text>
    </svg>
  );
}

// ── Confidence Bar ─────────────────────────────────────────────────

function ConfidenceBar({
  label,
  value,
  color,
  animated,
}: {
  label: string;
  value: number;
  color: string;
  animated: boolean;
}) {
  return (
    <div className="space-y-1">
      <div className="flex items-center justify-between text-xs">
        <span className="text-gray-400">{label}</span>
        <span className="font-mono font-semibold" style={{ color }}>
          {value.toFixed(1)}%
        </span>
      </div>
      <div className="h-2.5 bg-gray-800/50 rounded-full overflow-hidden border border-gray-700/50">
        <div
          className="h-full rounded-full transition-all duration-[1500ms] ease-out"
          style={{
            width: animated ? `${value}%` : "0%",
            background: `linear-gradient(90deg, ${color}66, ${color})`,
            boxShadow: `0 0 8px ${color}44`,
          }}
        />
      </div>
    </div>
  );
}

// ── Main Component ─────────────────────────────────────────────────

export function VerdictDashboard({
  riskScore,
  riskLevel,
  c2paStatus,
  predictedSource,
  sourceConfidence,
  totalProcessingTimeMs,
  inspectionId,
}: VerdictDashboardProps) {
  const [animated, setAnimated] = useState(false);
  const verdict = getVerdict(riskScore, riskLevel);

  useEffect(() => {
    const timer = setTimeout(() => setAnimated(true), 100);
    return () => clearTimeout(timer);
  }, []);

  return (
    <div className={cn("rounded-2xl border p-6 md:p-8", verdict.bg, "bg-[#0c0c14]")}>
      {/* Verdict Label */}
      <div
        className={cn(
          "text-center mb-6 transition-opacity duration-700",
          animated ? "opacity-100" : "opacity-0"
        )}
      >
        <p className="text-xs uppercase tracking-[3px] text-gray-500 mb-1">Pravorijek</p>
        <h2 className="text-xl md:text-2xl font-bold tracking-wide" style={{ color: verdict.color }}>
          {verdict.label}
        </h2>
      </div>

      <div className="flex flex-col lg:flex-row items-center gap-8">
        {/* Gauge */}
        <div className="flex-shrink-0">
          <Gauge
            value={verdict.confidence}
            color={verdict.color}
            glow={verdict.glow}
            animated={animated}
          />
          {/* Processing time */}
          <p className="text-center text-xs text-gray-500 mt-1">
            Vrijeme obrade:{" "}
            <span className="text-gray-400 font-mono">
              {(totalProcessingTimeMs / 1000).toFixed(1)}s
            </span>
          </p>
        </div>

        {/* Confidence Breakdown */}
        <div className="flex-1 w-full space-y-4">
          <p className="text-xs uppercase tracking-[2px] text-gray-500 mb-3">Analiza pouzdanosti</p>

          <ConfidenceBar
            label="Autentična slika"
            value={verdict.scores.authentic}
            color="#22c55e"
            animated={animated}
          />
          <ConfidenceBar
            label="Umjetno generirana"
            value={verdict.scores.ai_generated}
            color="#a855f7"
            animated={animated}
          />
          <ConfidenceBar
            label="Digitalno izmijenjena"
            value={verdict.scores.tampered}
            color="#f97316"
            animated={animated}
          />

          {/* Badges */}
          <div className="flex flex-wrap items-center gap-2 pt-2">
            {c2paStatus === "valid" && (
              <span className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-xs font-medium bg-green-500/10 text-green-400 border border-green-500/20">
                <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M9 12.75L11.25 15 15 9.75M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                </svg>
                C2PA potpis valjan
              </span>
            )}
            {c2paStatus === "ai_generated" && (
              <span className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-xs font-medium bg-purple-500/10 text-purple-400 border border-purple-500/20">
                C2PA: AI generirano
              </span>
            )}
            {predictedSource && (
              <span className="px-2.5 py-1 rounded-full text-xs font-medium bg-gray-800/50 text-gray-400 border border-gray-700/50">
                Izvor: {predictedSource} ({sourceConfidence}%)
              </span>
            )}
            <ExportButton inspectionId={inspectionId} />
          </div>
        </div>
      </div>
    </div>
  );
}
