"use client";

import { useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import type { PillarData } from "@/lib/forensicPillars";
import { getPillarStatus, forensicModuleLabel } from "@/lib/forensicPillars";
import { fraudRiskColor, fraudRiskLabel } from "@/lib/api";
import { cn } from "@/lib/cn";

interface ForensicPillarCardProps {
  data: PillarData;
  originalImageUrl: string;
}

// ── Icons ──────────────────────────────────────────────────────

function PillarIcon({ icon }: { icon: string }) {
  const cls = "w-5 h-5";
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

function StatusBadge({ status }: { status: "pass" | "warning" | "fail" }) {
  if (status === "pass") {
    return (
      <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium bg-green-500/15 text-green-600 dark:text-green-400 border border-green-500/20">
        <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M4.5 12.75l6 6 9-13.5" />
        </svg>
        Prolazi
      </span>
    );
  }
  if (status === "warning") {
    return (
      <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium bg-amber-500/15 text-amber-600 dark:text-amber-400 border border-amber-500/20">
        <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v3.75m-9.303 3.376c-.866 1.5.217 3.374 1.948 3.374h14.71c1.73 0 2.813-1.874 1.948-3.374L13.949 3.378c-.866-1.5-3.032-1.5-3.898 0L2.697 16.126zM12 15.75h.007v.008H12v-.008z" />
        </svg>
        Sumnjivo
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium bg-red-500/15 text-red-600 dark:text-red-400 border border-red-500/20">
      <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
        <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
      </svg>
      Kriticno
    </span>
  );
}

// ── Main component ─────────────────────────────────────────────

export function ForensicPillarCard({ data, originalImageUrl }: ForensicPillarCardProps) {
  const [expanded, setExpanded] = useState(data.aggregateRiskScore >= 0.25);
  const [showHeatmap, setShowHeatmap] = useState(false);
  const [heatmapOpacity, setHeatmapOpacity] = useState(60);
  const [heatmapTab, setHeatmapTab] = useState<"spectral" | "fft">("spectral");

  const status = getPillarStatus(data.aggregateRiskScore);

  const borderColor =
    status === "fail" ? "border-red-500/20" : status === "warning" ? "border-amber-500/20" : "border-border";
  const headerBg =
    status === "fail" ? "bg-red-500/10" : status === "warning" ? "bg-amber-500/10" : "bg-card/50";

  return (
    <div className={cn("rounded-xl border overflow-hidden bg-card", borderColor)}>
      {/* Header */}
      <button
        onClick={() => setExpanded(!expanded)}
        className={cn("w-full px-3 sm:px-4 py-2.5 sm:py-3 text-left transition-colors hover:bg-card-hover", headerBg)}
      >
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2 sm:gap-2.5 min-w-0 flex-1">
            <div className={cn(
              "flex-shrink-0",
              status === "fail" ? "text-red-500" : status === "warning" ? "text-amber-500" : "text-green-600"
            )}>
              <PillarIcon icon={data.pillar.icon} />
            </div>
            <div className="min-w-0">
              <span className="text-sm font-semibold block truncate">{data.pillar.label}</span>
              <span className="text-[11px] text-muted block truncate hidden sm:block">{data.pillar.description}</span>
            </div>
          </div>
          <div className="flex items-center gap-1.5 sm:gap-2 flex-shrink-0 ml-2">
            <span className={cn("text-xs font-mono", fraudRiskColor(data.aggregateRiskLevel))}>
              {Math.round(data.aggregateRiskScore * 100)}%
            </span>
            <StatusBadge status={status} />
            <svg
              className={cn("w-4 h-4 text-muted transition-transform", expanded && "rotate-180")}
              fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}
            >
              <path strokeLinecap="round" strokeLinejoin="round" d="M19.5 8.25l-7.5 7.5-7.5-7.5" />
            </svg>
          </div>
        </div>
      </button>

      {/* Body */}
      <AnimatePresence initial={false}>
        {expanded && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.2 }}
            className="overflow-hidden"
          >
            <div className="px-3 sm:px-4 pb-3 space-y-2">
              {data.modules.map((mod) => (
                <ModuleRow key={mod.moduleName} module={mod} />
              ))}

              {/* Embedded heatmap */}
              {data.heatmapUrl && (
                <HeatmapSection
                  originalImageUrl={originalImageUrl}
                  heatmapUrl={data.heatmapUrl}
                  fftSpectrumUrl={data.fftSpectrumUrl}
                  showHeatmap={showHeatmap}
                  setShowHeatmap={setShowHeatmap}
                  opacity={heatmapOpacity}
                  setOpacity={setHeatmapOpacity}
                  activeTab={heatmapTab}
                  setActiveTab={setHeatmapTab}
                />
              )}
              {!data.heatmapUrl && data.fftSpectrumUrl && (
                <HeatmapSection
                  originalImageUrl={originalImageUrl}
                  heatmapUrl={null}
                  fftSpectrumUrl={data.fftSpectrumUrl}
                  showHeatmap={showHeatmap}
                  setShowHeatmap={setShowHeatmap}
                  opacity={heatmapOpacity}
                  setOpacity={setHeatmapOpacity}
                  activeTab={heatmapTab}
                  setActiveTab={setHeatmapTab}
                />
              )}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

// ── Module row ─────────────────────────────────────────────────

function ModuleRow({ module: mod }: { module: PillarData["modules"][number] }) {
  const [open, setOpen] = useState(false);
  const riskPct = Math.round(mod.riskScore * 100);
  const hasFindings = mod.findings.length > 0;

  return (
    <div className="rounded-lg border border-border bg-background/60 text-sm">
      <button
        onClick={() => setOpen(!open)}
        className="w-full flex items-center justify-between px-3 py-1.5 text-left"
      >
        <span className="font-medium text-xs truncate">{forensicModuleLabel(mod.moduleName)}</span>
        <div className="flex items-center gap-2 flex-shrink-0 ml-2">
          {mod.error && (
            <span className="text-[10px] px-1.5 py-0.5 bg-red-500/15 text-red-600 dark:text-red-400 rounded">Greska</span>
          )}
          <div className="w-12 h-1.5 bg-border rounded-full overflow-hidden">
            <div
              className={cn(
                "h-full rounded-full",
                mod.riskLevel === "Low" && "bg-green-500",
                mod.riskLevel === "Medium" && "bg-amber-500",
                mod.riskLevel === "High" && "bg-orange-500",
                mod.riskLevel === "Critical" && "bg-red-500",
              )}
              style={{ width: `${riskPct}%` }}
            />
          </div>
          <span className={cn("text-[11px] font-mono w-7 text-right", fraudRiskColor(mod.riskLevel))}>
            {riskPct}%
          </span>
          {hasFindings && (
            <svg
              className={cn("w-3 h-3 text-muted transition-transform", open && "rotate-180")}
              fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}
            >
              <path strokeLinecap="round" strokeLinejoin="round" d="M19.5 8.25l-7.5 7.5-7.5-7.5" />
            </svg>
          )}
        </div>
      </button>

      <AnimatePresence initial={false}>
        {open && hasFindings && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.15 }}
            className="overflow-hidden"
          >
            <div className="px-3 pb-2 space-y-1">
              {mod.findings.map((f, j) => (
                <FindingItem key={j} finding={f} />
              ))}
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      {!hasFindings && !mod.error && (
        <div className="px-3 pb-1.5">
          <span className="text-[11px] text-muted">Nema nalaza</span>
        </div>
      )}
    </div>
  );
}

// ── Finding item ───────────────────────────────────────────────

function FindingItem({ finding: f }: { finding: PillarData["findings"][number] }) {
  const [showDesc, setShowDesc] = useState(false);

  return (
    <div>
      <button
        onClick={() => setShowDesc(!showDesc)}
        className="w-full flex items-center gap-2 text-left py-0.5"
      >
        <div
          className={cn(
            "w-1.5 h-1.5 rounded-full flex-shrink-0",
            f.riskScore >= 0.5 ? "bg-red-500" : f.riskScore >= 0.25 ? "bg-amber-500" : "bg-green-500",
          )}
        />
        <span className="text-[11px] flex-1 truncate">{f.title}</span>
        <span className="text-[10px] font-mono text-muted flex-shrink-0">
          {Math.round(f.confidence * 100)}%
        </span>
      </button>
      <AnimatePresence>
        {showDesc && (
          <motion.p
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.15 }}
            className="text-[10px] text-muted pl-3.5 leading-relaxed overflow-hidden"
          >
            {f.description}
          </motion.p>
        )}
      </AnimatePresence>
    </div>
  );
}

