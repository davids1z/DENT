"use client";

import { useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import type { ForensicResult, ForensicModuleResult, ForensicFinding } from "@/lib/api";
import { fraudRiskColor } from "@/lib/api";
import {
  groupModulesIntoPillars,
  getPillarStatus,
  forensicModuleLabel,
  type PillarData,
} from "@/lib/forensicPillars";
import { cn } from "@/lib/cn";
import { hasBboxData, extractBboxes } from "@/lib/findingBbox";
import { FindingBboxOverlay } from "./FindingBboxOverlay";

// ── Icons ────────────────────────────────────────────────────────

function PillarIcon({ icon }: { icon: string }) {
  const cls = "w-4 h-4 text-muted-light";
  switch (icon) {
    case "lock":
      return (
        <svg className={cls} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M16.5 10.5V6.75a4.5 4.5 0 10-9 0v3.75m-.75 11.25h10.5a2.25 2.25 0 002.25-2.25v-6.75a2.25 2.25 0 00-2.25-2.25H6.75a2.25 2.25 0 00-2.25 2.25v6.75a2.25 2.25 0 002.25 2.25z" />
        </svg>
      );
    case "cpu":
      return (
        <svg className={cls} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M8.25 3v1.5M4.5 8.25H3m18 0h-1.5M4.5 12H3m18 0h-1.5M4.5 15.75H3m18 0h-1.5M8.25 19.5V21M12 3v1.5m0 15V21m3.75-18v1.5m0 15V21m-9-1.5h10.5a2.25 2.25 0 002.25-2.25V6.75a2.25 2.25 0 00-2.25-2.25H6.75A2.25 2.25 0 004.5 6.75v10.5a2.25 2.25 0 002.25 2.25z" />
        </svg>
      );
    case "sparkles":
      return (
        <svg className={cls} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M9.813 15.904L9 18.75l-.813-2.846a4.5 4.5 0 00-3.09-3.09L2.25 12l2.846-.813a4.5 4.5 0 003.09-3.09L9 5.25l.813 2.846a4.5 4.5 0 003.09 3.09L15.75 12l-2.846.813a4.5 4.5 0 00-3.09 3.09zM18.259 8.715L18 9.75l-.259-1.035a3.375 3.375 0 00-2.455-2.456L14.25 6l1.036-.259a3.375 3.375 0 002.455-2.456L18 2.25l.259 1.035a3.375 3.375 0 002.455 2.456L21.75 6l-1.036.259a3.375 3.375 0 00-2.455 2.456zM16.894 20.567L16.5 21.75l-.394-1.183a2.25 2.25 0 00-1.423-1.423L13.5 18.75l1.183-.394a2.25 2.25 0 001.423-1.423l.394-1.183.394 1.183a2.25 2.25 0 001.423 1.423l1.183.394-1.183.394a2.25 2.25 0 00-1.423 1.423z" />
        </svg>
      );
    case "pencil":
      return (
        <svg className={cls} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M16.862 4.487l1.687-1.688a1.875 1.875 0 112.652 2.652L10.582 16.07a4.5 4.5 0 01-1.897 1.13L6 18l.8-2.685a4.5 4.5 0 011.13-1.897l8.932-8.931zm0 0L19.5 7.125M18 14v4.75A2.25 2.25 0 0115.75 21H5.25A2.25 2.25 0 013 18.75V8.25A2.25 2.25 0 015.25 6H10" />
        </svg>
      );
    case "signal":
      return (
        <svg className={cls} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M3 4.5h14.25M3 9h9.75M3 13.5h9.75m4.5-4.5v12m0 0l-3.75-3.75M17.25 21L21 17.25" />
        </svg>
      );
    case "brain":
      return (
        <svg className={cls} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M2.036 12.322a1.012 1.012 0 010-.639C3.423 7.51 7.36 4.5 12 4.5c4.638 0 8.573 3.007 9.963 7.178.07.207.07.431 0 .639C20.577 16.49 16.64 19.5 12 19.5c-4.638 0-8.573-3.007-9.963-7.178z" />
          <path strokeLinecap="round" strokeLinejoin="round" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
        </svg>
      );
    case "file":
      return (
        <svg className={cls} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M19.5 14.25v-2.625a3.375 3.375 0 00-3.375-3.375h-1.5A1.125 1.125 0 0113.5 7.125v-1.5a3.375 3.375 0 00-3.375-3.375H8.25m2.25 0H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 00-9-9z" />
        </svg>
      );
    default:
      return null;
  }
}

// ── Utility ──────────────────────────────────────────────────────

function riskLevelBg(level: string): string {
  switch (level) {
    case "Low": return "bg-green-500";
    case "Medium": return "bg-amber-500";
    case "High": return "bg-orange-500";
    case "Critical": return "bg-red-500";
    default: return "bg-muted-light";
  }
}

function statusDotColor(status: "pass" | "warning" | "fail"): string {
  if (status === "fail") return "bg-red-500";
  if (status === "warning") return "bg-amber-400";
  return "bg-green-500";
}

function statusLabel(status: "pass" | "warning" | "fail"): { text: string; cls: string } {
  if (status === "fail") return { text: "Kritično", cls: "text-red-600 dark:text-red-400 bg-red-500/10 border-red-500/20" };
  if (status === "warning") return { text: "Sumnjivo", cls: "text-amber-600 dark:text-amber-400 bg-amber-500/10 border-amber-500/20" };
  return { text: "Čisto", cls: "text-green-600 dark:text-green-400 bg-green-500/10 border-green-500/20" };
}

// ── Module Row ───────────────────────────────────────────────────

function ModuleRow({ module: mod, pagePreviewUrls }: { module: ForensicModuleResult; pagePreviewUrls?: string[] | null }) {
  const [open, setOpen] = useState(false);
  const [bboxOverlay, setBboxOverlay] = useState<{ finding: ForensicFinding; pageIdx: number } | null>(null);
  const riskPct = mod.riskScore100;

  return (
    <div className="rounded-lg border border-border bg-background">
      <button
        onClick={() => setOpen(!open)}
        className="w-full flex items-center gap-3 px-3 py-2 text-left hover:bg-card transition-colors"
      >
        <span className="text-xs font-medium flex-1 truncate text-foreground">
          {forensicModuleLabel(mod.moduleName)}
        </span>
        {mod.error && (
          <span className="text-[10px] px-1.5 py-0.5 bg-red-500/10 text-red-500 rounded border border-red-500/20">Greška</span>
        )}
        <div className="w-16 h-1.5 bg-card-hover rounded-full overflow-hidden flex-shrink-0">
          <div
            className={cn("h-full rounded-full", riskLevelBg(mod.riskLevel))}
            style={{ width: `${riskPct}%` }}
          />
        </div>
        <span className={cn("text-xs font-mono w-8 text-right", fraudRiskColor(mod.riskLevel))}>
          {riskPct}%
        </span>
        <svg
          className={cn("w-3 h-3 text-muted-light transition-transform flex-shrink-0", open && "rotate-180")}
          fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}
        >
          <path strokeLinecap="round" strokeLinejoin="round" d="M19.5 8.25l-7.5 7.5-7.5-7.5" />
        </svg>
      </button>

      <AnimatePresence initial={false}>
        {open && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.15 }}
            className="overflow-hidden"
          >
            <div className="px-3 pb-2.5 pt-1.5 border-t border-border space-y-1.5">
              {mod.findings.length > 0 ? (
                mod.findings.map((f, j) => {
                  const bboxPages = hasBboxData(f) ? extractBboxes(f) : [];
                  return (
                    <div key={j} className="flex items-start gap-2 py-1">
                      <div
                        className={cn(
                          "w-1.5 h-1.5 rounded-full flex-shrink-0 mt-1.5",
                          f.riskScore >= 0.5 ? "bg-red-500" : f.riskScore >= 0.25 ? "bg-amber-400" : "bg-green-500"
                        )}
                      />
                      <div className="flex-1 min-w-0">
                        <span className="text-[11px] text-foreground block">{f.title}</span>
                        {f.description && (
                          <span className="text-[10px] text-muted-light block">{f.description}</span>
                        )}
                        {/* Bbox page buttons */}
                        {bboxPages.length > 0 && pagePreviewUrls && pagePreviewUrls.length > 0 && (
                          <div className="flex flex-wrap gap-1 mt-1">
                            {bboxPages.map((bp, i) => (
                              <button
                                key={i}
                                onClick={() => setBboxOverlay({ finding: f, pageIdx: bp.page - 1 })}
                                className="inline-flex items-center gap-0.5 px-1.5 py-0.5 text-[9px] font-medium rounded bg-red-500/10 text-red-600 dark:text-red-400 border border-red-500/20 hover:bg-red-500/20 transition-colors"
                              >
                                <svg className="w-2.5 h-2.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                                  <path strokeLinecap="round" strokeLinejoin="round" d="M15 10.5a3 3 0 11-6 0 3 3 0 016 0z" />
                                  <path strokeLinecap="round" strokeLinejoin="round" d="M19.5 10.5c0 7.142-7.5 11.25-7.5 11.25S4.5 17.642 4.5 10.5a7.5 7.5 0 1115 0z" />
                                </svg>
                                Str. {bp.page}
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
              ) : (
                <p className="text-[10px] text-muted-light py-1">
                  Nije utvrđena anomalija ovim modulom.
                </p>
              )}
              <div className="text-[10px] text-muted-light pt-1 border-t border-border/50">
                Vrijeme obrade: {(mod.processingTimeMs / 1000).toFixed(2)}s
              </div>
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      {/* Bbox overlay lightbox */}
      {bboxOverlay && pagePreviewUrls && pagePreviewUrls[bboxOverlay.pageIdx] && (() => {
        const allBboxes = extractBboxes(bboxOverlay.finding);
        const pageBbox = allBboxes.find(b => b.page === bboxOverlay.pageIdx + 1);
        if (!pageBbox) return null;
        return (
          <FindingBboxOverlay
            pagePreviewUrl={pagePreviewUrls[bboxOverlay.pageIdx]}
            bboxes={pageBbox.rects}
            label={pageBbox.label}
            pageNumber={pageBbox.page}
            onClose={() => setBboxOverlay(null)}
          />
        );
      })()}
    </div>
  );
}

// ── Heatmap Viewer ───────────────────────────────────────────────

function HeatmapViewer({
  originalImageUrl,
  heatmapUrl,
  fftSpectrumUrl,
}: {
  originalImageUrl: string;
  heatmapUrl: string | null;
  fftSpectrumUrl: string | null;
}) {
  const [visible, setVisible] = useState(false);
  const [opacity, setOpacity] = useState(60);
  const [tab, setTab] = useState<"spectral" | "fft">("spectral");

  const hasTabs = heatmapUrl && fftSpectrumUrl;
  const activeUrl = hasTabs
    ? tab === "spectral" ? heatmapUrl : fftSpectrumUrl
    : heatmapUrl || fftSpectrumUrl;

  return (
    <div className="border-t border-border pt-3 mt-2">
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-2">
          {hasTabs && (
            <div className="flex rounded-md border border-border overflow-hidden">
              <button
                onClick={() => setTab("spectral")}
                className={cn(
                  "px-2 py-0.5 text-[10px] font-medium transition-colors",
                  tab === "spectral" ? "bg-accent text-white" : "bg-background text-muted-light hover:bg-card"
                )}
              >
                Heatmap
              </button>
              <button
                onClick={() => setTab("fft")}
                className={cn(
                  "px-2 py-0.5 text-[10px] font-medium transition-colors",
                  tab === "fft" ? "bg-accent text-white" : "bg-background text-muted-light hover:bg-card"
                )}
              >
                FFT
              </button>
            </div>
          )}
          <button
            onClick={() => setVisible(!visible)}
            className={cn(
              "text-[11px] font-medium px-2.5 py-1 rounded-md transition-colors",
              visible ? "bg-accent text-white" : "bg-card-hover text-muted hover:bg-card-hover"
            )}
          >
            {visible ? "Sakrij" : "Prikaži toplinski prikaz"}
          </button>
        </div>
        {visible && (
          <div className="flex items-center gap-1.5">
            <span className="text-[10px] text-muted-light">{opacity}%</span>
            <input
              type="range"
              min={10}
              max={100}
              value={opacity}
              onChange={(e) => setOpacity(Number(e.target.value))}
              className="w-16 h-1 accent-accent"
            />
          </div>
        )}
      </div>

      {visible && activeUrl && (
        <div className="relative rounded-lg overflow-hidden bg-background" style={{ maxHeight: 240 }}>
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src={originalImageUrl} alt="Original" className="w-full object-contain" style={{ maxHeight: 240 }} />
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            src={activeUrl}
            alt="Heatmap"
            className="absolute inset-0 w-full h-full object-contain"
            style={{ opacity: opacity / 100, mixBlendMode: "screen" }}
          />
        </div>
      )}
    </div>
  );
}

// ── Pillar Section ───────────────────────────────────────────────

function PillarSection({ data, originalImageUrl, pagePreviewUrls }: { data: PillarData; originalImageUrl: string; pagePreviewUrls?: string[] | null }) {
  const [expanded, setExpanded] = useState(false);
  const status = getPillarStatus(data.aggregateRiskScore);
  const riskPct = Math.round(data.aggregateRiskScore * 100);
  const moduleCount = data.modules.length;
  const sl = statusLabel(status);

  return (
    <div>
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full px-3 sm:px-5 py-3 sm:py-3.5 text-left hover:bg-card/50 transition-colors"
      >
        {/* Row 1: dot + icon + name + chevron */}
        <div className="flex items-center gap-2 sm:gap-3">
          <div className={cn("w-2 h-2 rounded-full flex-shrink-0", statusDotColor(status))} />
          <PillarIcon icon={data.pillar.icon} />
          <div className="flex-1 min-w-0">
            <span className="text-sm font-medium text-foreground block truncate">{data.pillar.label}</span>
            <span className="text-[11px] text-muted-light block truncate hidden sm:block">{data.modules.length} {data.modules.length === 1 ? "modul" : "modula"}: {data.modules.map(m => {
              const label = forensicModuleLabel(m.moduleName);
              // Shorten: remove "AI detekcija", "detekcija", "(CVPR 2025)" etc.
              return label.replace(/ AI detekcija| detekcija| \(.*?\)| manipulacije| analiza/g, "").trim();
            }).join(", ")}</span>
          </div>
          {/* Desktop: all inline */}
          <div className="hidden sm:flex items-center gap-2 flex-shrink-0">
            <div className="w-20 flex items-center gap-2">
              <div className="flex-1 h-1.5 bg-card-hover rounded-full overflow-hidden">
                <div className={cn("h-full rounded-full", statusDotColor(status))} style={{ width: `${riskPct}%` }} />
              </div>
              <span className={cn("text-xs font-mono w-8 text-right", status === "fail" ? "text-red-500" : status === "warning" ? "text-amber-500" : "text-green-500")}>{riskPct}%</span>
            </div>
            <span className="text-[10px] bg-card-hover text-muted px-2 py-0.5 rounded-full">{moduleCount} analiza</span>
            <span className={cn("text-[10px] font-medium px-2 py-0.5 rounded-full border w-16 text-center", sl.cls)}>{sl.text}</span>
          </div>
          <svg className={cn("w-4 h-4 text-muted-light transition-transform flex-shrink-0", expanded && "rotate-180")} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M19.5 8.25l-7.5 7.5-7.5-7.5" />
          </svg>
        </div>
        {/* Row 2 (mobile only): risk bar + badge */}
        <div className="flex sm:hidden items-center gap-2 mt-1.5 ml-[26px]">
          <div className="flex-1 h-1.5 bg-card-hover rounded-full overflow-hidden">
            <div className={cn("h-full rounded-full", statusDotColor(status))} style={{ width: `${riskPct}%` }} />
          </div>
          <span className={cn("text-xs font-mono w-8 text-right flex-shrink-0", fraudRiskColor(data.aggregateRiskLevel))}>{riskPct}%</span>
          {moduleCount > 0 && (
            <span className="text-[10px] bg-card-hover text-muted px-1.5 py-0.5 rounded-full flex-shrink-0">{moduleCount} analiza</span>
          )}
          <span className={cn("text-[10px] font-medium px-2 py-0.5 rounded-full border flex-shrink-0", sl.cls)}>{sl.text}</span>
        </div>
      </button>

      <AnimatePresence initial={false}>
        {expanded && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.2 }}
            className="overflow-hidden"
          >
            <div className="px-5 pb-4 space-y-2 bg-card/30">
              {data.modules.map((mod) => (
                <ModuleRow key={mod.moduleName} module={mod} pagePreviewUrls={pagePreviewUrls} />
              ))}
              {(data.heatmapUrl || data.fftSpectrumUrl) && (
                <HeatmapViewer
                  originalImageUrl={originalImageUrl}
                  heatmapUrl={data.heatmapUrl}
                  fftSpectrumUrl={data.fftSpectrumUrl}
                />
              )}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

// ── Main Component ───────────────────────────────────────────────

interface ForensicModuleTableProps {
  result: ForensicResult;
  originalImageUrl: string;
  pagePreviewUrls?: string[] | null;
}

export function ForensicModuleTable({ result, originalImageUrl, pagePreviewUrls }: ForensicModuleTableProps) {
  const pillars = groupModulesIntoPillars(result.modules, result);
  if (pillars.length === 0) return null;

  // Find modules not assigned to any pillar
  const assignedModules = new Set(pillars.flatMap(p => p.modules.map(m => m.moduleName)));
  const unassigned = result.modules.filter(m => !assignedModules.has(m.moduleName) && !m.error);

  // Consensus: count high/low modules
  const allModules = result.modules.filter(m => !m.error);
  const highModules = allModules.filter(m => m.riskScore >= 0.40);
  const lowModules = allModules.filter(m => m.riskScore < 0.20);
  const totalTime = allModules.reduce((s, m) => s + m.processingTimeMs, 0);

  return (
    <div>
      <h2 className="font-heading text-lg font-semibold mb-4">
        Forenzički moduli ({pillars.length})
      </h2>
      <div className="bg-background rounded-2xl border border-border shadow-sm overflow-hidden divide-y divide-border">
        {pillars.map((p) => (
          <PillarSection key={p.pillar.id} data={p} originalImageUrl={originalImageUrl} pagePreviewUrls={pagePreviewUrls} />
        ))}
      </div>

      {/* Unassigned modules (if any exist outside pillar groups) */}
      {unassigned.length > 0 && (
        <div className="mt-4">
          <h3 className="text-xs font-medium text-muted uppercase tracking-wider mb-2">Ostali moduli ({unassigned.length})</h3>
          <div className="bg-background rounded-xl border border-border shadow-sm overflow-hidden">
            <div className="px-5 py-3 space-y-2">
              {unassigned.map((mod) => (
                <ModuleRow key={mod.moduleName} module={mod} pagePreviewUrls={pagePreviewUrls} />
              ))}
            </div>
          </div>
        </div>
      )}

      {/* Consensus summary */}
      <div className="mt-4 p-4 bg-card border border-border rounded-xl">
        <h3 className="text-xs font-medium text-muted uppercase tracking-wider mb-2">Konsenzus modula</h3>
        <p className="text-sm text-foreground">
          {allModules.length} modula analizirano u {(totalTime / 1000).toFixed(2)}s.
          {highModules.length > 0 && (
            <> <span className="font-medium">{highModules.length}</span> {highModules.length === 1 ? "modul je prijavio" : "modula su prijavila"} povišen rizik
            ({highModules.map(m => forensicModuleLabel(m.moduleName)).join(", ")}).</>
          )}
          {highModules.length === 0 && lowModules.length === allModules.length && (
            <> Svi moduli potvrđuju nizak rizik.</>
          )}
          {highModules.length === 0 && lowModules.length < allModules.length && (
            <> Niti jedan modul nije prijavio značajan rizik, ali {allModules.length - lowModules.length} {allModules.length - lowModules.length === 1 ? "modul pokazuje" : "modula pokazuju"} umjerenu aktivnost.</>
          )}
        </p>
        <p className="text-xs text-muted mt-1">
          Završni rezultat: {result.overallRiskScore100}% ({result.overallRiskLevel})
        </p>
      </div>
    </div>
  );
}
