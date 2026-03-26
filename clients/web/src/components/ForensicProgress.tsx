"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { cn } from "@/lib/cn";

export interface ForensicStep {
  id: string;
  label: string;
  status: "pending" | "active" | "complete";
}

const IMAGE_STEPS: ForensicStep[] = [
  // All forensic modules run in parallel (~15s total wall clock)
  { id: "metadata_analysis", label: "Metadata analiza", status: "pending" },
  { id: "modification_detection", label: "ELA detekcija modifikacija", status: "pending" },
  { id: "safe_ai_detection", label: "SAFE AI detekcija", status: "pending" },
  { id: "dinov2_ai_detection", label: "DINOv2 AI detekcija", status: "pending" },
  { id: "community_forensics_detection", label: "Community Forensics", status: "pending" },
  { id: "efficientnet_ai_detection", label: "EfficientNet AI detekcija", status: "pending" },
  { id: "clip_ai_detection", label: "CLIP AI detekcija", status: "pending" },
  { id: "mesorch_detection", label: "Mesorch detekcija manipulacija", status: "pending" },
  // Post-processing
  { id: "evidence", label: "Digitalni pecat", status: "pending" },
];

const DOCUMENT_STEPS: ForensicStep[] = [
  { id: "document_forensics", label: "Analiza strukture dokumenta", status: "pending" },
  { id: "text_ai_detection", label: "Detekcija AI teksta", status: "pending" },
  { id: "content_validation", label: "Validacija sadrzaja (OIB/IBAN)", status: "pending" },
  { id: "embedded_images", label: "Forenzika ugradenih slika", status: "pending" },
  { id: "evidence", label: "Digitalni pecat", status: "pending" },
];

/** Determine steps based on filename extension. */
function getStepsForFile(filename?: string): ForensicStep[] {
  if (!filename) return IMAGE_STEPS;
  const ext = filename.toLowerCase().split(".").pop() || "";
  if (["pdf", "docx", "xlsx", "doc", "xls"].includes(ext)) {
    return DOCUMENT_STEPS;
  }
  return IMAGE_STEPS;
}

const DEFAULT_STEPS = IMAGE_STEPS;

/**
 * Durations tuned for parallel backend execution.
 * Image modules run simultaneously (~15s wall clock).
 * Document modules run in parallel (~3s).
 */
const STEP_DURATIONS: Record<string, number> = {
  // Image modules (parallel, ~15s total)
  metadata_analysis: 1,
  modification_detection: 2,
  safe_ai_detection: 2,
  dinov2_ai_detection: 2,
  community_forensics_detection: 2,
  efficientnet_ai_detection: 2,
  clip_ai_detection: 2,
  mesorch_detection: 2,
  // Document modules (parallel, ~3s total)
  document_forensics: 2,
  text_ai_detection: 2,
  content_validation: 2,
  embedded_images: 3,
  // Post-processing
  evidence: 5,
};

/** The last step never auto-completes — it stays spinning until real API returns. */
const LAST_STEP_INDEX = DEFAULT_STEPS.length - 1;
const TOTAL_ESTIMATED_DURATION = Object.values(STEP_DURATIONS).reduce((a, b) => a + b, 0);

interface ForensicProgressProps {
  steps?: ForensicStep[];
  progress: number; // 0.0 - 1.0
}

export function ForensicProgress({ steps, progress }: ForensicProgressProps) {
  const displaySteps = steps || DEFAULT_STEPS;
  const completedCount = displaySteps.filter((s) => s.status === "complete").length;
  const activeStep = displaySteps.find((s) => s.status === "active");
  const allComplete = completedCount === displaySteps.length;
  const waitingForServer = activeStep?.id === DEFAULT_STEPS[LAST_STEP_INDEX].id
    && completedCount === displaySteps.length - 1;

  return (
    <div className="space-y-4">
      {/* Overall progress bar */}
      <div className="space-y-2">
        <div className="flex items-center justify-between">
          <span className="text-sm font-medium text-foreground">
            Forenzicka analiza
          </span>
          <span className="text-xs text-muted">
            {allComplete ? (
              <span className="text-emerald-600 font-medium">Zavrseno ✓</span>
            ) : (
              `${completedCount}/${displaySteps.length} koraka`
            )}
          </span>
        </div>
        <div className="h-2 bg-gray-100 rounded-full overflow-hidden">
          <div
            className={cn(
              "h-full rounded-full transition-all duration-500 ease-out",
              allComplete ? "bg-emerald-500" : "bg-accent"
            )}
            style={{ width: `${Math.round(progress * 100)}%` }}
          />
        </div>
        {waitingForServer ? (
          <p className="text-xs text-muted animate-pulse">
            Zavrsavanje analize — cekanje na server...
          </p>
        ) : activeStep && !allComplete ? (
          <p className="text-xs text-muted animate-pulse">
            {activeStep.label}...
          </p>
        ) : null}
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

export function useForensicProgress(isActive: boolean, filename?: string) {
  const stepsTemplate = getStepsForFile(filename);
  const [steps, setSteps] = useState<ForensicStep[]>(() => createForensicSteps(filename));
  const [progress, setProgress] = useState(0);
  const stepIndexRef = useRef(0);
  const stepElapsedRef = useRef(0);

  // Reset whenever analysis starts
  useEffect(() => {
    if (isActive) {
      const fresh = createForensicSteps(filename);
      // Activate first step
      fresh[0].status = "active";
      setSteps(fresh);
      setProgress(0);
      stepIndexRef.current = 0;
      stepElapsedRef.current = 0;
    }
  }, [isActive, filename]);

  // Tick every 500ms to advance simulated progress
  useEffect(() => {
    if (!isActive) return;

    const stepIds = stepsTemplate.map((s) => s.id);
    const tick = 0.5; // seconds per interval

    const interval = setInterval(() => {
      stepElapsedRef.current += tick;
      const idx = stepIndexRef.current;

      const lastStepIdx = stepIds.length - 1;

      // Already past all steps (complete() was called) — nothing to do
      if (idx > lastStepIdx) return;

      const currentId = stepIds[idx];
      const duration = STEP_DURATIONS[currentId] || 3;

      // Last step: NEVER auto-complete — keep it spinning until complete() is called.
      // Slowly creep progress from ~90% toward 98% using asymptotic curve.
      if (idx === lastStepIdx) {
        const extraTime = stepElapsedRef.current;
        // Asymptotic creep: 0.90 + 0.08 * (1 - e^(-t/40)) → approaches 0.98
        const creep = 0.90 + 0.08 * (1 - Math.exp(-extraTime / 40));
        setProgress(Math.min(creep, 0.98));
        return;
      }

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

      // Calculate overall progress (up to ~90% for the 12 auto-advancing steps)
      const completedDuration = stepIds
        .slice(0, stepIndexRef.current)
        .reduce((sum, id) => sum + (STEP_DURATIONS[id] || 3), 0);
      const currentDuration = STEP_DURATIONS[stepIds[stepIndexRef.current]] || 3;
      const withinStep = Math.min(stepElapsedRef.current / currentDuration, 0.95);
      const totalProg = (completedDuration + withinStep * currentDuration) / TOTAL_ESTIMATED_DURATION;

      // Cap at 90% — last 10% is for the final step which stays spinning
      setProgress(Math.min(totalProg, 0.90));
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
 * Create a mutable steps array based on file type.
 */
export function createForensicSteps(filename?: string): ForensicStep[] {
  return getStepsForFile(filename).map((s) => ({ ...s }));
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
