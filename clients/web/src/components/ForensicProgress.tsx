"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { cn } from "@/lib/cn";

export interface ForensicStep {
  id: string;
  label: string;
  status: "pending" | "active" | "complete";
}

// ---------------------------------------------------------------------------
// Step templates for different file types
// All forensic modules run in parallel (~15s total wall clock)
// ---------------------------------------------------------------------------

export const IMAGE_STEPS: ForensicStep[] = [
  { id: "metadata_analysis", label: "Metadata analiza", status: "pending" },
  { id: "modification_detection", label: "ELA detekcija modifikacija", status: "pending" },
  { id: "safe_ai_detection", label: "SAFE AI detekcija", status: "pending" },
  { id: "dinov2_ai_detection", label: "DINOv2 AI detekcija", status: "pending" },
  { id: "community_forensics_detection", label: "Community Forensics", status: "pending" },
  { id: "efficientnet_ai_detection", label: "EfficientNet AI detekcija", status: "pending" },
  { id: "clip_ai_detection", label: "CLIP AI detekcija", status: "pending" },
  { id: "mesorch_detection", label: "Mesorch detekcija manipulacija", status: "pending" },
];

export const DOCUMENT_STEPS: ForensicStep[] = [
  { id: "document_forensics", label: "Analiza strukture dokumenta", status: "pending" },
  { id: "text_ai_detection", label: "Detekcija AI teksta", status: "pending" },
  { id: "content_validation", label: "Validacija sadrzaja (OIB/IBAN)", status: "pending" },
  { id: "embedded_images", label: "Forenzika ugradenih slika", status: "pending" },
];

const SHARED_STEPS: ForensicStep[] = [
  { id: "evidence", label: "Digitalni pecat", status: "pending" },
];

/**
 * Durations tuned so all steps finish BEFORE the backend returns (~7-15s).
 * The last step ("evidence") stays spinning until the real result arrives.
 * Image: 8 steps × ~1s = ~8s, Document: 4 steps × ~0.8s = ~3s.
 */
const IMAGE_STEP_DURATIONS: Record<string, number> = {
  metadata_analysis: 0.8,
  modification_detection: 1,
  safe_ai_detection: 1,
  dinov2_ai_detection: 1,
  community_forensics_detection: 1,
  efficientnet_ai_detection: 1,
  clip_ai_detection: 1,
  mesorch_detection: 1,
};

const DOCUMENT_STEP_DURATIONS: Record<string, number> = {
  document_forensics: 0.8,
  text_ai_detection: 0.8,
  content_validation: 0.8,
  embedded_images: 1,
};

const SHARED_STEP_DURATIONS: Record<string, number> = {
  evidence: 5,
};

// Keep the old DEFAULT_STEPS for backward compatibility (single image)
const DEFAULT_STEPS: ForensicStep[] = [
  ...IMAGE_STEPS,
  ...SHARED_STEPS,
];

const STEP_DURATIONS: Record<string, number> = {
  ...IMAGE_STEP_DURATIONS,
  ...SHARED_STEP_DURATIONS,
};

// ---------------------------------------------------------------------------
// Per-file progress data
// ---------------------------------------------------------------------------

export interface FileProgress {
  fileName: string;
  fileType: "image" | "document";
  steps: ForensicStep[];
  status: "pending" | "active" | "complete";
}

function isDocumentFile(name: string): boolean {
  const ext = name.split(".").pop()?.toLowerCase() ?? "";
  return ["pdf", "docx", "xlsx", "doc", "xls"].includes(ext);
}

function getStepsForFile(fileName: string): ForensicStep[] {
  return isDocumentFile(fileName)
    ? DOCUMENT_STEPS.map((s) => ({ ...s }))
    : IMAGE_STEPS.map((s) => ({ ...s }));
}

function getDurationsForFile(fileName: string): Record<string, number> {
  return isDocumentFile(fileName) ? DOCUMENT_STEP_DURATIONS : IMAGE_STEP_DURATIONS;
}

