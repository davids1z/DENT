"use client";

import Link from "next/link";
import type { Inspection } from "@/lib/api";
import { formatCurrency, formatDate, severityColor } from "@/lib/api";

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
      <div className="bg-card rounded-2xl border border-border overflow-hidden hover:border-accent/30 transition-all group">
        {/* Image */}
        <div className="relative h-48 overflow-hidden bg-background">
          <img
            src={i.imageUrl}
            alt={i.originalFileName}
            className="w-full h-full object-cover group-hover:scale-105 transition-transform duration-500"
            onError={(e) => {
              (e.target as HTMLImageElement).src = "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='100' height='100' viewBox='0 0 24 24' fill='none' stroke='%2371717a' stroke-width='1.5'%3E%3Crect x='3' y='3' width='18' height='18' rx='2' /%3E%3Cpath d='m3 16 5-5 2 2 4-4 7 7' /%3E%3C/svg%3E";
            }}
          />
          <div className="absolute top-3 right-3">
            <span
              className={`px-2.5 py-1 rounded-full text-xs font-medium backdrop-blur-sm ${
                i.status === "Completed"
                  ? "bg-green-500/20 text-green-400"
                  : i.status === "Failed"
                  ? "bg-red-500/20 text-red-400"
                  : "bg-yellow-500/20 text-yellow-400"
              }`}
            >
              {i.status === "Completed" ? "Zavrseno" : i.status === "Failed" ? "Greska" : "U obradi"}
            </span>
          </div>
        </div>

        {/* Info */}
        <div className="p-4">
          <div className="flex items-center justify-between mb-2">
            <h3 className="font-medium truncate">
              {i.vehicleMake && i.vehicleModel
                ? `${i.vehicleMake} ${i.vehicleModel}`
                : i.originalFileName}
            </h3>
            {i.damages.length > 0 && (
              <span className={`text-xs font-medium ${severityColor(worstSeverity)}`}>
                {i.damages.length} {i.damages.length === 1 ? "steta" : "steta"}
              </span>
            )}
          </div>

          <div className="flex items-center justify-between">
            <span className="text-xs text-muted">{formatDate(i.createdAt)}</span>
            {i.totalEstimatedCostMin != null && (
              <span className="text-sm font-semibold text-accent">
                {formatCurrency(i.totalEstimatedCostMin)}
                {i.totalEstimatedCostMax && i.totalEstimatedCostMax !== i.totalEstimatedCostMin
                  ? ` - ${formatCurrency(i.totalEstimatedCostMax)}`
                  : ""}
              </span>
            )}
          </div>
        </div>
      </div>
    </Link>
  );
}
