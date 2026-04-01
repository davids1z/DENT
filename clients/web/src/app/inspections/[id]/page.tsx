"use client";

import { useEffect, useState, useCallback } from "react";
import { useParams, useRouter } from "next/navigation";
import { getInspection, deleteInspection, formatDate, type Inspection } from "@/lib/api";
import { AuthGuard } from "@/components/AuthGuard";
import { useAuth } from "@/lib/auth";
import { DamageReport } from "@/components/DamageReport";
import { DamageOverlay } from "@/components/DamageOverlay";
import { DecisionTrace } from "@/components/DecisionTrace";
import { VerdictDashboard } from "@/components/VerdictDashboard";
import { ForensicModuleTable } from "@/components/ForensicModuleTable";
import { AgentReasoningTrace } from "@/components/AgentReasoningTrace";
import { EvidenceIntegrity } from "@/components/EvidenceIntegrity";
import { OverridePanel } from "@/components/OverridePanel";
import { ImageGallery } from "@/components/ImageGallery";
import { GroupOverviewCard } from "@/components/GroupOverviewCard";
import { CrossImageFindings } from "@/components/CrossImageFindings";
import { GlassPanel } from "@/components/ui/GlassPanel";
import { cn } from "@/lib/cn";
import { useMemo } from "react";
import type { ForensicResult } from "@/lib/api";

export default function InspectionDetailPage() {
  return <AuthGuard><InspectionDetailContent /></AuthGuard>;
}

