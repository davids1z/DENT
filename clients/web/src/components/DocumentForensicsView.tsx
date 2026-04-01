"use client";

import { useState, useMemo } from "react";
import type { ForensicResult, ForensicFinding } from "@/lib/api";
import { groupDocumentFindings, extractToolAttribution, getDocumentRiskScore, type FindingCategory } from "@/lib/documentFindings";
import { extractBboxes, hasBboxData } from "@/lib/findingBbox";
import { DocumentPageViewer } from "./DocumentPageViewer";
import { FindingBboxOverlay } from "./FindingBboxOverlay";
import { cn } from "@/lib/cn";

interface DocumentForensicsViewProps {
  forensicResult: ForensicResult;
  pagePreviewUrls: string[];
  fileName: string;
}

export function DocumentForensicsView({ forensicResult, pagePreviewUrls, fileName }: DocumentForensicsViewProps) {
  const [activePage, setActivePage] = useState(0);
  const [expandedCategory, setExpandedCategory] = useState<string | null>(null);
  const [lightboxFinding, setLightboxFinding] = useState<ForensicFinding | null>(null);

  const categories = useMemo(() => groupDocumentFindings(forensicResult.modules), [forensicResult.modules]);
  const toolAttribution = useMemo(() => extractToolAttribution(forensicResult.modules), [forensicResult.modules]);
  const { score: riskScore, level: riskLevel } = useMemo(() => getDocumentRiskScore(forensicResult.modules), [forensicResult.modules]);
  const riskPct = Math.round(riskScore * 100);

  const totalFindings = categories.reduce((s, c) => s + c.findings.length, 0);
  const highRiskFindings = categories.reduce((s, c) => s + c.findings.filter(f => f.riskScore >= 0.50).length, 0);

  // Find currently active bboxes based on expanded category's findings
  const activeBboxes = useMemo(() => {
    if (!expandedCategory) return undefined;
    const cat = categories.find(c => c.id === expandedCategory);
    if (!cat) return undefined;
    return cat.findings
      .filter(f => hasBboxData(f))
      .flatMap(f => extractBboxes(f))
      .filter(bp => bp.page === activePage + 1)
      .map(bp => ({ rects: bp.rects, label: bp.label }));
  }, [expandedCategory, categories, activePage]);

  // Extract diff heatmap from version diff findings
  const diffHeatmapB64 = useMemo(() => {
    for (const mod of forensicResult.modules) {
      for (const f of mod.findings) {
        if (f.code?.startsWith("DOC_VERSION_") && f.evidence) {
          const ev = f.evidence as Record<string, unknown>;
          if (ev.diff_heatmap_b64) return String(ev.diff_heatmap_b64);
        }
      }
    }
    return null;
  }, [forensicResult.modules]);

  // Extract metadata summary
  const metadataSummary = useMemo(() => {
    const items: { label: string; value: string }[] = [];
    for (const mod of forensicResult.modules) {
      if (mod.moduleName !== "document_forensics") continue;
      for (const f of mod.findings) {
        const ev = f.evidence as Record<string, unknown> | null;
        if (!ev) continue;
        if (ev.creation_date) items.push({ label: "Datum kreiranja", value: String(ev.creation_date) });
        if (ev.mod_date) items.push({ label: "Datum izmjene", value: String(ev.mod_date) });
        if (ev.producer) items.push({ label: "Producer", value: String(ev.producer) });
        if (ev.creator) items.push({ label: "Creator", value: String(ev.creator) });
        if (ev.author) items.push({ label: "Autor", value: String(ev.author) });
        if (ev.eof_count) items.push({ label: "Revizije (%%EOF)", value: String(ev.eof_count) });
        if (ev.signer_name) items.push({ label: "Potpisnik", value: String(ev.signer_name) });
        if (ev.cert_issuer) items.push({ label: "Izdavač certifikata", value: String(ev.cert_issuer) });
      }
    }
    // Deduplicate by label
    const seen = new Set<string>();
    return items.filter(i => { if (seen.has(i.label)) return false; seen.add(i.label); return true; });
  }, [forensicResult.modules]);

  // Verdict
  const verdictColor = riskPct >= 50 ? "red" : riskPct >= 15 ? "amber" : "green";
  const verdictLabel = riskPct >= 50 ? "Sumnjiv dokument" : riskPct >= 15 ? "Potrebna provjera" : "Autentičan dokument";
  const verdictBg = verdictColor === "red" ? "bg-red-500/10 border-red-500/20 text-red-600 dark:text-red-400"
    : verdictColor === "amber" ? "bg-amber-500/10 border-amber-500/20 text-amber-600 dark:text-amber-400"
    : "bg-green-500/10 border-green-500/20 text-green-600 dark:text-green-400";

  function handleFindingClick(finding: ForensicFinding) {
    if (!hasBboxData(finding)) return;
    const bboxes = extractBboxes(finding);
    if (bboxes.length > 0) {
      // Jump to the first page with bbox
      setActivePage(bboxes[0].page - 1);
      // If page preview available, open lightbox
      if (pagePreviewUrls[bboxes[0].page - 1]) {
        setLightboxFinding(finding);
      }
    }
  }

  return (
    <div className="space-y-4">
      {/* Verdict Banner */}
      <div className={cn("flex items-center gap-3 p-3 rounded-xl border", verdictBg)}>
        <div className="flex items-center gap-2 flex-1 min-w-0">
          {verdictColor === "green" && (
            <svg className="w-5 h-5 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M9 12.75L11.25 15 15 9.75M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
            </svg>
          )}
          {verdictColor !== "green" && (
            <svg className="w-5 h-5 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v3.75m-9.303 3.376c-.866 1.5.217 3.374 1.948 3.374h14.71c1.73 0 2.813-1.874 1.948-3.374L13.949 3.378c-.866-1.5-3.032-1.5-3.898 0L2.697 16.126zM12 15.75h.007v.008H12v-.008z" />
            </svg>
          )}
          <div>
            <span className="text-sm font-semibold block">{verdictLabel}</span>
            <span className="text-[11px] opacity-75">
              {totalFindings} nalaza · {highRiskFindings > 0 ? `${highRiskFindings} visokorizičnih` : "bez visokorizičnih"}
            </span>
          </div>
        </div>
        <div className="flex items-center gap-2 flex-shrink-0">
          {toolAttribution && (
            <span className="text-[10px] px-2 py-0.5 rounded-full bg-amber-500/15 border border-amber-500/25 text-amber-600 dark:text-amber-400 font-medium">
              Editirano u: {toolAttribution}
            </span>
          )}
          <span className="text-xs font-mono font-bold">{riskPct}%</span>
        </div>
      </div>

      {/* Split layout */}
      <div className="flex flex-col lg:flex-row gap-4">
        {/* Left: Document Page Viewer */}
        <div className="lg:w-[60%] bg-background border border-border rounded-xl overflow-hidden" style={{ minHeight: 400 }}>
          {pagePreviewUrls.length > 0 ? (
            <DocumentPageViewer
              pagePreviewUrls={pagePreviewUrls}
              activeBboxes={activeBboxes}
              activePage={activePage}
              onPageChange={setActivePage}
              diffHeatmapB64={diffHeatmapB64}
              metadataSummary={metadataSummary}
            />
          ) : (
            <div className="flex items-center justify-center h-64 text-muted text-sm">
              <div className="text-center">
                <svg className="w-10 h-10 mx-auto mb-2 text-muted/30" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M19.5 14.25v-2.625a3.375 3.375 0 00-3.375-3.375h-1.5A1.125 1.125 0 0113.5 7.125v-1.5a3.375 3.375 0 00-3.375-3.375H8.25m2.25 0H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 00-9-9z" />
                </svg>
                Pregled stranica nije dostupan
              </div>
            </div>
          )}
        </div>

        {/* Right: Findings Sidebar */}
        <div className="lg:w-[40%] space-y-2">
          {/* Overall score */}
          <div className="bg-background border border-border rounded-xl p-3">
            <div className="flex items-center justify-between mb-2">
              <span className="text-xs font-medium text-muted uppercase tracking-wider">Forenzički rizik</span>
              <span className={cn("text-sm font-mono font-bold",
                riskPct >= 50 ? "text-red-500" : riskPct >= 15 ? "text-amber-500" : "text-green-500"
              )}>{riskPct}%</span>
            </div>
            <div className="h-2 bg-border/40 rounded-full overflow-hidden">
              <div
                className={cn("h-full rounded-full transition-all duration-500",
                  riskPct >= 50 ? "bg-red-500" : riskPct >= 15 ? "bg-amber-500" : "bg-green-500"
                )}
                style={{ width: `${riskPct}%` }}
              />
            </div>
            <div className="flex items-center justify-between mt-1.5">
              <span className="text-[10px] text-muted">{fileName}</span>
              <span className="text-[10px] text-muted">{forensicResult.totalProcessingTimeMs ? `${(forensicResult.totalProcessingTimeMs / 1000).toFixed(1)}s` : ""}</span>
            </div>
          </div>

          {/* Finding categories */}
          {categories.length > 0 ? (
            <div className="bg-background border border-border rounded-xl overflow-hidden divide-y divide-border">
              {categories.map(cat => (
                <CategoryRow
                  key={cat.id}
                  category={cat}
                  isExpanded={expandedCategory === cat.id}
                  onToggle={() => setExpandedCategory(expandedCategory === cat.id ? null : cat.id)}
                  onFindingClick={handleFindingClick}
                  hasPagePreviews={pagePreviewUrls.length > 0}
                />
              ))}
            </div>
          ) : (
            <div className="bg-background border border-border rounded-xl p-4 text-center text-sm text-muted">
              Nema forenzičkih nalaza za ovaj dokument
            </div>
          )}
        </div>
      </div>

      {/* Lightbox for bbox overlay */}
      {lightboxFinding && (() => {
        const bboxes = extractBboxes(lightboxFinding);
        const first = bboxes[0];
        if (!first || !pagePreviewUrls[first.page - 1]) return null;
        return (
          <FindingBboxOverlay
            pagePreviewUrl={pagePreviewUrls[first.page - 1]}
            bboxes={first.rects}
            label={first.label}
            pageNumber={first.page}
            onClose={() => setLightboxFinding(null)}
          />
        );
      })()}
    </div>
  );
}

