"use client";

import { getReportUrl } from "@/lib/api";

interface ExportButtonProps {
  inspectionId: string;
}

export function ExportButton({ inspectionId }: ExportButtonProps) {
  return (
    <a
      href={getReportUrl(inspectionId)}
      target="_blank"
      rel="noopener noreferrer"
      className="inline-flex items-center gap-2 px-4 py-2 bg-accent-solid text-white rounded-lg text-sm font-medium hover:bg-accent-hover transition-colors"
    >
      <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
        <path strokeLinecap="round" strokeLinejoin="round" d="M3 16.5v2.25A2.25 2.25 0 005.25 21h13.5A2.25 2.25 0 0021 18.75V16.5M16.5 12L12 16.5m0 0L7.5 12m4.5 4.5V3" />
      </svg>
      Preuzmi forenzicki izvjestaj
    </a>
  );
}