function InspectionDetailContent() {
  const params = useParams();
  const router = useRouter();
  const { user } = useAuth();
  const isAdmin = user?.role === "Admin";
  const [inspection, setInspection] = useState<Inspection | null>(null);
  const [loading, setLoading] = useState(true);
  const [deleting, setDeleting] = useState(false);
  const [copied, setCopied] = useState(false);
  const [selectedDamageIndex, setSelectedDamageIndex] = useState<number | null>(null);
  const [activeImageUrl, setActiveImageUrl] = useState<string | null>(null);
  const [activeImageIndex, setActiveImageIndex] = useState(0);

  const loadInspection = useCallback(() => {
    if (params.id) {
      getInspection(params.id as string)
        .then((data) => { setInspection(data); setActiveImageUrl(data.imageUrl); })
        .catch(() => router.push("/inspections"))
        .finally(() => setLoading(false));
    }
  }, [params.id, router]);

  useEffect(() => { loadInspection(); }, [loadInspection]);

  // All hooks must be called unconditionally (before any early returns) — Rules of Hooks
  const isGroupInspection = (inspection?.additionalImages?.length ?? 0) > 0;
  const groupFiles = useMemo(() => {
    if (!inspection || !isGroupInspection) return [];
    const files: { url: string; fileName: string; sortOrder: number; forensicResult: ForensicResult | null }[] = [];
    const primaryFr = inspection.fileForensicResults?.find((fr: ForensicResult) => fr.sortOrder === 0) || inspection.forensicResult;
    files.push({ url: inspection.imageUrl, fileName: inspection.originalFileName, sortOrder: 0, forensicResult: primaryFr });
    for (const img of (inspection.additionalImages ?? [])) {
      const fr = inspection.fileForensicResults?.find(
        (fr: ForensicResult) => fr.sortOrder === img.sortOrder || fr.fileName === img.originalFileName
      ) || null;
      files.push({ url: img.imageUrl, fileName: img.originalFileName, sortOrder: img.sortOrder, forensicResult: fr });
    }
    return files;
  }, [inspection, isGroupInspection]);

  // Dynamic forensic result — switches when user selects a different image
  const activeForensicResult = useMemo<ForensicResult | null>(() => {
    if (!inspection) return null;
    const fileResults = inspection.fileForensicResults;
    if (!fileResults || fileResults.length === 0) return inspection.forensicResult;

    const currentUrl = activeImageUrl || inspection.imageUrl;

    // Match by fileUrl (exact)
    const matchByUrl = fileResults.find((fr) => fr.fileUrl && fr.fileUrl === currentUrl);
    if (matchByUrl) return matchByUrl;

    // Primary image → sort=0
    if (currentUrl === inspection.imageUrl) {
      return fileResults.find((fr) => fr.sortOrder === 0) || inspection.forensicResult;
    }

    // Additional image → match by fileName
    const additionalImg = (inspection.additionalImages ?? []).find((img) => img.imageUrl === currentUrl);
    if (additionalImg) {
      const matchByName = fileResults.find((fr) => fr.fileName === additionalImg.originalFileName);
      if (matchByName) return matchByName;
    }

    return inspection.forensicResult;
  }, [inspection, activeImageUrl]);

  // Active file name for display
  const activeFileName = useMemo(() => {
    if (!inspection) return "";
    const currentUrl = activeImageUrl || inspection.imageUrl;
    if (currentUrl === inspection.imageUrl) return inspection.originalFileName;
    const img = (inspection.additionalImages ?? []).find((i) => i.imageUrl === currentUrl);
    return img?.originalFileName || inspection.originalFileName;
  }, [inspection, activeImageUrl]);

  const handleDelete = async () => {
    if (!inspection || !confirm("Jeste li sigurni da želite obrisati ovu analizu?")) return;
    setDeleting(true);
    try { await deleteInspection(inspection.id); router.push("/inspections"); } catch { setDeleting(false); }
  };

  const handleShare = async () => {
    try { await navigator.clipboard.writeText(window.location.href); setCopied(true); setTimeout(() => setCopied(false), 2000); } catch {}
  };

  if (loading) {
    return (
      <div className="min-h-[60dvh] flex items-center justify-center">
        <div className="w-8 h-8 border-2 border-accent border-t-transparent rounded-full animate-spin" />
      </div>
    );
  }

  const handleImageSelect = (url: string) => {
    setActiveImageUrl(url);
    if (!inspection) return;
    if (url === inspection.imageUrl) {
      setActiveImageIndex(0);
    } else {
      const idx = (inspection.additionalImages ?? []).findIndex((img) => img.imageUrl === url);
      setActiveImageIndex(idx >= 0 ? idx + 1 : 0);
    }
  };

  if (!inspection) return null;

  const isHighRisk = activeForensicResult
    ? ["High", "Critical"].includes(activeForensicResult.overallRiskLevel)
    : false;

  return (
    <div className="relative">
      <div className="pointer-events-none absolute inset-0 -z-10 overflow-hidden">
        <div className="absolute -top-20 -right-20 w-[280px] h-[280px] sm:-top-28 sm:-right-28 sm:w-[380px] sm:h-[380px] lg:-top-32 lg:-right-32 lg:w-[500px] lg:h-[500px] rounded-full deco-circle" />
      </div>
      <div className="max-w-7xl mx-auto px-4 sm:px-6 py-8 fade-up">
      {/* ── Header ── */}
      <div className="mb-6 sm:mb-8">
        <div className="flex items-center justify-between">
          <button onClick={() => router.back()} className="text-muted hover:text-foreground text-sm mb-2 flex items-center gap-1 transition-colors">
            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" /></svg>
            Natrag
          </button>
          <div className="flex items-center gap-2">
            <button onClick={handleShare} className={cn("px-3 py-1.5 bg-card border border-border rounded-lg text-xs sm:text-sm transition-colors", copied ? "text-green-600 border-green-200" : "text-muted hover:text-foreground")}>
              {copied ? "Kopirano!" : "Podijeli"}
            </button>
            <button onClick={handleDelete} disabled={deleting} className="px-3 py-1.5 bg-card border border-border text-red-500 rounded-lg text-xs sm:text-sm hover:bg-red-50 transition-colors disabled:opacity-50">
              {deleting ? "..." : "Obriši"}
            </button>
          </div>
        </div>
        <h1 className="font-heading text-xl sm:text-2xl font-bold">Forenzička analiza</h1>
        <div className="flex flex-wrap items-center gap-1 sm:gap-2 mt-1">
          <p className="text-muted text-xs sm:text-sm">{formatDate(inspection.createdAt)}</p>
          <span className="text-muted text-xs sm:text-sm truncate max-w-[200px] sm:max-w-none">&middot; {inspection.originalFileName}</span>
        </div>
      </div>

      {/* ── GROUP OVERVIEW (if multi-file) ── */}
      {isGroupInspection && (
        <div className="mb-6 space-y-4">
          <GroupOverviewCard inspection={inspection} files={groupFiles} />
          {inspection.crossImageReport && (inspection.crossImageReport.findings?.length ?? 0) > 0 && (
            <CrossImageFindings report={inspection.crossImageReport} files={groupFiles} />
          )}
        </div>
      )}

      {/* ── 1. VERDICT HERO ── */}
      {activeForensicResult && (
        <div className="mb-8">
          <VerdictDashboard
            riskScore={activeForensicResult.overallRiskScore}
            riskLevel={activeForensicResult.overallRiskLevel}
            c2paStatus={activeForensicResult.c2paStatus}
            predictedSource={activeForensicResult.predictedSource}
            sourceConfidence={activeForensicResult.sourceConfidence}
            totalProcessingTimeMs={activeForensicResult.totalProcessingTimeMs}
            inspectionId={inspection.id}
            summary={inspection.summary}
            decisionOutcome={inspection.decisionOutcome}
            decisionReason={inspection.decisionReason}
            verdictProbabilities={activeForensicResult.verdictProbabilities}
            fileName={activeFileName}
          />
        </div>
      )}

      {/* ── 2. IMAGE + FINDINGS ── */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <div className="space-y-3">
          <DamageOverlay imageUrl={activeImageUrl || inspection.imageUrl} damages={inspection.damages ?? []} selectedIndex={selectedDamageIndex} onSelectDamage={setSelectedDamageIndex} activeImageIndex={activeImageIndex} fileName={activeFileName} pagePreviewUrls={activeForensicResult?.pagePreviewUrls} allImageUrls={isGroupInspection ? [inspection.imageUrl, ...(inspection.additionalImages ?? []).map(i => i.imageUrl)] : undefined} onLightboxNavigate={handleImageSelect} fileLabel={isGroupInspection ? `${activeImageIndex + 1} od ${1 + (inspection.additionalImages?.length ?? 0)}` : undefined} />
          <ImageGallery primaryImageUrl={inspection.imageUrl} additionalImages={inspection.additionalImages ?? []} activeImageUrl={activeImageUrl || inspection.imageUrl} onSelect={handleImageSelect} />
        </div>
        <DamageReport inspection={inspection} selectedDamageIndex={selectedDamageIndex} onSelectDamage={setSelectedDamageIndex} forensicResult={activeForensicResult} />
      </div>

      {/* ── 3. HOW WE DECIDED ── */}
      {(inspection.agentDecision || (inspection.decisionTraces && (inspection.decisionTraces?.length ?? 0) > 0)) && (
        <section className="mt-8">
          <h2 className="font-heading text-lg font-semibold mb-4 flex items-center gap-2">
            <svg className="w-5 h-5 text-violet-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M9.813 15.904L9 18.75l-.813-2.846a4.5 4.5 0 00-3.09-3.09L2.25 12l2.846-.813a4.5 4.5 0 003.09-3.09L9 5.25l.813 2.846a4.5 4.5 0 003.09 3.09L15.75 12l-2.846.813a4.5 4.5 0 00-3.09 3.09z" />
            </svg>
            Kako je sustav donio odluku
          </h2>

          {inspection.agentDecision && (
            <AgentReasoningTrace
              decision={inspection.agentDecision}
              fallbackUsed={inspection.agentFallbackUsed}
              processingTimeMs={inspection.agentProcessingTimeMs}
              defaultExpanded={isHighRisk}
            />
          )}

          {inspection.decisionTraces && (inspection.decisionTraces?.length ?? 0) > 0 && (
            <div className="mt-4">
              <DecisionTrace traces={inspection.decisionTraces} />
            </div>
          )}
        </section>
      )}

      {/* ── 3.5. WEATHER CORRELATION ── */}
      {inspection.agentWeatherAssessment && (() => {
        try {
          const w = JSON.parse(inspection.agentWeatherAssessment) as {
            queried?: boolean; weatherDescription?: string; precipitationMm?: number;
            temperatureMin?: number; temperatureMax?: number; hadHail?: boolean;
            hadPrecipitation?: boolean; latitude?: number; longitude?: number; date?: string;
          };
          if (!w.queried) return null;
          const icon = w.hadHail ? "🌨️" : w.hadPrecipitation ? "🌧️" : "☀️";
          return (
            <div className="mt-4 p-3 bg-card border border-border rounded-xl flex items-center gap-3">
              <span className="text-xl">{icon}</span>
              <div className="flex-1 min-w-0">
                <span className="text-xs font-medium text-foreground block">
                  Vremenska provjera — {w.date}
                </span>
                <span className="text-[11px] text-muted block">
                  {w.weatherDescription}
                  {w.precipitationMm != null && w.precipitationMm > 0 ? `, ${w.precipitationMm.toFixed(1)}mm oborina` : ""}
                  {w.temperatureMin != null && w.temperatureMax != null ? `, ${Math.round(w.temperatureMin)}-${Math.round(w.temperatureMax)}°C` : ""}
                  {w.hadHail ? " — TUČA ZABILJEŽENA" : ""}
                </span>
              </div>
              <span className="text-[10px] text-muted flex-shrink-0">
                GPS: {w.latitude?.toFixed(2)}, {w.longitude?.toFixed(2)}
              </span>
            </div>
          );
        } catch { return null; }
      })()}

      {/* ── 4. FORENSIC MODULES ── */}
      {activeForensicResult && (
        <div className="mt-8">
          <ForensicModuleTable
            result={activeForensicResult}
            originalImageUrl={activeImageUrl || inspection.imageUrl}
            pagePreviewUrls={activeForensicResult.pagePreviewUrls}
          />
        </div>
      )}

      {/* ── 5. EVIDENCE & ACTIONS ── */}
      <div className="mt-8 space-y-4">
        {inspection.evidenceHash && (
          <EvidenceIntegrity inspection={inspection} />
        )}

        {isAdmin && inspection.decisionOutcome && (
          <OverridePanel inspectionId={inspection.id} currentOutcome={inspection.decisionOutcome} overrides={inspection.decisionOverrides} onOverrideComplete={loadInspection} />
        )}
      </div>
      </div>
    </div>
  );
}