// ── Category Row ──

function CategoryRow({
  category,
  isExpanded,
  onToggle,
  onFindingClick,
  hasPagePreviews,
}: {
  category: FindingCategory;
  isExpanded: boolean;
  onToggle: () => void;
  onFindingClick: (f: ForensicFinding) => void;
  hasPagePreviews: boolean;
}) {
  const count = category.findings.length;
  const dotColor = category.maxRisk >= 0.50 ? "bg-red-500" : category.maxRisk >= 0.25 ? "bg-amber-400" : count > 0 ? "bg-blue-400" : "bg-green-500";

  return (
    <div>
      <button
        onClick={onToggle}
        className="w-full flex items-center gap-2.5 px-3 py-2.5 text-left hover:bg-card/50 transition-colors"
      >
        <div className={cn("w-2 h-2 rounded-full flex-shrink-0", dotColor)} />
        <CategoryIcon icon={category.icon} />
        <span className="text-xs font-medium text-foreground flex-1">{category.label}</span>
        {count > 0 && (
          <span className="text-[10px] bg-card-hover text-muted px-1.5 py-0.5 rounded-full">{count}</span>
        )}
        {count === 0 && (
          <span className="text-[10px] text-green-500">✓</span>
        )}
        <svg className={cn("w-3 h-3 text-muted transition-transform", isExpanded && "rotate-180")} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M19.5 8.25l-7.5 7.5-7.5-7.5" />
        </svg>
      </button>

      {isExpanded && (
        <div className="px-3 pb-2.5 space-y-1">
          {count === 0 ? (
            <p className="text-[10px] text-muted py-1 pl-4">Nije utvrđena anomalija.</p>
          ) : (
            category.findings.map((f, i) => {
              const hasBbox = hasPagePreviews && hasBboxData(f);
              const bboxPages = hasBbox ? extractBboxes(f) : [];
              return (
                <div key={i} className="flex items-start gap-2 py-1 pl-4">
                  <div className={cn("w-1.5 h-1.5 rounded-full flex-shrink-0 mt-1.5",
                    f.riskScore >= 0.5 ? "bg-red-500" : f.riskScore >= 0.25 ? "bg-amber-400" : "bg-blue-400"
                  )} />
                  <div className="flex-1 min-w-0">
                    <span className="text-[11px] text-foreground block">{f.title}</span>
                    {f.description && (
                      <span className="text-[10px] text-muted-light block line-clamp-2">{f.description}</span>
                    )}
                    {bboxPages.length > 0 && (
                      <div className="flex gap-1 mt-0.5">
                        {bboxPages.map((bp, j) => (
                          <button
                            key={j}
                            onClick={() => onFindingClick(f)}
                            className="inline-flex items-center gap-0.5 px-1.5 py-0.5 text-[9px] font-medium rounded bg-red-500/10 text-red-500 border border-red-500/20 hover:bg-red-500/20 transition-colors"
                          >
                            📍 Str. {bp.page}
                          </button>
                        ))}
                      </div>
                    )}
                  </div>
                  <span className="text-[10px] font-mono text-muted-light flex-shrink-0">
                    {Math.round(f.confidence * 100)}%
                  </span>
                </div>
              );
            })
          )}
        </div>
      )}
    </div>
  );
}

