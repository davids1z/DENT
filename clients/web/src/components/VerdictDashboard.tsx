"use client";

import { useEffect, useState, useRef } from "react";
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
  // Balanced palette — visible on both light/dark, not neon
  if (value <= 15) return { main: "#34D399", glow: "#34D39925" }; // emerald
  if (value <= 35) return { main: "#2DD4BF", glow: "#2DD4BF25" }; // teal
  if (value <= 55) return { main: "#FBBF24", glow: "#FBBF2425" }; // amber
  if (value <= 75) return { main: "#F97316", glow: "#F9731625" }; // orange
  return { main: "#EF4444", glow: "#EF444430" };                  // red
}

function getRiskLabel(value: number): string {
  if (value <= 15) return "Nizak";
  if (value <= 35) return "Umjeren";
  if (value <= 55) return "Povišen";
  if (value <= 75) return "Visok";
  return "Kritičan";
}

function useCountUp(target: number, enabled: boolean, duration = 800) {
  const [current, setCurrent] = useState(0);
  const fromRef = useRef(0);
  useEffect(() => {
    if (!enabled) { setCurrent(0); fromRef.current = 0; return; }
    const from = fromRef.current;
    fromRef.current = target;
    // First animation (from 0): slower entrance
    const dur = from === 0 ? 1500 : duration;
    const start = performance.now();
    let raf: number;
    function tick(now: number) {
      const elapsed = now - start;
      const progress = Math.min(elapsed / dur, 1);
      const eased = 1 - Math.pow(1 - progress, 3);
      setCurrent(from + (target - from) * eased);
      if (progress < 1) raf = requestAnimationFrame(tick);
    }
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [target, enabled, duration]);
  return current;
}

function RiskGauge({ value, animated, size = 192 }: { value: number; animated: boolean; size?: number }) {
  const stroke = 6;
  const trackStroke = 6;
  const r = (size - stroke) / 2;
  const circumference = 2 * Math.PI * r;
  const displayValue = useCountUp(value, animated);
  const fillOffset = circumference * (1 - displayValue / 100);
  const { main, glow } = getRiskColor(value);
  const label = getRiskLabel(value);
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
          <span className="text-[36px] sm:text-[44px] font-heading font-extrabold tabular-nums text-foreground leading-none tracking-tight">
            {whole}
          </span>
          <span className="text-lg sm:text-xl font-heading font-extrabold tabular-nums text-foreground/50 leading-none">
            {decimal}
          </span>
          <span className="text-base sm:text-lg font-bold text-foreground/30 ml-0.5">%</span>
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
  const display = useCountUp(value, animated);
  const dominant = value >= 30;
  return (
    <div className="space-y-1.5">
      <div className="flex items-center justify-between">
        <span className={cn("text-sm", dominant ? "text-foreground font-medium" : "text-muted")}>{label}</span>
        <span className={cn("text-sm font-mono tabular-nums", dominant ? "font-bold text-foreground" : "text-muted")}>
          {display.toFixed(1)}%
        </span>
      </div>
      <div className="h-1.5 bg-border/40 rounded-full overflow-hidden">
        <div
          className="h-full rounded-full"
          style={{ width: `${display}%`, backgroundColor: dominant ? color : "var(--color-muted)", opacity: dominant ? 1 : 0.3 }}
        />
      </div>
    </div>
  );
}

// ── Decision Badge (inline styles, immune to purge) ──────────────

function DecisionBadge({ outcome, reason }: { outcome: string; reason?: string | null }) {
  const [isDark, setIsDark] = useState(false);
  useEffect(() => {
    setIsDark(document.documentElement.classList.contains("dark"));
    const observer = new MutationObserver(() => {
      setIsDark(document.documentElement.classList.contains("dark"));
    });
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ["class"] });
    return () => observer.disconnect();
  }, []);

  const styles = decisionInlineStyles[outcome];
  if (!styles) return null;
  const s = isDark ? styles.dark : styles.light;

  return (
    <div className="flex justify-center mb-8">
      <div
        className="inline-flex items-center gap-2 px-4 py-2 rounded-lg border text-xs font-semibold text-center max-w-full"
        style={s}
      >
        <span className="flex-shrink-0">{decisionOutcomeLabel(outcome)}</span>
        {reason && (
          <span className="font-normal" style={{ opacity: 0.8 }}>— {reason}</span>
        )}
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

// Inline styles per outcome — immune to Tailwind purge
const decisionInlineStyles: Record<string, { light: React.CSSProperties; dark: React.CSSProperties }> = {
  AutoApprove: {
    light: { backgroundColor: "#D1FAE5", color: "#064E3B", borderColor: "#34D399" },
    dark: { backgroundColor: "rgba(52,211,153,0.15)", color: "#6EE7B7", borderColor: "rgba(52,211,153,0.3)" },
  },
  HumanReview: {
    light: { backgroundColor: "#FDE68A", color: "#78350F", borderColor: "#D97706" },
    dark: { backgroundColor: "rgba(245,158,11,0.2)", color: "#FCD34D", borderColor: "rgba(245,158,11,0.4)" },
  },
  Escalate: {
    light: { backgroundColor: "#FECACA", color: "#7F1D1D", borderColor: "#EF4444" },
    dark: { backgroundColor: "rgba(239,68,68,0.2)", color: "#FCA5A5", borderColor: "rgba(239,68,68,0.4)" },
  },
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

  // Use REAL meta-learner probabilities if available; no heuristic fallback.
  // When the meta-learner is disabled, showing fabricated probability bars
  // gives false precision and misleads users.
  const hasRealProbabilities = !!verdictProbabilities;
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
    : null;

  const riskPercent = riskScore * 100;
  const badge = getVerdictBadge(riskPercent);

  // Animate on first mount only — useCountUp handles transitions between values
  useEffect(() => {
    const timer = setTimeout(() => setAnimated(true), 30);
    return () => clearTimeout(timer);
  }, []);

  return (
    <div className="bg-background shadow-sm rounded-2xl border border-border p-4 sm:p-6 md:p-8">
      {/* Decision Outcome (if available) */}
      {decisionOutcome && decisionInlineStyles[decisionOutcome] && (
        <DecisionBadge outcome={decisionOutcome} reason={decisionReason} />
      )}

      {/* Verdict Badge — hidden when decision outcome already shown (avoids contradictions) */}
      {!decisionOutcome && <div
        className={cn(
          "flex justify-center mb-4 sm:mb-6 transition-opacity duration-200",
          animated ? "opacity-100" : "opacity-0"
        )}
      >
        <div
          className={cn(
            "inline-flex items-center gap-2 px-3 sm:px-4 py-1.5 sm:py-2 rounded-full border text-xs sm:text-sm font-semibold text-center max-w-full",
            badge.bgClass,
            badge.textClass,
            badge.borderClass
          )}
        >
          <span className="flex-shrink-0">{badge.icon === "check" && <CheckShieldIcon />}{(badge.icon === "warning" || badge.icon === "alert") && <WarningIcon />}</span>
          <span className="break-words">{badge.label}</span>
        </div>
      </div>}

      <div className="flex flex-col lg:flex-row items-center gap-6 sm:gap-10">
        {/* Risk Gauge */}
        <div className="flex-shrink-0">
          <div className="sm:hidden"><RiskGauge value={riskPercent} animated={animated} size={160} /></div>
          <div className="hidden sm:block"><RiskGauge value={riskPercent} animated={animated} size={192} /></div>
        </div>

        {/* Module Breakdown — only show when real probabilities are available */}
        <div className="flex-1 w-full space-y-5">
          {hasRealProbabilities && verdict && (
            <>
              <p className="text-xs uppercase tracking-[2px] text-muted-light font-medium">
                Razrada rizika
              </p>

              <ModuleBar
                label={isDocument ? "Autentičan dokument" : "Autentična slika"}
                value={verdict.scores.authentic}
                color="#34D399"
                animated={animated}
              />
              <ModuleBar
                label="Umjetno generirana"
                value={verdict.scores.ai_generated}
                color="#818CF8"
                animated={animated}
              />
              <ModuleBar
                label="Digitalno izmijenjena"
                value={verdict.scores.tampered}
                color="#F97316"
                animated={animated}
              />
            </>
          )}

          {/* Badges */}
          <div className="flex flex-wrap items-center gap-2 pt-3 border-t border-border">
            {c2paStatus === "valid" && (
              <span className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-xs font-medium bg-card text-muted border border-border">
                <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M9 12.75L11.25 15 15 9.75M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                </svg>
                C2PA potpis valjan
              </span>
            )}
            {c2paStatus === "ai_generated" && (
              <span className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-xs font-medium bg-card text-muted border border-border">
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
            {/* ExportButton removed — report endpoint not implemented yet */}
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
