"use client";

import { decisionOutcomeLabel } from "@/lib/api";
import { cn } from "@/lib/cn";

interface DecisionBadgeProps {
  outcome: string;
  reason?: string | null;
  className?: string;
}

const badgeStyles: Record<string, string> = {
  AutoApprove: "bg-green-50 border-green-200 text-green-700",
  HumanReview: "bg-amber-50 border-amber-200 text-amber-700",
  Escalate: "bg-red-50 border-red-200 text-red-700",
};

const iconColor: Record<string, string> = {
  AutoApprove: "text-green-600",
  HumanReview: "text-amber-600",
  Escalate: "text-red-600",
};

export function DecisionBadge({ outcome, reason, className }: DecisionBadgeProps) {
  return (
    <div
      className={cn(
        "rounded-xl border p-4",
        badgeStyles[outcome] || "bg-gray-50 border-gray-200 text-gray-700",
        className
      )}
    >
      <div className="flex items-center gap-3">
        <div className={cn("flex-shrink-0", iconColor[outcome] || "text-gray-500")}>
          {outcome === "AutoApprove" && <CheckIcon />}
          {outcome === "HumanReview" && <EyeIcon />}
          {outcome === "Escalate" && <AlertIcon />}
        </div>
        <div className="min-w-0">
          <div className="font-semibold text-sm">
            {decisionOutcomeLabel(outcome)}
          </div>
          {reason && (
            <p className="text-xs opacity-75 mt-0.5 leading-relaxed">{reason}</p>
          )}
        </div>
      </div>
    </div>
  );
}

function CheckIcon() {
  return (
    <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M9 12.75L11.25 15 15 9.75m-3-7.036A11.959 11.959 0 013.598 6 11.99 11.99 0 003 9.749c0 5.592 3.824 10.29 9 11.623 5.176-1.332 9-6.03 9-11.622 0-1.31-.21-2.571-.598-3.751h-.152c-3.196 0-6.1-1.248-8.25-3.285z" />
    </svg>
  );
}

function EyeIcon() {
  return (
    <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M2.036 12.322a1.012 1.012 0 010-.639C3.423 7.51 7.36 4.5 12 4.5c4.638 0 8.573 3.007 9.963 7.178.07.207.07.431 0 .639C20.577 16.49 16.64 19.5 12 19.5c-4.638 0-8.573-3.007-9.963-7.178z" />
      <path strokeLinecap="round" strokeLinejoin="round" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
    </svg>
  );
}

function AlertIcon() {
  return (
    <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v3.75m-9.303 3.376c-.866 1.5.217 3.374 1.948 3.374h14.71c1.73 0 2.813-1.874 1.948-3.374L13.949 3.378c-.866-1.5-3.032-1.5-3.898 0L2.697 16.126zM12 15.75h.007v.008H12v-.008z" />
    </svg>
  );
}
