"use client";

import { useEffect, useState } from "react";
import { cn } from "@/lib/cn";
import { sanitizeLlmText } from "@/lib/forensicPillars";
import { decisionOutcomeLabel } from "@/lib/api";
import { ExportButton } from "./ExportButton";

interface VerdictDashboardProps {
  riskScore: number;
  riskLevel: string;
  c2paStatus: string | null;
  predictedSource: string | null;
  sourceConfidence: number;
  totalProcessingTimeMs: number;
  inspectionId: string;
  summary?: string | null;
  decisionOutcome?: string | null;
  decisionReason?: string | null;
}

// 3-class verdict from risk score
type VerdictClass = "authentic" | "ai_generated" | "tampered";

function getVerdict(riskScore: number, riskLevel: string): {
  cls: VerdictClass;
  label: string;
  confidence: number;
  scores: { authentic: number; ai_generated: number; tampered: number };
} {
  const risk = riskScore * 100;

  if (riskLevel === "Critical" || risk >= 75) {
    const conf = Math.min(99.5, 70 + risk * 0.35);
    return {
      cls: "ai_generated",
      label: "UMJETNO GENERIRANA SLIKA",
      confidence: conf,
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
    scores: {
      authentic: conf,
      ai_generated: Math.max(0.5, (100 - conf) * 0.6),
      tampered: Math.max(0.5, (100 - conf) * 0.4),
    },
  };
}

// ── Verdict Badge ────────────────────────────────────────────────

function getVerdictBadge(riskPercent: number) {
  if (riskPercent >= 75) {
    return {
      label: "KRITIČAN RIZIK: DETEKTIRANA MANIPULACIJA",
      bgClass: "bg-red-50",
      textClass: "text-red-700",
      borderClass: "border-red-200",
      icon: "warning" as const,
    };
  }
  if (riskPercent <= 20) {
    return {
      label: "SIGURNO: AUTENTIČNI MEDIJ",
      bgClass: "bg-green-50",
      textClass: "text-green-700",
      borderClass: "border-green-200",
      icon: "check" as const,
    };
  }
  return {
    label: "UMJEREN RIZIK: POTREBNA PROVJERA",
    bgClass: "bg-amber-50",
    textClass: "text-amber-700",
    borderClass: "border-amber-200",
    icon: "alert" as const,
  };
}

// ── Risk Gauge (stroke-dasharray animation) ──────────────────────

function RiskGauge({ value, animated }: { value: number; animated: boolean }) {
  const size = 220;
  const cx = size / 2;
  const cy = size / 2 + 8;
  const r = size / 2 - 20;
  const strokeWidth = 14;

  const startAngle = 180;
  const endAngle = 0;

  function polarToCartesian(angle: number) {
    const rad = (angle * Math.PI) / 180;
    return { x: cx + r * Math.cos(rad), y: cy - r * Math.sin(rad) };
  }

  const bgStart = polarToCartesian(startAngle);
  const bgEnd = polarToCartesian(endAngle);
  const bgArc = `M ${bgStart.x} ${bgStart.y} A ${r} ${r} 0 0 1 ${bgEnd.x} ${bgEnd.y}`;

  // stroke-dasharray/offset for smooth animation
  const totalArcLength = Math.PI * r;
  const fillLength = (value / 100) * totalArcLength;
  const dashOffset = animated ? totalArcLength - fillLength : totalArcLength;

  return (
    <svg width={size} height={size / 2 + 30} viewBox={`0 0 ${size} ${size / 2 + 30}`}>
      <defs>
        <linearGradient id="risk-arc-gradient" x1="0%" y1="0%" x2="100%" y2="0%">
          <stop offset="0%" stopColor="#22c55e" />
          <stop offset="35%" stopColor="#eab308" />
          <stop offset="60%" stopColor="#f97316" />
          <stop offset="100%" stopColor="#ef4444" />
        </linearGradient>
      </defs>

      {/* Background arc */}
      <path
        d={bgArc}
        fill="none"
        stroke="#e5e7eb"
        strokeWidth={strokeWidth}
        strokeLinecap="round"
      />

      {/* Fill arc — always in DOM, animated via stroke-dashoffset */}
      <path
        d={bgArc}
        fill="none"
        stroke="url(#risk-arc-gradient)"
        strokeWidth={strokeWidth}
        strokeLinecap="round"
        strokeDasharray={totalArcLength}
        strokeDashoffset={dashOffset}
        className="gauge-fill-animation"
      />

      {/* Center number */}
      <text
        x={cx}
        y={cy - 14}
        textAnchor="middle"
        fill="#0f172a"
        fontSize="42"
        fontWeight="900"
        style={{
          opacity: animated ? 1 : 0,
          transition: "opacity 0.8s ease-in 0.5s",
        }}
      >
        {animated ? value.toFixed(1) : "0.0"}%
      </text>
      <text
        x={cx}
        y={cy + 10}
        textAnchor="middle"
        fill="#94a3b8"
        fontSize="10"
        letterSpacing="3"
      >
        INDEKS RIZIKA
      </text>
    </svg>
  );
}

// ── Module Bar (thin, flat) ──────────────────────────────────────

function ModuleBar({
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
    <div className="space-y-1.5">
      <div className="flex items-center justify-between">
        <span className="text-sm text-slate-500">{label}</span>
        <span className="text-sm font-mono font-bold text-slate-900">
          {value.toFixed(1)}%
        </span>
      </div>
      <div className="h-1.5 bg-gray-100 rounded-full overflow-hidden">
        <div
          className="h-full rounded-full transition-all duration-[1200ms] ease-out"
          style={{
            width: animated ? `${value}%` : "0%",
            backgroundColor: color,
          }}
        />
      </div>
    </div>
  );
}

// ── SVG Icons ────────────────────────────────────────────────────

function CheckShieldIcon() {
  return (
    <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M9 12.75L11.25 15 15 9.75m-3-7.036A11.959 11.959 0 013.598 6 11.99 11.99 0 003 9.749c0 5.592 3.824 10.29 9 11.623 5.176-1.332 9-6.03 9-11.622 0-1.31-.21-2.571-.598-3.751h-.152c-3.196 0-6.1-1.248-8.25-3.285z" />
    </svg>
  );
}

function WarningIcon() {
  return (
    <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v3.75m-9.303 3.376c-.866 1.5.217 3.374 1.948 3.374h14.71c1.73 0 2.813-1.874 1.948-3.374L13.949 3.378c-.866-1.5-3.032-1.5-3.898 0L2.697 16.126zM12 15.75h.007v.008H12v-.008z" />
    </svg>
  );
}

// ── Decision Outcome Label ───────────────────────────────────────

const decisionStyles: Record<string, string> = {
  AutoApprove: "bg-green-50 text-green-700 border-green-200",
  HumanReview: "bg-amber-50 text-amber-700 border-amber-200",
  Escalate: "bg-red-50 text-red-700 border-red-200",
};

// ── Main Component ───────────────────────────────────────────────

export function VerdictDashboard({
  riskScore,
  riskLevel,
  c2paStatus,
  predictedSource,
  sourceConfidence,
  totalProcessingTimeMs,
  inspectionId,
  summary,
  decisionOutcome,
  decisionReason,
}: VerdictDashboardProps) {
  const [animated, setAnimated] = useState(false);
  const verdict = getVerdict(riskScore, riskLevel);
  const riskPercent = riskScore * 100;
  const badge = getVerdictBadge(riskPercent);

  useEffect(() => {
    const timer = setTimeout(() => setAnimated(true), 100);
    return () => clearTimeout(timer);
  }, []);

  return (
    <div className="bg-white shadow-sm rounded-2xl border border-gray-100 p-6 md:p-8">
      {/* Decision Outcome (if available) */}
      {decisionOutcome && (
        <div className="flex justify-center mb-4">
          <div className={cn(
            "inline-flex items-center gap-2 px-3 py-1.5 rounded-lg border text-xs font-semibold",
            decisionStyles[decisionOutcome] || "bg-gray-50 text-gray-700 border-gray-200"
          )}>
            {decisionOutcomeLabel(decisionOutcome)}
            {decisionReason && (
              <span className="font-normal opacity-75">— {decisionReason}</span>
            )}
          </div>
        </div>
      )}

      {/* Verdict Badge */}
      <div
        className={cn(
          "flex justify-center mb-6 transition-opacity duration-500",
          animated ? "opacity-100" : "opacity-0"
        )}
      >
        <div
          className={cn(
            "inline-flex items-center gap-2 px-4 py-2 rounded-full border text-sm font-semibold",
            badge.bgClass,
            badge.textClass,
            badge.borderClass
          )}
        >
          {badge.icon === "check" && <CheckShieldIcon />}
          {(badge.icon === "warning" || badge.icon === "alert") && <WarningIcon />}
          {badge.label}
        </div>
      </div>

      <div className="flex flex-col lg:flex-row items-center gap-10">
        {/* Risk Gauge */}
        <div className="flex-shrink-0">
          <RiskGauge value={riskPercent} animated={animated} />
        </div>

        {/* Module Breakdown */}
        <div className="flex-1 w-full space-y-5">
          <p className="text-xs uppercase tracking-[2px] text-slate-400 font-medium">
            Razrada rizika
          </p>

          <ModuleBar
            label="Autentična slika"
            value={verdict.scores.authentic}
            color="#22c55e"
            animated={animated}
          />
          <ModuleBar
            label="Umjetno generirana"
            value={verdict.scores.ai_generated}
            color="#a855f7"
            animated={animated}
          />
          <ModuleBar
            label="Digitalno izmijenjena"
            value={verdict.scores.tampered}
            color="#f97316"
            animated={animated}
          />

          {/* Badges */}
          <div className="flex flex-wrap items-center gap-2 pt-3 border-t border-gray-100">
            {c2paStatus === "valid" && (
              <span className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-xs font-medium bg-green-50 text-green-700 border border-green-200">
                <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M9 12.75L11.25 15 15 9.75M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                </svg>
                C2PA potpis valjan
              </span>
            )}
            {c2paStatus === "ai_generated" && (
              <span className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-xs font-medium bg-purple-50 text-purple-700 border border-purple-200">
                C2PA: AI generirano
              </span>
            )}
            {predictedSource && (
              <span className="px-2.5 py-1 rounded-full text-xs font-medium bg-gray-50 text-gray-600 border border-gray-200">
                Izvor: {predictedSource} ({sourceConfidence}%)
              </span>
            )}
            <span className="px-2.5 py-1 rounded-full text-xs font-medium bg-gray-50 text-slate-500 border border-gray-200">
              {(totalProcessingTimeMs / 1000).toFixed(1)}s
            </span>
            <ExportButton inspectionId={inspectionId} />
          </div>
        </div>
      </div>

      {/* AI Summary */}
      {summary && (
        <div className="mt-6 pt-5 border-t border-gray-100">
          <p className="text-sm text-slate-600 leading-relaxed">
            {sanitizeLlmText(summary)}
          </p>
          <p className="text-[10px] text-slate-400 mt-1.5 italic">
            Sažetak generirao jezični model
          </p>
        </div>
      )}
    </div>
  );
}
