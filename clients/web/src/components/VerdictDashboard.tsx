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
  verdictProbabilities?: Record<string, number> | null;
  fileName?: string;
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
      bgClass: "bg-red-500/10",
      textClass: "text-red-600 dark:text-red-400",
      borderClass: "border-red-500/20",
      icon: "warning" as const,
    };
  }
  if (riskPercent <= 20) {
    return {
      label: "SIGURNO: AUTENTIČNI MEDIJ",
      bgClass: "bg-green-500/10",
      textClass: "text-green-600 dark:text-green-400",
      borderClass: "border-green-500/20",
      icon: "check" as const,
    };
  }
  return {
    label: "UMJEREN RIZIK: POTREBNA PROVJERA",
    bgClass: "bg-amber-500/10",
    textClass: "text-amber-600 dark:text-amber-400",
    borderClass: "border-amber-500/20",
    icon: "alert" as const,
  };
}

// ── Risk Gauge ──────────────────────────────────────────────────

function getRiskColor(value: number): { main: string; glow: string } {
  if (value <= 15) return { main: "#10b981", glow: "#10b98130" };
  if (value <= 35) return { main: "#06b6d4", glow: "#06b6d430" };
  if (value <= 55) return { main: "#f59e0b", glow: "#f59e0b30" };
  if (value <= 75) return { main: "#f97316", glow: "#f9731630" };
  return { main: "#ef4444", glow: "#ef444440" };
}

function getRiskLabel(value: number): string {
  if (value <= 15) return "Nizak";
  if (value <= 35) return "Umjeren";
  if (value <= 55) return "Povišen";
  if (value <= 75) return "Visok";
  return "Kritičan";
}

