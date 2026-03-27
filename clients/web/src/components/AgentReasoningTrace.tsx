"use client";

import { useState } from "react";
import { type AgentDecision } from "@/lib/api";
import { cn } from "@/lib/cn";

interface AgentReasoningTraceProps {
  decision: AgentDecision;
  fallbackUsed: boolean;
  processingTimeMs: number;
  defaultExpanded?: boolean;
}

export function AgentReasoningTrace({
  decision,
  fallbackUsed,
  processingTimeMs,
  defaultExpanded,
}: AgentReasoningTraceProps) {
  const [expanded, setExpanded] = useState(defaultExpanded ?? false);

  const confidencePct = Math.round(decision.confidence * 100);
  const outcomeColor =
    decision.outcome === "AutoApprove"
      ? "text-green-600"
      : decision.outcome === "Escalate"
        ? "text-red-600"
        : "text-amber-600";
  const outcomeBg =
    decision.outcome === "AutoApprove"
      ? "bg-green-500/10 border-green-500/20"
      : decision.outcome === "Escalate"
        ? "bg-red-500/10 border-red-500/20"
        : "bg-amber-500/10 border-amber-500/20";
  const outcomeLabel =
    decision.outcome === "AutoApprove"
      ? "Automatski odobreno"
      : decision.outcome === "Escalate"
        ? "Eskalirano"
        : "Potreban pregled";

  return (
    <div className="bg-card border border-border rounded-xl overflow-hidden">
      {/* Header */}
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full flex items-center justify-between p-4 hover:bg-card-hover transition-colors"
      >
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 rounded-lg bg-violet-500/10 flex items-center justify-center">
            <svg
              className="w-4 h-4 text-violet-600"
              fill="none"
              viewBox="0 0 24 24"
              stroke="currentColor"
              strokeWidth={1.5}
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                d="M9.813 15.904L9 18.75l-.813-2.846a4.5 4.5 0 00-3.09-3.09L2.25 12l2.846-.813a4.5 4.5 0 003.09-3.09L9 5.25l.813 2.846a4.5 4.5 0 003.09 3.09L15.75 12l-2.846.813a4.5 4.5 0 00-3.09 3.09zM18.259 8.715L18 9.75l-.259-1.035a3.375 3.375 0 00-2.455-2.456L14.25 6l1.036-.259a3.375 3.375 0 002.455-2.456L18 2.25l.259 1.035a3.375 3.375 0 002.455 2.456L21.75 6l-1.036.259a3.375 3.375 0 00-2.455 2.456z"
              />
            </svg>
          </div>
          <div className="text-left">
            <div className="text-sm font-medium">AI Agent procjena</div>
            <div className="flex items-center gap-2 text-xs text-muted">
              <span className={outcomeColor}>{outcomeLabel}</span>
              <span>·</span>
              <span>Pouzdanost: {confidencePct}%</span>
              <span>·</span>
              <span>{(processingTimeMs / 1000).toFixed(1)}s</span>
              {fallbackUsed && (
                <>
                  <span>·</span>
                  <span className="text-amber-600">Zamjenski sustav</span>
                </>
              )}
            </div>
          </div>
        </div>
        <svg
          className={cn(
            "w-5 h-5 text-muted transition-transform",
            expanded && "rotate-180"
          )}
          fill="none"
          viewBox="0 0 24 24"
          stroke="currentColor"
          strokeWidth={1.5}
        >
          <path
            strokeLinecap="round"
            strokeLinejoin="round"
            d="M19.5 8.25l-7.5 7.5-7.5-7.5"
          />
        </svg>
      </button>

      {expanded && (
        <div className="border-t border-border p-4 space-y-4">
          {/* Fallback warning */}
          {fallbackUsed && (
            <div className="bg-amber-500/10 border border-amber-500/20 rounded-lg p-3 text-sm text-amber-600 dark:text-amber-400">
              AI agent nije mogao donijeti odluku. Korišten je zamjenski sustav
              pravila.
            </div>
          )}

          {/* Summary + STP badge */}
          <div className={cn("rounded-lg border p-3", outcomeBg)}>
            <div className="flex items-start justify-between gap-3">
              <p className="text-sm">{decision.summaryHr}</p>
              {decision.stpEligible && (
                <span className="flex-shrink-0 px-2 py-0.5 rounded-full bg-green-500/15 text-green-600 dark:text-green-400 text-[10px] font-semibold">
                  STP
                </span>
              )}
            </div>
          </div>

          {/* Weather verification */}
          {decision.weatherVerification?.queried && (
            <div className="space-y-1.5">
              <h4 className="text-xs font-semibold text-muted uppercase tracking-wider">
                Vremenska provjera
              </h4>
              <div
                className={cn(
                  "rounded-lg border p-3 text-sm",
                  decision.weatherVerification.corroboratesClaim === false
                    ? "bg-red-500/10 border-red-500/20"
                    : decision.weatherVerification.corroboratesClaim === true
                      ? "bg-green-500/10 border-green-500/20"
                      : "bg-card border-border"
                )}
              >
                <div className="flex items-center gap-4 text-xs mb-1.5">
                  <span>
                    Padaline:{" "}
                    {decision.weatherVerification.hadPrecipitation
                      ? "Da"
                      : "Ne"}{" "}
                    ({decision.weatherVerification.precipitationMm} mm)
                  </span>
                  <span>
                    Tuča:{" "}
                    {decision.weatherVerification.hadHail ? (
                      <span className="text-red-600 font-medium">Da</span>
                    ) : (
                      "Ne"
                    )}
                  </span>
                  {decision.weatherVerification.weatherDescription && (
                    <span>
                      Vrijeme: {decision.weatherVerification.weatherDescription}
                    </span>
                  )}
                </div>
                {decision.weatherVerification.corroboratesClaim === false &&
                  decision.weatherVerification.discrepancyNote && (
                    <p className="text-xs text-red-600 dark:text-red-400">
                      {decision.weatherVerification.discrepancyNote}
                    </p>
                  )}
                {decision.weatherVerification.corroboratesClaim === true && (
                  <p className="text-xs text-green-600 dark:text-green-400">
                    Vremenski uvjeti potkrjepljuju prijavljenu tvrdnju.
                  </p>
                )}
              </div>
            </div>
          )}

          {/* Reasoning steps */}
          {decision.reasoningSteps.length > 0 && (
            <div className="space-y-1.5">
              <h4 className="text-xs font-semibold text-muted uppercase tracking-wider">
                Koraci zaključivanja
              </h4>
              <div className="space-y-2">
                {decision.reasoningSteps.map((step) => (
                  <div
                    key={step.step}
                    className="flex gap-3 text-sm"
                  >
                    <div className="flex-shrink-0 w-6 h-6 rounded-full bg-violet-500/15 text-violet-700 dark:text-violet-400 flex items-center justify-center text-xs font-semibold">
                      {step.step}
                    </div>
                    <div className="min-w-0">
                      <div className="font-medium text-xs text-violet-700 dark:text-violet-400 mb-0.5">
                        {step.category}
                      </div>
                      <div className="text-xs text-foreground">
                        {step.observation}
                      </div>
                      {step.assessment && (
                        <div className="text-xs text-muted mt-0.5">
                          {step.assessment}
                        </div>
                      )}
                      {step.impact && (
                        <div className="text-xs text-muted italic mt-0.5">
                          Utjecaj: {step.impact}
                        </div>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Fraud indicators */}
          {decision.fraudIndicators.length > 0 && (
            <div className="space-y-1.5">
              <h4 className="text-xs font-semibold text-red-600 uppercase tracking-wider">
                Indikatori prijevare
              </h4>
              <ul className="space-y-1">
                {decision.fraudIndicators.map((indicator, i) => (
                  <li
                    key={i}
                    className="flex items-start gap-2 text-xs text-red-600 dark:text-red-400 bg-red-500/10 rounded-lg px-3 py-1.5"
                  >
                    <svg
                      className="w-3.5 h-3.5 mt-0.5 flex-shrink-0"
                      fill="none"
                      viewBox="0 0 24 24"
                      stroke="currentColor"
                      strokeWidth={2}
                    >
                      <path
                        strokeLinecap="round"
                        strokeLinejoin="round"
                        d="M12 9v3.75m-9.303 3.376c-.866 1.5.217 3.374 1.948 3.374h14.71c1.73 0 2.813-1.874 1.948-3.374L13.949 3.378c-.866-1.5-3.032-1.5-3.898 0L2.697 16.126zM12 15.75h.007v.008H12v-.008z"
                      />
                    </svg>
                    {indicator}
                  </li>
                ))}
              </ul>
            </div>
          )}

          {/* STP blockers */}
          {decision.stpBlockers.length > 0 && (
            <div className="space-y-1.5">
              <h4 className="text-xs font-semibold text-amber-600 uppercase tracking-wider">
                Razlozi za ručni pregled
              </h4>
              <ul className="space-y-1">
                {decision.stpBlockers.map((blocker, i) => (
                  <li
                    key={i}
                    className="text-xs text-amber-600 dark:text-amber-400 bg-amber-500/10 rounded-lg px-3 py-1.5"
                  >
                    {blocker}
                  </li>
                ))}
              </ul>
            </div>
          )}

          {/* Recommended actions */}
          {decision.recommendedActions.length > 0 && (
            <div className="space-y-1.5">
              <h4 className="text-xs font-semibold text-muted uppercase tracking-wider">
                Preporucene radnje
              </h4>
              <ul className="space-y-1">
                {decision.recommendedActions.map((action, i) => (
                  <li
                    key={i}
                    className="flex items-start gap-2 text-xs text-blue-600 dark:text-blue-400 bg-blue-500/10 rounded-lg px-3 py-1.5"
                  >
                    <svg
                      className="w-3.5 h-3.5 mt-0.5 flex-shrink-0"
                      fill="none"
                      viewBox="0 0 24 24"
                      stroke="currentColor"
                      strokeWidth={2}
                    >
                      <path
                        strokeLinecap="round"
                        strokeLinejoin="round"
                        d="M13.5 4.5L21 12m0 0l-7.5 7.5M21 12H3"
                      />
                    </svg>
                    {action}
                  </li>
                ))}
              </ul>
            </div>
          )}

          {/* Model info */}
          {decision.modelUsed && (
            <div className="text-[10px] text-muted pt-1 border-t border-border">
              Model: {decision.modelUsed} · Vrijeme obrade:{" "}
              {(decision.processingTimeMs / 1000).toFixed(1)}s
            </div>
          )}
        </div>
      )}
    </div>
  );
}