// ---------------------------------------------------------------------------
// Component: ForensicProgress
// ---------------------------------------------------------------------------

interface ForensicProgressProps {
  steps?: ForensicStep[];
  progress: number; // 0.0 - 1.0
  fileProgresses?: FileProgress[];
  currentFileIndex?: number;
}

export function ForensicProgress({ steps, progress, fileProgresses, currentFileIndex }: ForensicProgressProps) {
  // Multi-file mode
  if (fileProgresses && fileProgresses.length > 1) {
    const totalFiles = fileProgresses.length;
    const completedFiles = fileProgresses.filter((f) => f.status === "complete").length;
    const activeFile = fileProgresses.find((f) => f.status === "active");
    const allComplete = progress >= 1;

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
                <span className="text-emerald-600 font-medium">Zavrseno</span>
              ) : (
                `Datoteka ${Math.min(completedFiles + 1, totalFiles)}/${totalFiles}`
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
          {activeFile && !allComplete && (
            <p className="text-xs text-muted animate-pulse">
              Analiziram {activeFile.fileType === "document" ? "dokument" : "sliku"}: {activeFile.fileName}...
            </p>
          )}
        </div>

        {/* Per-file sections */}
        <div className="space-y-3">
          {fileProgresses.map((fp, idx) => (
            <div key={idx} className={cn(
              "rounded-lg border p-3 transition-colors",
              fp.status === "complete" ? "border-emerald-200 bg-emerald-50/30" :
              fp.status === "active" ? "border-accent/30 bg-accent/5" :
              "border-border bg-card/50 opacity-60"
            )}>
              <div className="flex items-center gap-2 mb-2">
                <div className="flex-shrink-0 w-4 h-4 flex items-center justify-center">
                  {fp.status === "complete" ? (
                    <svg className="w-4 h-4 text-emerald-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
                      <path strokeLinecap="round" strokeLinejoin="round" d="M4.5 12.75l6 6 9-13.5" />
                    </svg>
                  ) : fp.status === "active" ? (
                    <div className="w-3 h-3 border-2 border-accent border-t-transparent rounded-full animate-spin" />
                  ) : (
                    <div className="w-2 h-2 rounded-full bg-gray-300" />
                  )}
                </div>
                <span className={cn(
                  "text-xs font-medium truncate",
                  fp.status === "complete" ? "text-emerald-700" :
                  fp.status === "active" ? "text-accent" : "text-muted"
                )}>
                  {fp.fileName}
                </span>
                <span className={cn(
                  "text-[10px] px-1.5 py-0.5 rounded-full ml-auto flex-shrink-0",
                  fp.fileType === "document" ? "bg-blue-100 text-blue-700" : "bg-purple-100 text-purple-700"
                )}>
                  {fp.fileType === "document" ? "DOC" : "IMG"}
                </span>
              </div>

              {fp.status === "active" && (
                <div className="space-y-0.5 ml-6">
                  {fp.steps.map((step) => (
                    <div
                      key={step.id}
                      className={cn(
                        "flex items-center gap-2 py-0.5 text-[11px] transition-colors",
                        step.status === "complete" && "text-emerald-600",
                        step.status === "active" && "text-accent font-medium",
                        step.status === "pending" && "text-muted"
                      )}
                    >
                      <div className="flex-shrink-0 w-3 h-3 flex items-center justify-center">
                        {step.status === "complete" ? (
                          <svg className="w-3 h-3 text-emerald-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
                            <path strokeLinecap="round" strokeLinejoin="round" d="M4.5 12.75l6 6 9-13.5" />
                          </svg>
                        ) : step.status === "active" ? (
                          <div className="w-2.5 h-2.5 border-[1.5px] border-accent border-t-transparent rounded-full animate-spin" />
                        ) : (
                          <div className="w-1.5 h-1.5 rounded-full bg-gray-300" />
                        )}
                      </div>
                      <span>{step.label}</span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          ))}

          {/* Shared steps (agent + evidence) */}
          {fileProgresses.every((f) => f.status === "complete") && !allComplete && (
            <div className="rounded-lg border border-accent/30 bg-accent/5 p-3">
              <div className="flex items-center gap-2 mb-2">
                <div className="w-3 h-3 border-2 border-accent border-t-transparent rounded-full animate-spin" />
                <span className="text-xs font-medium text-accent">Zavrsna evaluacija</span>
              </div>
            </div>
          )}
        </div>
      </div>
    );
  }

  // Single-file fallback (original behavior)
  const displaySteps = steps || DEFAULT_STEPS;
  const completedCount = displaySteps.filter((s) => s.status === "complete").length;
  const activeStep = displaySteps.find((s) => s.status === "active");
  const allComplete = completedCount === displaySteps.length;
  const lastStepIdx = displaySteps.length - 1;
  const waitingForServer = activeStep?.id === displaySteps[lastStepIdx]?.id
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
              <span className="text-emerald-600 font-medium">Zavrseno</span>
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
// Hook: useForensicProgress — supports both single-file and multi-file
// ---------------------------------------------------------------------------

export function useForensicProgress(isActive: boolean, files?: File[]) {
  const [steps, setSteps] = useState<ForensicStep[]>(() => createForensicSteps());
  const [progress, setProgress] = useState(0);
  const [fileProgresses, setFileProgresses] = useState<FileProgress[]>([]);
  const [currentFileIndex, setCurrentFileIndex] = useState(0);
  const stepIndexRef = useRef(0);
  const stepElapsedRef = useRef(0);
  const fileIndexRef = useRef(0);
  const isMultiFile = (files?.length ?? 0) > 1;

  // Reset whenever analysis starts
  useEffect(() => {
    if (!isActive) return;

    if (isMultiFile && files) {
      // Multi-file mode: build per-file progress
      const fps: FileProgress[] = files.map((f) => ({
        fileName: f.name,
        fileType: isDocumentFile(f.name) ? "document" : "image",
        steps: getStepsForFile(f.name),
        status: "pending",
      }));
      fps[0].status = "active";
      fps[0].steps[0].status = "active";
      setFileProgresses(fps);
      setCurrentFileIndex(0);
      fileIndexRef.current = 0;
      stepIndexRef.current = 0;
      stepElapsedRef.current = 0;
      setProgress(0);
    } else {
      // Single-file mode (original behavior)
      const fresh = createForensicSteps();
      fresh[0].status = "active";
      setSteps(fresh);
      setProgress(0);
      stepIndexRef.current = 0;
      stepElapsedRef.current = 0;
    }
  }, [isActive, isMultiFile]);

  // Tick every 500ms — multi-file mode
  useEffect(() => {
    if (!isActive || !isMultiFile || !files) return;

    const tick = 0.5;

    // Calculate total estimated duration across all files + shared
    const totalDuration = files.reduce((sum, f) => {
      const durations = getDurationsForFile(f.name);
      return sum + Object.values(durations).reduce((a, b) => a + b, 0);
    }, 0) + Object.values(SHARED_STEP_DURATIONS).reduce((a, b) => a + b, 0);

    const interval = setInterval(() => {
      stepElapsedRef.current += tick;

      setFileProgresses((prev) => {
        const fps = prev.map((fp) => ({
          ...fp,
          steps: fp.steps.map((s) => ({ ...s })),
        }));

        const fi = fileIndexRef.current;
        if (fi >= fps.length) {
          // All files done, in shared steps phase — asymptotic creep
          const extraTime = stepElapsedRef.current;
          const creep = 0.90 + 0.08 * (1 - Math.exp(-extraTime / 20));
          setProgress(Math.min(creep, 0.98));
          return fps;
        }

        const currentFp = fps[fi];
        const durations = getDurationsForFile(currentFp.fileName);
        const stepIds = currentFp.steps.map((s) => s.id);
        const si = stepIndexRef.current;

        if (si >= stepIds.length) {
          // Current file complete, move to next file
          currentFp.status = "complete";
          currentFp.steps = currentFp.steps.map((s) => ({ ...s, status: "complete" as const }));

          const nextFi = fi + 1;
          fileIndexRef.current = nextFi;
          stepIndexRef.current = 0;
          stepElapsedRef.current = 0;
          setCurrentFileIndex(nextFi);

          if (nextFi < fps.length) {
            fps[nextFi].status = "active";
            fps[nextFi].steps[0].status = "active";
          }

          return fps;
        }

        const currentStepId = stepIds[si];
        const duration = durations[currentStepId] || 3;

        if (stepElapsedRef.current >= duration) {
          // Complete current step, activate next
          stepElapsedRef.current = 0;
          currentFp.steps[si].status = "complete";
          const nextSi = si + 1;
          stepIndexRef.current = nextSi;

          if (nextSi < stepIds.length) {
            currentFp.steps[nextSi].status = "active";
          }
        }

        // Calculate overall progress
        let completedDuration = 0;
        for (let f = 0; f < fi; f++) {
          const d = getDurationsForFile(fps[f].fileName);
          completedDuration += Object.values(d).reduce((a, b) => a + b, 0);
        }
        if (fi < fps.length) {
          const currentDurations = getDurationsForFile(fps[fi].fileName);
          const currentStepIds = fps[fi].steps.map((s) => s.id);
          for (let s = 0; s < stepIndexRef.current; s++) {
            completedDuration += currentDurations[currentStepIds[s]] || 3;
          }
          if (stepIndexRef.current < currentStepIds.length) {
            const curDur = currentDurations[currentStepIds[stepIndexRef.current]] || 3;
            completedDuration += Math.min(stepElapsedRef.current / curDur, 0.95) * curDur;
          }
        }

        setProgress(Math.min(completedDuration / totalDuration, 0.90));

        return fps;
      });
    }, tick * 1000);

    return () => clearInterval(interval);
  }, [isActive, isMultiFile, files]);

  // Tick every 500ms — single-file mode (original)
  useEffect(() => {
    if (!isActive || isMultiFile) return;

    const stepIds = DEFAULT_STEPS.map((s) => s.id);
    const lastStepIndex = DEFAULT_STEPS.length - 1;
    const totalEstDuration = Object.values(STEP_DURATIONS).reduce((a, b) => a + b, 0);
    const tick = 0.5; // seconds per interval

    const interval = setInterval(() => {
      stepElapsedRef.current += tick;
      const idx = stepIndexRef.current;

      // Already past all steps (complete() was called) — nothing to do
      if (idx > lastStepIndex) return;

      const currentId = stepIds[idx];
      const duration = STEP_DURATIONS[currentId] || 3;

      // Last step: NEVER auto-complete — keep it spinning until complete() is called.
      // Slowly creep progress from ~90% toward 98% using asymptotic curve.
      if (idx === lastStepIndex) {
        const extraTime = stepElapsedRef.current;
        const creep = 0.90 + 0.08 * (1 - Math.exp(-extraTime / 40));
        setProgress(Math.min(creep, 0.98));
        return;
      }

      if (stepElapsedRef.current >= duration) {
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

      const completedDuration = stepIds
        .slice(0, stepIndexRef.current)
        .reduce((sum, id) => sum + (STEP_DURATIONS[id] || 3), 0);
      const currentDuration = STEP_DURATIONS[stepIds[stepIndexRef.current]] || 3;
      const withinStep = Math.min(stepElapsedRef.current / currentDuration, 0.95);
      const totalProg = (completedDuration + withinStep * currentDuration) / totalEstDuration;

      setProgress(Math.min(totalProg, 0.90));
    }, tick * 1000);

    return () => clearInterval(interval);
  }, [isActive, isMultiFile]);

  /**
   * Call when the real API result arrives.
   * Rapidly cascades through remaining steps (120ms each) so the user
   * sees every step turn green, then resolves the returned Promise.
   */
  const complete = useCallback((): Promise<void> => {
    return new Promise<void>((resolve) => {
      // Stop the normal tick timers by pushing index past the end
      stepIndexRef.current = 999;
      fileIndexRef.current = 999;

      // Collect all remaining pending/active steps across single + multi-file
      const CASCADE_MS = 120;

      // Single-file mode: cascade steps
      setSteps((prev) => {
        const remaining = prev.filter((s) => s.status !== "complete");
        if (remaining.length === 0) {
          setProgress(1);
          resolve();
          return prev;
        }

        let delay = 0;
        for (const step of remaining) {
          const id = step.id;
          delay += CASCADE_MS;
          setTimeout(() => {
            setSteps((cur) =>
              cur.map((s) => (s.id === id ? { ...s, status: "complete" as const } : s))
            );
          }, delay);
        }
        setTimeout(() => {
          setProgress(1);
        }, delay);
        // Don't resolve yet — multi-file cascade below handles its own resolve
        if (!isMultiFile) {
          setTimeout(resolve, delay + 200);
        }
        return prev;
      });

      // Multi-file mode: cascade file-by-file, step-by-step
      setFileProgresses((prev) => {
        if (prev.length === 0) {
          if (isMultiFile) resolve();
          return prev;
        }
        let delay = 0;
        for (let fi = 0; fi < prev.length; fi++) {
          const fp = prev[fi];
          const pendingSteps = fp.steps.filter((s) => s.status !== "complete");
          for (const step of pendingSteps) {
            delay += CASCADE_MS;
            const capturedFi = fi;
            const capturedStepId = step.id;
            setTimeout(() => {
              setFileProgresses((cur) =>
                cur.map((f, idx) =>
                  idx === capturedFi
                    ? {
                        ...f,
                        status: f.steps.every((s) => s.id === capturedStepId || s.status === "complete")
                          ? ("complete" as const)
                          : ("active" as const),
                        steps: f.steps.map((s) =>
                          s.id === capturedStepId ? { ...s, status: "complete" as const } : s
                        ),
                      }
                    : f
                )
              );
            }, delay);
          }
          // Mark file complete after its steps
          delay += CASCADE_MS;
          const capturedFi2 = fi;
          setTimeout(() => {
            setFileProgresses((cur) =>
              cur.map((f, idx) =>
                idx === capturedFi2
                  ? {
                      ...f,
                      status: "complete" as const,
                      steps: f.steps.map((s) => ({ ...s, status: "complete" as const })),
                    }
                  : f
              )
            );
          }, delay);
        }
        // Smooth progress ramp
        const totalDelay = delay;
        const progressInterval = setInterval(() => {
          setProgress((p) => {
            const next = Math.min(p + 0.05, 1);
            if (next >= 1) clearInterval(progressInterval);
            return next;
          });
        }, CASCADE_MS);
        setTimeout(() => {
          clearInterval(progressInterval);
          setProgress(1);
          resolve();
        }, totalDelay + 200);
        return prev;
      });
    });
  }, [isMultiFile]);

  /** Reset to initial state. */
  const reset = useCallback(() => {
    setSteps(createForensicSteps());
    setFileProgresses([]);
    setProgress(0);
    setCurrentFileIndex(0);
    stepIndexRef.current = 0;
    stepElapsedRef.current = 0;
    fileIndexRef.current = 0;
  }, []);

  return { steps, progress, fileProgresses, currentFileIndex, complete, reset };
}

// ---------------------------------------------------------------------------
// Pure helpers
// ---------------------------------------------------------------------------

export function createForensicSteps(): ForensicStep[] {
  return DEFAULT_STEPS.map((s) => ({ ...s }));
}

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
