"use client";

import Link from "next/link";
import type { Inspection } from "@/lib/api";
import { formatDate, severityColor, severityLabel, fraudRiskLabel, fraudRiskColor } from "@/lib/api";
import { cn } from "@/lib/cn";

interface InspectionCardProps {
  inspection: Inspection;
}

export function InspectionCard({ inspection: i }: InspectionCardProps) {
  const worstSeverity = i.damages.reduce(
    (worst, d) => {
      const order = ["Minor", "Moderate", "Severe", "Critical"];
      return order.indexOf(d.severity) > order.indexOf(worst) ? d.severity : worst;
    },
    "Minor"
  );

  return (
    <Link href={`/inspections/${i.id}`}>
      <div className="bg-card border border-border rounded-xl overflow-hidden hover:border-border transition-colors">
        <div className="relative overflow-hidden bg-card">
          <img src={i.imageUrl} alt={i.originalFileName} loading="lazy" decoding="async" className="w-full aspect-[4/3] object-cover"
            onError={(e) => { (e.target as HTMLImageElement).src = "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='100' height='100' viewBox='0 0 24 24' fill='none' stroke='%23999' stroke-width='1.5'%3E%3Crect x='3' y='3' width='18' height='18' rx='2' /%3E%3Cpath d='m3 16 5-5 2 2 4-4 7 7' /%3E%3C/svg%3E"; }} />
          <div className="absolute top-2 right-2 sm:top-3 sm:right-3">
            <span className={cn("px-1.5 py-0.5 sm:px-2.5 sm:py-1 rounded-full text-[10px] sm:text-xs font-medium",
              i.status === "Completed" ? "bg-green-500/15 text-green-600 dark:text-green-400" : i.status === "Failed" ? "bg-red-500/15 text-red-600 dark:text-red-400" : "bg-amber-500/15 text-amber-600 dark:text-amber-400"
            )}>
              {i.status === "Completed" ? "Završeno" : i.status === "Failed" ? "Greška" : "U obradi"}
            </span>
          </div>
          {i.damages.length > 0 && (
            <div className="absolute bottom-3 left-3">
              <span className={cn("text-xs font-semibold bg-white/90 px-2 py-1 rounded", severityColor(worstSeverity))}>
                {i.damages.length} {i.damages.length === 1 ? "nalaz" : "nalaza"} &middot; {severityLabel(worstSeverity)}
              </span>
            </div>
          )}
        </div>
        <div className="p-2.5 sm:p-4">
          <h3 className="font-medium truncate mb-1 text-xs sm:text-base">{i.originalFileName}</h3>
          <div className="flex items-center justify-between">
            <span className="text-[10px] sm:text-xs text-muted">{formatDate(i.createdAt)}</span>
            {i.fraudRiskLevel && (
              <span className={cn("text-[10px] sm:text-sm font-semibold", fraudRiskColor(i.fraudRiskLevel))}>
                {fraudRiskLabel(i.fraudRiskLevel)}
              </span>
            )}
          </div>
        </div>
      </div>
    </Link>
  );
}
