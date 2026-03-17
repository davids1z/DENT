"use client";

import Link from "next/link";
import type { Inspection } from "@/lib/api";
import { formatCurrency, formatDate, severityColor, severityLabel } from "@/lib/api";
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
      <div className="bg-card border border-border rounded-xl overflow-hidden hover:border-gray-300 transition-colors">
        <div className="relative h-48 overflow-hidden bg-gray-50">
          <img src={i.imageUrl} alt={i.originalFileName} loading="eager" className="w-full h-full object-cover"
            onError={(e) => { (e.target as HTMLImageElement).src = "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='100' height='100' viewBox='0 0 24 24' fill='none' stroke='%23999' stroke-width='1.5'%3E%3Crect x='3' y='3' width='18' height='18' rx='2' /%3E%3Cpath d='m3 16 5-5 2 2 4-4 7 7' /%3E%3C/svg%3E"; }} />
          <div className="absolute top-3 right-3">
            <span className={cn("px-2.5 py-1 rounded-full text-xs font-medium",
              i.status === "Completed" ? "bg-green-100 text-green-700" : i.status === "Failed" ? "bg-red-100 text-red-700" : "bg-amber-100 text-amber-700"
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
        <div className="p-4">
          <h3 className="font-medium truncate mb-1">{i.originalFileName}</h3>
          <div className="flex items-center justify-between">
            <span className="text-xs text-muted">{formatDate(i.createdAt)}</span>
            {i.totalEstimatedCostMin != null && (
              <span className="text-sm font-semibold text-accent">
                {formatCurrency(i.totalEstimatedCostMin)}{i.totalEstimatedCostMax && i.totalEstimatedCostMax !== i.totalEstimatedCostMin ? ` - ${formatCurrency(i.totalEstimatedCostMax)}` : ""}
              </span>
            )}
          </div>
        </div>
      </div>
    </Link>
  );
}