function useCountUp(target: number, enabled: boolean, duration = 1500) {
  const [current, setCurrent] = useState(0);
  useEffect(() => {
    if (!enabled) { setCurrent(0); return; }
    const start = performance.now();
    let raf: number;
    function tick(now: number) {
      const elapsed = now - start;
      const progress = Math.min(elapsed / duration, 1);
      const eased = 1 - Math.pow(1 - progress, 4);
      setCurrent(eased * target);
      if (progress < 1) raf = requestAnimationFrame(tick);
    }
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [target, enabled, duration]);
  return current;
}

function RiskGauge({ value, animated }: { value: number; animated: boolean }) {
  const size = 192;
  const stroke = 6;
  const trackStroke = 6;
  const r = (size - stroke) / 2;
  const circumference = 2 * Math.PI * r;
  const fillOffset = animated ? circumference * (1 - value / 100) : circumference;
  const { main, glow } = getRiskColor(value);
  const label = getRiskLabel(value);
  const displayValue = useCountUp(value, animated);
  const whole = Math.floor(displayValue);
  const decimal = (displayValue % 1).toFixed(1).slice(1); // ".X"

  return (
    <div className="relative flex-shrink-0" style={{ width: size, height: size }}>
      {/* SVG rings */}
      <svg width={size} height={size} className="-rotate-90" style={{ overflow: "visible" }}>
        {/* Track */}
        <circle
          cx={size / 2} cy={size / 2} r={r}
          fill="none"
          stroke="currentColor"
          strokeWidth={trackStroke}
          className="text-border opacity-50"
        />
        {/* Progress */}
        <circle
          cx={size / 2} cy={size / 2} r={r}
          fill="none"
          stroke={main}
          strokeWidth={stroke}
          strokeLinecap="round"
          strokeDasharray={circumference}
          strokeDashoffset={fillOffset}
          style={{
            transition: animated ? "stroke-dashoffset 1.5s cubic-bezier(0.25, 0.46, 0.45, 0.94)" : "none",
            filter: animated ? `drop-shadow(0 0 8px ${glow})` : "none",
          }}
        />
      </svg>

      {/* Center */}
      <div
        className="absolute inset-0 flex flex-col items-center justify-center"
        style={{ opacity: animated ? 1 : 0, transition: "opacity 0.5s ease-out 0.3s" }}
      >
        <div className="flex items-baseline gap-0">
          <span className="text-[44px] font-heading font-extrabold tabular-nums text-foreground leading-none tracking-tight">
            {whole}
          </span>
          <span className="text-xl font-heading font-extrabold tabular-nums text-foreground/50 leading-none">
            {decimal}
          </span>
          <span className="text-lg font-bold text-foreground/30 ml-0.5">%</span>
        </div>
        <div
          className="mt-2 text-[10px] font-bold uppercase tracking-[2px]"
          style={{ color: main }}
        >
          {label}
        </div>
      </div>
    </div>
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
        <span className="text-sm text-muted">{label}</span>
        <span className="text-sm font-mono font-bold text-foreground">
          {value.toFixed(1)}%
        </span>
      </div>
      <div className="h-1.5 bg-card-hover rounded-full overflow-hidden">
        <div
          className="h-full rounded-full transition-all duration-[600ms] ease-out"
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
  AutoApprove: "bg-green-500/10 text-green-600 dark:text-green-400 border-green-500/20",
  HumanReview: "bg-amber-500/10 text-amber-600 dark:text-amber-400 border-amber-500/20",
  Escalate: "bg-red-500/10 text-red-600 dark:text-red-400 border-red-500/20",
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
  verdictProbabilities,
  fileName,
}: VerdictDashboardProps) {
  const [animated, setAnimated] = useState(false);
  const isDocument = fileName ? ["pdf", "docx", "xlsx", "doc", "xls"].includes(fileName.split(".").pop()?.toLowerCase() ?? "") : false;
  const contentWord = isDocument ? "DOKUMENT" : "SLIKA";

  // Use REAL meta-learner probabilities if available, else heuristic fallback
  const verdict = verdictProbabilities
    ? (() => {
        const a = (verdictProbabilities.authentic ?? 0) * 100;
        const ai = (verdictProbabilities.ai_generated ?? 0) * 100;
        const t = (verdictProbabilities.tampered ?? 0) * 100;
        const maxVal = Math.max(a, ai, t);
        const cls: VerdictClass = maxVal === ai ? "ai_generated" : maxVal === t ? "tampered" : "authentic";
        const labels: Record<VerdictClass, string> = {
          authentic: isDocument ? "AUTENTIČAN DOKUMENT" : "AUTENTIČNA FOTOGRAFIJA",
          ai_generated: `UMJETNO GENERIRANA ${contentWord}`,
          tampered: `DIGITALNO IZMIJENJENA ${contentWord}`,
        };
        return {
          cls,
          label: labels[cls],
          confidence: maxVal,
          scores: { authentic: a, ai_generated: ai, tampered: t },
        };
      })()
    : getVerdict(riskScore, riskLevel);

  // Override labels for documents
  if (isDocument && !verdictProbabilities) {
    if (verdict.cls === "authentic") verdict.label = "AUTENTIČAN DOKUMENT";
    else if (verdict.cls === "ai_generated") verdict.label = `UMJETNO GENERIRAN ${contentWord}`;
    else if (verdict.cls === "tampered") verdict.label = `DIGITALNO IZMIJENJEN ${contentWord}`;
  }

  const riskPercent = riskScore * 100;
  const badge = getVerdictBadge(riskPercent);

  useEffect(() => {
    const timer = setTimeout(() => setAnimated(true), 30);
    return () => clearTimeout(timer);
  }, []);

  return (
    <div className="bg-background shadow-sm rounded-2xl border border-border p-6 md:p-8">
      {/* Decision Outcome (if available) */}
      {decisionOutcome && (
        <div className="flex justify-center mb-4">
          <div className={cn(
            "inline-flex items-center gap-2 px-3 py-1.5 rounded-lg border text-xs font-semibold",
            decisionStyles[decisionOutcome] || "bg-card text-foreground border-border"
          )}>
            {decisionOutcomeLabel(decisionOutcome)}
            {decisionReason && (
              <span className="font-normal opacity-75">— {decisionReason}</span>
            )}
          </div>
        </div>
      )}

      {/* Verdict Badge — hidden when decision outcome already shown (avoids contradictions) */}
      {!decisionOutcome && <div
        className={cn(
          "flex justify-center mb-6 transition-opacity duration-200",
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
      </div>}

      <div className="flex flex-col lg:flex-row items-center gap-10">
        {/* Risk Gauge */}
        <div className="flex-shrink-0">
          <RiskGauge value={riskPercent} animated={animated} />
        </div>

        {/* Module Breakdown */}
        <div className="flex-1 w-full space-y-5">
          <p className="text-xs uppercase tracking-[2px] text-muted-light font-medium">
            Razrada rizika
          </p>

          <ModuleBar
            label={isDocument ? "Autentičan dokument" : "Autentična slika"}
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
          <div className="flex flex-wrap items-center gap-2 pt-3 border-t border-border">
            {c2paStatus === "valid" && (
              <span className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-xs font-medium bg-green-500/10 text-green-600 dark:text-green-400 border border-green-500/20">
                <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M9 12.75L11.25 15 15 9.75M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                </svg>
                C2PA potpis valjan
              </span>
            )}
            {c2paStatus === "ai_generated" && (
              <span className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-xs font-medium bg-purple-500/10 text-purple-600 dark:text-purple-400 border border-purple-500/20">
                C2PA: AI generirano
              </span>
            )}
            {predictedSource && (
              <span className="px-2.5 py-1 rounded-full text-xs font-medium bg-card text-muted border border-border">
                Izvor: {predictedSource} ({sourceConfidence}%)
              </span>
            )}
            <span className="px-2.5 py-1 rounded-full text-xs font-medium bg-card text-muted border border-border">
              {(totalProcessingTimeMs / 1000).toFixed(1)}s
            </span>
            <ExportButton inspectionId={inspectionId} />
          </div>
        </div>
      </div>

      {/* AI Summary */}
      {summary && (
        <div className="mt-6 pt-5 border-t border-border">
          <p className="text-sm text-muted leading-relaxed">
            {sanitizeLlmText(summary)}
          </p>
          <p className="text-[10px] text-muted-light mt-1.5 italic">
            Sažetak generirao jezični model
          </p>
        </div>
      )}
    </div>
  );
}
