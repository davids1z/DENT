"use client";

import { fraudRiskLabel, fraudRiskBg, fraudRiskColor } from "@/lib/api";
import { cn } from "@/lib/cn";

interface ForensicBadgeProps {
  riskScore: number;
  riskLevel: string;
  className?: string;
}

export function ForensicBadge({ riskScore, riskLevel, className }: ForensicBadgeProps) {
  const percentage = Math.round(riskScore * 100);

  return (
    <div
      className={cn(
        "rounded-xl border p-4",
        fraudRiskBg(riskLevel),
        className
      )}
    >
      <div className="flex items-center gap-3">
        <div className={cn("flex-shrink-0", fraudRiskColor(riskLevel))}>
          <ShieldIcon />
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex items-center justify-between">
            <span className="font-semibold text-sm">
              Forenzicka analiza: {fraudRiskLabel(riskLevel)}
            </span>
            <span className={cn("text-sm font-mono font-bold", fraudRiskColor(riskLevel))}>
              {percentage}%
            </span>
          </div>
          <div className="mt-1.5 h-1.5 bg-black/5 rounded-full overflow-hidden">
            <div
              className={cn(
                "h-full rounded-full transition-all duration-500",
                riskLevel === "Low" && "bg-green-500",
                riskLevel === "Medium" && "bg-amber-500",
                riskLevel === "High" && "bg-orange-500",
                riskLevel === "Critical" && "bg-red-500",
              )}
              style={{ width: `${percentage}%` }}
            />
          </div>
        </div>
      </div>
    </div>
  );
}

function ShieldIcon() {
  return (
    <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
      <path
        strokeLinecap="round"
        strokeLinejoin="round"
        d="M9 12.75L11.25 15 15 9.75m-3-7.036A11.959 11.959 0 013.598 6 11.99 11.99 0 003 9.749c0 5.592 3.824 10.29 9 11.623 5.176-1.332 9-6.03 9-11.622 0-1.31-.21-2.571-.598-3.751h-.152c-3.196 0-6.1-1.248-8.25-3.285z"
      />
    </svg>
  );
}
