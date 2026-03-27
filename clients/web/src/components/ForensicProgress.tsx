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
  { id: "bfree_detection", label: "B-Free AI detekcija", status: "pending" },
  { id: "spai_detection", label: "SPAI spektralna detekcija", status: "pending" },
];

export const DOCUMENT_STEPS: ForensicStep[] = [
  { id: "doc_structure", label: "Struktura, revizije i metapodaci", status: "pending" },
  { id: "doc_fonts", label: "Fontovi, glifovi i metrike znakova", status: "pending" },
  { id: "doc_signatures", label: "Potpisi i redakcija", status: "pending" },
  { id: "doc_manipulation", label: "Shadow napadi, OCG i anotacije", status: "pending" },
  { id: "doc_visual", label: "Vizualna vs OCR analiza", status: "pending" },
  { id: "doc_advanced", label: "ToUnicode, JavaScript i ELA", status: "pending" },
  { id: "doc_content", label: "AI tekst i validacija sadrzaja", status: "pending" },
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
  bfree_detection: 1.5,
  spai_detection: 2,
};

const DOCUMENT_STEP_DURATIONS: Record<string, number> = {
  doc_structure: 1.0,
  doc_fonts: 1.2,
  doc_signatures: 1.0,
  doc_manipulation: 1.2,
  doc_visual: 1.5,
  doc_advanced: 1.3,
  doc_content: 1.0,
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
          <div className="h-2 bg-card-hover rounded-full overflow-hidden">
            <div
              className={cn(
                "h-full rounded-full transition-[width] duration-700 ease-linear",
                allComplete ? "bg-emerald-500" : "bg-accent"
              )}
              style={{ width: `${(progress * 100).toFixed(1)}%` }}
            />
          </div>
          {activeFile && !allComplete && (
            <p className="text-xs text-muted animate-pulse">
              Analiziram {activeFile.fileType === "document" ? "dokument" : "sliku"}: {activeFile.fileName}...
            </p>
          )}
        </div>

        {/* Per-file sections — show max 3, collapse rest */}
        <div className="space-y-3">
          {fileProgresses.slice(0, 3).map((fp, idx) => (
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
                    <div className="w-2 h-2 rounded-full bg-border" />
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
                          <div className="w-1.5 h-1.5 rounded-full bg-border" />
                        )}
                      </div>
                      <span>{step.label}</span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          ))}

          {fileProgresses.length > 3 && (
            <div className="rounded-lg border border-border bg-card/50 p-3 text-center">
              <span className="text-xs text-muted">
                +{fileProgresses.length - 3} {fileProgresses.length - 3 === 1 ? "datoteka" : "datoteka"} u obradi
              </span>
            </div>
          )}

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
        <div className="h-2 bg-card-hover rounded-full overflow-hidden">
          <div
            className={cn(
              "h-full rounded-full transition-[width] duration-700 ease-linear",
              allComplete ? "bg-emerald-500" : "bg-accent"
            )}
            style={{ width: `${(progress * 100).toFixed(1)}%` }}
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
                <div className="w-2 h-2 rounded-full bg-border" />
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

  // Detect single-file type for proper step selection
  const singleFileName = (!isMultiFile && files?.[0]?.name) || "";
  const isSingleDoc = singleFileName ? isDocumentFile(singleFileName) : false;

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
      // Single-file mode — pick steps based on file type
      const baseSteps = isSingleDoc
        ? DOCUMENT_STEPS.map((s) => ({ ...s }))
        : IMAGE_STEPS.map((s) => ({ ...s }));
      const fresh = [...baseSteps, ...SHARED_STEPS.map((s) => ({ ...s }))];
      fresh[0].status = "active";
      setSteps(fresh);
      setProgress(0);
      stepIndexRef.current = 0;
      stepElapsedRef.current = 0;
    }
  }, [isActive, isMultiFile, isSingleDoc]);

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

    const currentSteps = isSingleDoc
      ? [...DOCUMENT_STEPS, ...SHARED_STEPS]
      : [...IMAGE_STEPS, ...SHARED_STEPS];
    const currentDurations = isSingleDoc
      ? { ...DOCUMENT_STEP_DURATIONS, ...SHARED_STEP_DURATIONS }
      : { ...IMAGE_STEP_DURATIONS, ...SHARED_STEP_DURATIONS };

    const stepIds = currentSteps.map((s) => s.id);
    const lastStepIndex = currentSteps.length - 1;
    const totalEstDuration = Object.values(currentDurations).reduce((a, b) => a + b, 0);
    const tick = 0.5; // seconds per interval

    const interval = setInterval(() => {
      stepElapsedRef.current += tick;
      const idx = stepIndexRef.current;

      // Already past all steps (complete() was called) — nothing to do
      if (idx > lastStepIndex) return;

      const currentId = stepIds[idx];
      const duration = currentDurations[currentId] || 3;

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
        .reduce((sum, id) => sum + (currentDurations[id] || 3), 0);
      const currentDuration = currentDurations[stepIds[stepIndexRef.current]] || 3;
      const withinStep = Math.min(stepElapsedRef.current / currentDuration, 0.95);
      const totalProg = (completedDuration + withinStep * currentDuration) / totalEstDuration;

      setProgress(Math.min(totalProg, 0.90));
    }, tick * 1000);

    return () => clearInterval(interval);
  }, [isActive, isMultiFile, isSingleDoc]);

  /**
   * Call when the real API result arrives.
   * Completes remaining steps one-by-one (250ms each) via a simple interval,
   * then resolves the Promise so the caller can show the result screen.
   */
  const complete = useCallback((): Promise<void> => {
    // Stop the normal tick timers
    stepIndexRef.current = 999;
    fileIndexRef.current = 999;

    return new Promise<void>((resolve) => {
      const TICK = 120; // ms between each step turning green

      const iv = setInterval(() => {
        let madeProgress = false;

        // ── Single-file mode: complete next pending/active step ──
        setSteps((prev) => {
          const idx = prev.findIndex((s) => s.status !== "complete");
          if (idx === -1) return prev; // all done
          madeProgress = true;
          return prev.map((s, i) => (i === idx ? { ...s, status: "complete" as const } : s));
        });

        // ── Multi-file mode: complete next pending/active step across files ──
        setFileProgresses((prev) => {
          if (prev.length === 0) return prev;
          for (let fi = 0; fi < prev.length; fi++) {
            const fp = prev[fi];
            const si = fp.steps.findIndex((s) => s.status !== "complete");
            if (si !== -1) {
              madeProgress = true;
              return prev.map((f, fIdx) => {
                if (fIdx !== fi) return f;
                const newSteps = f.steps.map((s, sIdx) =>
                  sIdx === si ? { ...s, status: "complete" as const } : s
                );
                const allDone = newSteps.every((s) => s.status === "complete");
                return { ...f, status: allDone ? "complete" as const : "active" as const, steps: newSteps };
              });
            }
          }
          return prev; // all files done
        });

        // Ramp progress toward 100%
        setProgress((p) => Math.min(p + 0.08, 1));

        // Check if everything is done
        if (!madeProgress) {
          clearInterval(iv);
          setProgress(1);
          resolve();
        }
      }, TICK);
    });
  }, []);

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
