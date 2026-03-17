"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { cn } from "@/lib/cn";

export interface ForensicStep {
  id: string;
  label: string;
  status: "pending" | "active" | "complete";
}

const DEFAULT_STEPS: ForensicStep[] = [
  { id: "metadata_analysis", label: "Metadata analiza", status: "pending" },
  { id: "modification_detection", label: "ELA detekcija modifikacija", status: "pending" },
  { id: "optical_forensics", label: "Opticka forenzika", status: "pending" },
  { id: "spectral_forensics", label: "Spektralna forenzika", status: "pending" },
  { id: "deep_modification_detection", label: "CNN duboka analiza", status: "pending" },
  { id: "semantic_forensics", label: "Semanticka analiza", status: "pending" },
  { id: "ai_generation_detection", label: "AI generiranje detekcija", status: "pending" },
  { id: "gemini", label: "Gemini kontekst analiza", status: "pending" },
  { id: "agent", label: "Agent evaluacija", status: "pending" },
  { id: "evidence", label: "Digitalni pecat", status: "pending" },
];

/**
 * Approximate durations (seconds) per step — used for timed progress simulation.
 * Group 1 (parallel on backend): metadata, ELA, optical, spectral finish fast.
 * Group 2 (sequential): CNN, semantic, AI gen are heavier.
 * Then: Gemini, Agent, Evidence.
 */
const STEP_DURATIONS: Record<string, number> = {
  metadata_analysis: 1.0,
  modification_detection: 1.2,
  optical_forensics: 1.0,
  spectral_forensics: 1.5,
  deep_modification_detection: 6,
  semantic_forensics: 4,
  ai_generation_detection: 6,
  gemini: 12,
  agent: 8,
  evidence: 2,
};

const TOTAL_ESTIMATED_DURATION = Object.values(STEP_DURATIONS).reduce((a, b) => a + b, 0);

interface ForensicProgressProps {
  steps?: ForensicStep[];
  progress: number; // 0.0 - 1.0
}

