"use client";

import { cn } from "@/lib/cn";

interface ProgressStepsProps {
  currentStep: number;
}

const steps = [
  { label: "Upload" },
  { label: "Analiza" },
  { label: "Rezultat" },
];

export function ProgressSteps({ currentStep }: ProgressStepsProps) {
  return (
    <div className="flex items-center justify-center gap-2">
      {steps.map((step, i) => {
        const isCompleted = i < currentStep;
        const isActive = i === currentStep;

        return (
          <div key={step.label} className="flex items-center gap-2">
            <div className="flex items-center gap-2">
              <div
                className={cn(
                  "w-7 h-7 rounded-full flex items-center justify-center text-xs font-medium",
                  (isCompleted || isActive) && "bg-accent text-white",
                  !isCompleted && !isActive && "bg-gray-100 text-muted"
                )}
              >
                {isCompleted ? (
                  <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
                  </svg>
                ) : (
                  <span>{i + 1}</span>
                )}
              </div>
              <span
                className={cn(
                  "text-xs font-medium hidden sm:block",
                  isActive || isCompleted ? "text-foreground" : "text-muted"
                )}
              >
                {step.label}
              </span>
            </div>
            {i < steps.length - 1 && (
              <div className="w-8 sm:w-12 h-px mx-1">
                <div
                  className={cn(
                    "h-full rounded-full",
                    i < currentStep ? "bg-accent" : "bg-border"
                  )}
                />
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
