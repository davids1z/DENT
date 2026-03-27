"use client";

import { useState } from "react";
import {
  type Inspection,
  formatDate,
  getReportUrl,
  getCertificateUrl,
  custodyEventLabel,
} from "@/lib/api";
import { GlassPanel } from "@/components/ui/GlassPanel";
import { cn } from "@/lib/cn";

interface Props {
  inspection: Inspection;
}

export function EvidenceIntegrity({ inspection }: Props) {
  const [showHashes, setShowHashes] = useState(false);
  const [showCustody, setShowCustody] = useState(false);

  const hasEvidence = !!inspection.evidenceHash;
  if (!hasEvidence) return null;

  const sealed = inspection.hasTimestamp;

  return (
    <GlassPanel className="space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <svg className="w-5 h-5 text-blue-600" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 15v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2zm10-10V7a4 4 0 00-8 0v4h8z" />
          </svg>
          <h3 className="font-heading font-semibold text-lg">Integritet dokaza</h3>
        </div>
        <span className={cn(
          "px-3 py-1 rounded-full text-xs font-medium",
          sealed
            ? "bg-green-500/15 text-green-600 dark:text-green-400 border border-green-500/30"
            : "bg-amber-500/15 text-amber-600 dark:text-amber-400 border border-amber-500/30"
        )}>
          {sealed ? "Zapečaćeno" : "Bez pečata"}
        </span>
      </div>

      {/* Evidence hash */}
      <div>
        <div className="text-xs text-muted mb-1">Kombinirani hash dokaza (SHA-256)</div>
        <code className="block text-xs font-mono bg-black/5 dark:bg-white/5 rounded px-3 py-2 break-all select-all">
          {inspection.evidenceHash}
        </code>
      </div>

      {/* RFC 3161 Timestamp */}
      {sealed && inspection.timestampedAt && (
        <div className="rounded-lg bg-green-500/10 border border-green-500/20 p-3">
          <div className="flex items-center gap-2 mb-1">
            <svg className="w-4 h-4 text-green-600" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z" />
            </svg>
            <span className="text-sm font-medium text-green-600 dark:text-green-400">RFC 3161 kvalificirani vremenski pečat</span>
          </div>
          <div className="text-xs text-green-600 dark:text-green-500 space-y-0.5">
            <div>Vrijeme: {formatDate(inspection.timestampedAt)}</div>
            <div>TSA: {inspection.timestampAuthority}</div>
          </div>
        </div>
      )}

      {/* Image hashes (expandable) */}
      {inspection.imageHashes && inspection.imageHashes.length > 0 && (
        <div>
          <button
            onClick={() => setShowHashes(!showHashes)}
            className="flex items-center gap-1.5 text-sm text-muted hover:text-foreground transition-colors"
          >
            <svg className={cn("w-3.5 h-3.5 transition-transform", showHashes && "rotate-90")} fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
            </svg>
            Hash-evi slika ({inspection.imageHashes.length})
          </button>
          {showHashes && (
            <div className="mt-2 space-y-1.5">
              {inspection.imageHashes.map((h, i) => (
                <div key={i} className="flex items-start gap-2 text-xs">
                  <span className="text-muted whitespace-nowrap">{h.fileName}:</span>
                  <code className="font-mono text-[10px] break-all select-all">{h.sha256}</code>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Forensic + Agent hashes */}
      {(inspection.forensicResultHash || inspection.agentDecisionHash) && (
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 text-xs">
          {inspection.forensicResultHash && (
            <div>
              <div className="text-muted mb-0.5">Hash forenzike</div>
              <code className="font-mono text-[10px] break-all select-all">{inspection.forensicResultHash}</code>
            </div>
          )}
          {inspection.agentDecisionHash && (
            <div>
              <div className="text-muted mb-0.5">Hash odluke agenta</div>
              <code className="font-mono text-[10px] break-all select-all">{inspection.agentDecisionHash}</code>
            </div>
          )}
        </div>
      )}

      {/* Chain of custody (expandable) */}
      {inspection.chainOfCustody && inspection.chainOfCustody.length > 0 && (
        <div>
          <button
            onClick={() => setShowCustody(!showCustody)}
            className="flex items-center gap-1.5 text-sm text-muted hover:text-foreground transition-colors"
          >
            <svg className={cn("w-3.5 h-3.5 transition-transform", showCustody && "rotate-90")} fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
            </svg>
            Lanac skrbništva ({inspection.chainOfCustody.length} događaja)
          </button>
          {showCustody && (
            <div className="mt-2 border-l-2 border-blue-200 dark:border-blue-800 pl-3 space-y-2">
              {inspection.chainOfCustody.map((evt, i) => (
                <div key={i} className="relative">
                  <div className="absolute -left-[17px] top-1.5 w-2 h-2 rounded-full bg-blue-400" />
                  <div className="text-xs">
                    <span className="font-medium">{custodyEventLabel(evt.event)}</span>
                    <span className="text-muted ml-2">{formatDate(evt.timestamp)}</span>
                  </div>
                  {evt.hash && (
                    <code className="text-[10px] font-mono text-muted break-all">{evt.hash}</code>
                  )}
                  {evt.details && (
                    <div className="text-[10px] text-muted">{evt.details}</div>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Download buttons */}
      <div className="flex flex-wrap gap-2 pt-2 border-t border-border">
        <a
          href={getReportUrl(inspection.id)}
          target="_blank"
          rel="noopener noreferrer"
          className="inline-flex items-center gap-1.5 px-4 py-2 bg-blue-600 text-white text-sm font-medium rounded-lg hover:bg-blue-700 transition-colors"
        >
          <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 10v6m0 0l-3-3m3 3l3-3m2 8H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
          </svg>
          Preuzmi PDF izvještaj
        </a>
        <a
          href={getCertificateUrl(inspection.id)}
          target="_blank"
          rel="noopener noreferrer"
          className="inline-flex items-center gap-1.5 px-4 py-2 bg-card border border-border text-foreground text-sm font-medium rounded-lg hover:bg-accent transition-colors"
        >
          <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10 20l4-16m4 4l4 4-4 4M6 16l-4-4 4-4" />
          </svg>
          Preuzmi XML certifikat
        </a>
      </div>
    </GlassPanel>
  );
}