// ── Heatmap section ────────────────────────────────────────────

function HeatmapSection({
  originalImageUrl,
  heatmapUrl,
  fftSpectrumUrl,
  showHeatmap,
  setShowHeatmap,
  opacity,
  setOpacity,
  activeTab,
  setActiveTab,
}: {
  originalImageUrl: string;
  heatmapUrl: string | null;
  fftSpectrumUrl: string | null;
  showHeatmap: boolean;
  setShowHeatmap: (v: boolean) => void;
  opacity: number;
  setOpacity: (v: number) => void;
  activeTab: "spectral" | "fft";
  setActiveTab: (v: "spectral" | "fft") => void;
}) {
  const hasTabs = heatmapUrl && fftSpectrumUrl;
  const activeUrl = hasTabs
    ? activeTab === "spectral" ? heatmapUrl : fftSpectrumUrl
    : heatmapUrl || fftSpectrumUrl;

  return (
    <div className="border-t border-border pt-2 mt-1">
      <div className="flex items-center justify-between mb-1.5">
        <div className="flex items-center gap-2">
          {hasTabs && (
            <div className="flex rounded-md border border-border overflow-hidden">
              <button
                onClick={() => setActiveTab("spectral")}
                className={cn(
                  "px-2 py-0.5 text-[10px] font-medium transition-colors",
                  activeTab === "spectral" ? "bg-accent-solid text-white" : "bg-background text-muted hover:bg-card",
                )}
              >
                Heatmap
              </button>
              <button
                onClick={() => setActiveTab("fft")}
                className={cn(
                  "px-2 py-0.5 text-[10px] font-medium transition-colors",
                  activeTab === "fft" ? "bg-accent-solid text-white" : "bg-background text-muted hover:bg-card",
                )}
              >
                FFT
              </button>
            </div>
          )}
          <button
            onClick={() => setShowHeatmap(!showHeatmap)}
            className={cn(
              "text-[11px] font-medium px-2 py-0.5 rounded transition-colors",
              showHeatmap ? "bg-accent-solid text-white" : "bg-card-hover text-muted hover:bg-card-hover",
            )}
          >
            {showHeatmap ? "Sakrij" : "Prikazi"}
          </button>
        </div>
        {showHeatmap && (
          <div className="flex items-center gap-1.5">
            <span className="text-[10px] text-muted">{opacity}%</span>
            <input
              type="range"
              min={10}
              max={100}
              value={opacity}
              onChange={(e) => setOpacity(Number(e.target.value))}
              className="w-16 h-1 accent-accent-solid"
            />
          </div>
        )}
      </div>

      {showHeatmap && activeUrl && (
        <div className="relative rounded-lg overflow-hidden bg-foreground" style={{ maxHeight: 200 }}>
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src={originalImageUrl} alt="Original" className="w-full object-contain" style={{ maxHeight: 200 }} />
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