export function ForensicProgress({ steps, progress }: ForensicProgressProps) {
  const displaySteps = steps || DEFAULT_STEPS;
  const completedCount = displaySteps.filter((s) => s.status === "complete").length;
  const activeStep = displaySteps.find((s) => s.status === "active");

  return (
    <div className="space-y-4">
      {/* Overall progress bar */}
      <div className="space-y-2">
        <div className="flex items-center justify-between">
          <span className="text-sm font-medium text-foreground">
            Forenzicka analiza
          </span>
          <span className="text-xs text-muted">
            {completedCount}/{displaySteps.length} koraka
          </span>
        </div>
        <div className="h-2 bg-gray-100 rounded-full overflow-hidden">
          <div
            className="h-full bg-accent rounded-full transition-all duration-500 ease-out"
            style={{ width: `${Math.round(progress * 100)}%` }}
          />
        </div>
        {activeStep && (
          <p className="text-xs text-muted animate-pulse">
            {activeStep.label}...
          </p>
        )}
      </div>

      {/* Step list */}
      <div className="space-y-1">
        {displaySteps.map((step) => (
          <div
            key={step.id}
            className={cn(
              "flex items-center gap-2.5 py-1.5 px-2 rounded-lg text-xs transition-colors",
              step.status === "complete" && "text-emerald-700 bg-emerald-50/50",
              step.status === "active" && "text-accent font-medium bg-accent/5",
              step.status === "pending" && "text-muted"
            )}
          >
            {/* Status icon */}
            <div className="flex-shrink-0 w-4 h-4 flex items-center justify-center">
              {step.status === "complete" ? (
                <svg className="w-4 h-4 text-emerald-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M4.5 12.75l6 6 9-13.5" />
                </svg>
              ) : step.status === "active" ? (
                <div className="w-3 h-3 border-2 border-accent border-t-transparent rounded-full animate-spin" />
              ) : (
                <div className="w-2 h-2 rounded-full bg-gray-300" />
              )}
            </div>

            <span>{step.label}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Hook: useForensicProgress — timed simulation of forensic step progression
// ---------------------------------------------------------------------------

export function useForensicProgress(isActive: boolean) {
  const [steps, setSteps] = useState<ForensicStep[]>(() => createForensicSteps());
  const [progress, setProgress] = useState(0);
  const stepIndexRef = useRef(0);
  const stepElapsedRef = useRef(0);

  // Reset whenever analysis starts
  useEffect(() => {
    if (isActive) {
      const fresh = createForensicSteps();
      // Activate first step
      fresh[0].status = "active";
      setSteps(fresh);
      setProgress(0);
      stepIndexRef.current = 0;
      stepElapsedRef.current = 0;
    }
  }, [isActive]);

  // Tick every 500ms to advance simulated progress
  useEffect(() => {
    if (!isActive) return;

    const stepIds = DEFAULT_STEPS.map((s) => s.id);
    const tick = 0.5; // seconds per interval

    const interval = setInterval(() => {
      stepElapsedRef.current += tick;
      const idx = stepIndexRef.current;
      if (idx >= stepIds.length) return; // all done

      const currentId = stepIds[idx];
      const duration = STEP_DURATIONS[currentId] || 3;

      if (stepElapsedRef.current >= duration) {
        // Complete current step, activate next
        stepElapsedRef.current = 0;
        const nextIdx = idx + 1;
        stepIndexRef.current = nextIdx;

        setSteps((prev) => {
          const next = prev.map((s) => ({ ...s }));
          next[idx].status = "complete";
          if (nextIdx < next.length) {
            next[nextIdx].status = "active";
          }
          return next;
        });
      }

      // Calculate overall progress
      const completedDuration = stepIds
        .slice(0, stepIndexRef.current)
        .reduce((sum, id) => sum + (STEP_DURATIONS[id] || 3), 0);
      const currentDuration = STEP_DURATIONS[stepIds[stepIndexRef.current]] || 3;
      const withinStep = Math.min(stepElapsedRef.current / currentDuration, 0.95);
      const totalProg = (completedDuration + withinStep * currentDuration) / TOTAL_ESTIMATED_DURATION;

      // Cap at 95% — final 5% reserved for actual completion
      setProgress(Math.min(totalProg, 0.95));
    }, tick * 1000);

    return () => clearInterval(interval);
  }, [isActive]);

  /** Call when the real API result arrives — instantly completes all remaining steps. */
  const complete = useCallback(() => {
    setSteps((prev) => prev.map((s) => ({ ...s, status: "complete" as const })));
    setProgress(1);
  }, []);

  /** Reset to initial state. */
  const reset = useCallback(() => {
    setSteps(createForensicSteps());
    setProgress(0);
    stepIndexRef.current = 0;
    stepElapsedRef.current = 0;
  }, []);

  return { steps, progress, complete, reset };
}

// ---------------------------------------------------------------------------
// Pure helpers (still exported for potential SSE-based usage later)
// ---------------------------------------------------------------------------

/**
 * Create a mutable steps array for use with SSE events.
 */
export function createForensicSteps(): ForensicStep[] {
  return DEFAULT_STEPS.map((s) => ({ ...s }));
}

/**
 * Update step statuses based on a completed module name.
 */
export function markStepComplete(
  steps: ForensicStep[],
  moduleId: string
): ForensicStep[] {
  return steps.map((s) => {
    if (s.id === moduleId) {
      return { ...s, status: "complete" as const };
    }
    return s;
  });
}

/**
 * Set the next pending step to active.
 */
export function activateNextStep(steps: ForensicStep[]): ForensicStep[] {
  let foundPending = false;
  return steps.map((s) => {
    if (!foundPending && s.status === "pending") {
      foundPending = true;
      return { ...s, status: "active" as const };
    }
    return s;
  });
}
