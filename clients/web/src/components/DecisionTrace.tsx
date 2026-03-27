"use client";

import { useState } from "react";
import type { DecisionTraceEntry } from "@/lib/api";
import { cn } from "@/lib/cn";

interface DecisionTraceProps {
  traces: DecisionTraceEntry[];
}

export function DecisionTrace({ traces }: DecisionTraceProps) {
  const [expanded, setExpanded] = useState(false);

  if (traces.length === 0) return null;

  const triggeredCount = traces.filter((t) => t.triggered).length;

  return (
    <div className="bg-card border border-border rounded-xl overflow-hidden">
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full flex items-center justify-between px-4 py-3 text-left hover:bg-card-hover transition-colors"
      >
        <div className="flex items-center gap-2">
          <span className="text-sm font-medium">Trag odluke</span>
          <span className="text-xs text-muted">
            ({triggeredCount}/{traces.length} pravila aktivirano)
          </span>
        </div>
        <svg
          className={cn("w-4 h-4 text-muted transition-transform", expanded && "rotate-180")}
          fill="none"
          viewBox="0 0 24 24"
          stroke="currentColor"
          strokeWidth={1.5}
        >
          <path strokeLinecap="round" strokeLinejoin="round" d="M19.5 8.25l-7.5 7.5-7.5-7.5" />
        </svg>
      </button>

      {expanded && (
        <div className="px-4 pb-4 space-y-2">
          {traces
            .sort((a, b) => a.evaluationOrder - b.evaluationOrder)
            .map((trace, i) => (
              <div
                key={i}
                className={cn(
                  "flex items-start gap-3 px-3 py-2.5 rounded-lg text-sm",
                  trace.triggered
                    ? "bg-red-50 border border-red-100"
                    : "bg-card"
                )}
              >
                <div className={cn(
                  "w-5 h-5 rounded-full flex items-center justify-center flex-shrink-0 mt-0.5",
                  trace.triggered ? "bg-red-100" : "bg-green-100"
                )}>
                  {trace.triggered ? (
                    <svg className="w-3 h-3 text-red-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={3}>
                      <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v3.75m9-.75a9 9 0 11-18 0 9 9 0 0118 0zm-9 3.75h.008v.008H12v-.008z" />
                    </svg>
                  ) : (
                    <svg className="w-3 h-3 text-green-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={3}>
                      <path strokeLinecap="round" strokeLinejoin="round" d="M4.5 12.75l6 6 9-13.5" />
                    </svg>
                  )}
                </div>
                <div className="min-w-0 flex-1">
                  <div className="flex items-center justify-between gap-2">
                    <span className={cn("font-medium", trace.triggered ? "text-red-700" : "text-muted")}>
                      {trace.ruleName}
                    </span>
                    <span className={cn(
                      "text-xs px-2 py-0.5 rounded-full",
                      trace.triggered ? "bg-red-100 text-red-600" : "text-muted"
                    )}>
                      {trace.actualValue}
                    </span>
                  </div>
                  <p className="text-xs text-muted mt-0.5">{trace.ruleDescription}</p>
                  {trace.thresholdValue && (
                    <p className="text-[10px] text-muted mt-0.5">Prag: {trace.thresholdValue}</p>
                  )}
                </div>
              </div>
            ))}
        </div>
      )}
    </div>
  );
}