// ── Category Icons ──

function CategoryIcon({ icon }: { icon: string }) {
  const cls = "w-3.5 h-3.5 text-muted-light flex-shrink-0";
  switch (icon) {
    case "shield": return <svg className={cls} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}><path strokeLinecap="round" strokeLinejoin="round" d="M9 12.75L11.25 15 15 9.75m-3-7.036A11.959 11.959 0 013.598 6 11.99 11.99 0 003 9.749c0 5.592 3.824 10.29 9 11.623 5.176-1.332 9-6.03 9-11.622 0-1.31-.21-2.571-.598-3.751h-.152c-3.196 0-6.1-1.248-8.25-3.285z" /></svg>;
    case "alert": return <svg className={cls} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}><path strokeLinecap="round" strokeLinejoin="round" d="M12 9v3.75m-9.303 3.376c-.866 1.5.217 3.374 1.948 3.374h14.71c1.73 0 2.813-1.874 1.948-3.374L13.949 3.378c-.866-1.5-3.032-1.5-3.898 0L2.697 16.126zM12 15.75h.007v.008H12v-.008z" /></svg>;
    case "eye": return <svg className={cls} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}><path strokeLinecap="round" strokeLinejoin="round" d="M2.036 12.322a1.012 1.012 0 010-.639C3.423 7.51 7.36 4.5 12 4.5c4.638 0 8.573 3.007 9.963 7.178.07.207.07.431 0 .639C20.577 16.49 16.64 19.5 12 19.5c-4.638 0-8.573-3.007-9.963-7.178z" /><path strokeLinecap="round" strokeLinejoin="round" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" /></svg>;
    case "type": return <svg className={cls} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}><path strokeLinecap="round" strokeLinejoin="round" d="M7.5 8.25h9m-9 3H12m-9.75 1.51c0 1.6 1.123 2.994 2.707 3.227 1.129.166 2.27.293 3.423.379.35.026.67.21.865.501L12 21l2.755-4.133a1.14 1.14 0 01.865-.501 48.172 48.172 0 003.423-.379c1.584-.233 2.707-1.626 2.707-3.228V6.741c0-1.602-1.123-2.995-2.707-3.228A48.394 48.394 0 0012 3c-2.392 0-4.744.175-7.043.513C3.373 3.746 2.25 5.14 2.25 6.741v6.018z" /></svg>;
    case "layers": return <svg className={cls} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}><path strokeLinecap="round" strokeLinejoin="round" d="M6.429 9.75L2.25 12l4.179 2.25m0-4.5l5.571 3 5.571-3m-11.142 0L2.25 7.5 12 2.25l9.75 5.25-4.179 2.25m0 0L21.75 12l-4.179 2.25m0 0l4.179 2.25L12 21.75 2.25 16.5l4.179-2.25m11.142 0l-5.571 3-5.571-3" /></svg>;
    case "code": return <svg className={cls} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}><path strokeLinecap="round" strokeLinejoin="round" d="M17.25 6.75L22.5 12l-5.25 5.25m-10.5 0L1.5 12l5.25-5.25m7.5-3l-4.5 16.5" /></svg>;
    case "sparkles": return <svg className={cls} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}><path strokeLinecap="round" strokeLinejoin="round" d="M9.813 15.904L9 18.75l-.813-2.846a4.5 4.5 0 00-3.09-3.09L2.25 12l2.846-.813a4.5 4.5 0 003.09-3.09L9 5.25l.813 2.846a4.5 4.5 0 003.09 3.09L15.75 12l-2.846.813a4.5 4.5 0 00-3.09 3.09z" /></svg>;
    case "check": return <svg className={cls} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}><path strokeLinecap="round" strokeLinejoin="round" d="M9 12.75L11.25 15 15 9.75M21 12a9 9 0 11-18 0 9 9 0 0118 0z" /></svg>;
    default: return <svg className={cls} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}><path strokeLinecap="round" strokeLinejoin="round" d="M19.5 14.25v-2.625a3.375 3.375 0 00-3.375-3.375h-1.5A1.125 1.125 0 0113.5 7.125v-1.5a3.375 3.375 0 00-3.375-3.375H8.25m2.25 0H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 00-9-9z" /></svg>;
  }
}
