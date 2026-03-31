"use client";

import type { CrossImageReport, ForensicResult } from "@/lib/api";
import { cn } from "@/lib/cn";

interface GroupFile {
  url: string;
  fileName: string;
  sortOrder: number;
  forensicResult: ForensicResult | null;
}

interface CrossImageFindingsProps {
  report: CrossImageReport;
  files: GroupFile[];
}

const FINDING_LABELS: Record<string, string> = {
  CROSS_META_CAMERA_MISMATCH: "Razliciti uredaji",
  CROSS_META_TIMESTAMP_GAP: "Nekonzistentan vremenski okvir",
  CROSS_META_GPS_MISMATCH: "Razlicite GPS lokacije",
  CROSS_META_SOFTWARE_MISMATCH: "Razlicit softver za obradu",
  CROSS_RISK_OUTLIER: "Rizicni outlier u skupini",
  CROSS_RISK_ALL_HIGH: "Svi fajlovi visokorizicni",
  CROSS_SAME_GENERATOR: "Isti AI generator detektiran",
  CROSS_NEAR_DUPLICATE: "Gotovo identicne datoteke",
  CROSS_COMPRESSION_MISMATCH: "Nekonzistentna kompresija",
};

const FINDING_ICONS: Record<string, string> = {
  CROSS_META_CAMERA_MISMATCH: "M3 9a2 2 0 012-2h.93a2 2 0 001.664-.89l.812-1.22A2 2 0 0110.07 4h3.86a2 2 0 011.664.89l.812 1.22A2 2 0 0018.07 7H19a2 2 0 012 2v9a2 2 0 01-2 2H5a2 2 0 01-2-2V9z",
  CROSS_META_TIMESTAMP_GAP: "M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z",
  CROSS_META_GPS_MISMATCH: "M17.657 16.657L13.414 20.9a1.998 1.998 0 01-2.827 0l-4.244-4.243a8 8 0 1111.314 0z",
  CROSS_RISK_OUTLIER: "M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z",
  CROSS_NEAR_DUPLICATE: "M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z",
};

export function CrossImageFindings({ report, files }: CrossImageFindingsProps) {
  if (!report.findings || report.findings.length === 0) return null;

  return (
    <div className="bg-card border border-border rounded-2xl p-5 sm:p-6">
      <h3 className="font-heading font-semibold text-base mb-1">
        Usporedba medu datotekama
      </h3>
      <p className="text-xs text-muted mb-4">
        Pronadeno {report.findings.length} nekonzistentnost{report.findings.length > 1 ? "i" : ""} analizom visestrukih datoteka
      </p>

      <div className="space-y-3">
        {report.findings.map((finding, idx) => {
          const riskColor = finding.riskScore >= 0.75 ? "border-l-red-500 bg-red-500/5" :
            finding.riskScore >= 0.50 ? "border-l-orange-500 bg-orange-500/5" :
            finding.riskScore >= 0.25 ? "border-l-amber-500 bg-amber-500/5" :
            "border-l-blue-500 bg-blue-500/5";

          const iconPath = Object.entries(FINDING_ICONS).find(([key]) => finding.code.startsWith(key))?.[1]
            || "M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z";

          const label = Object.entries(FINDING_LABELS).find(([key]) => finding.code.startsWith(key))?.[1]
            || finding.title;

          const affectedFileNames = finding.affectedFiles
            .map((i) => files[i]?.fileName)
            .filter(Boolean);

          return (
            <div key={idx} className={cn("border-l-4 rounded-lg p-3 sm:p-4", riskColor)}>
              <div className="flex items-start gap-3">
                <svg className="w-5 h-5 text-muted flex-shrink-0 mt-0.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d={iconPath} />
                </svg>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 mb-1">
                    <span className="text-sm font-medium">{label}</span>
                    <span className="text-[10px] px-1.5 py-0.5 rounded bg-card border border-border text-muted">{finding.code}</span>
                  </div>
                  <p className="text-xs text-muted">{finding.description}</p>
                  {affectedFileNames.length > 0 && (
                    <div className="flex flex-wrap gap-1 mt-2">
                      {affectedFileNames.map((name, i) => (
                        <span key={i} className="text-[10px] px-1.5 py-0.5 rounded bg-card border border-border text-muted truncate max-w-[120px]">
                          {name}
                        </span>
                      ))}
                    </div>
                  )}
                </div>
                <span className={cn(
                  "text-xs font-semibold flex-shrink-0",
                  finding.riskScore >= 0.75 ? "text-red-500" :
                  finding.riskScore >= 0.50 ? "text-orange-500" :
                  finding.riskScore >= 0.25 ? "text-amber-500" : "text-blue-500"
                )}>
                  {Math.round(finding.riskScore * 100)}%
                </span>
              </div>
            </div>
          );
        })}
      </div>

      {report.groupRiskModifier > 0 && (
        <div className="mt-4 p-3 bg-amber-500/10 border border-amber-500/20 rounded-lg">
          <p className="text-xs text-amber-600 dark:text-amber-400">
            Skupna usporedba povecala ukupni rizik za +{Math.round(report.groupRiskModifier * 100)} postotnih bodova
          </p>
        </div>
      )}
    </div>
  );
}
