"use client";

import { useEffect, useState, useCallback } from "react";
import { useParams, useRouter } from "next/navigation";
import { getInspection, deleteInspection, formatDate, type Inspection } from "@/lib/api";
import { AuthGuard } from "@/components/AuthGuard";
import { DamageReport } from "@/components/DamageReport";
import { DamageOverlay } from "@/components/DamageOverlay";
import { DecisionTrace } from "@/components/DecisionTrace";
import { VerdictDashboard } from "@/components/VerdictDashboard";
import { ForensicModuleTable } from "@/components/ForensicModuleTable";
import { AgentReasoningTrace } from "@/components/AgentReasoningTrace";
import { EvidenceIntegrity } from "@/components/EvidenceIntegrity";
import { OverridePanel } from "@/components/OverridePanel";
import { ImageGallery } from "@/components/ImageGallery";
import { GlassPanel } from "@/components/ui/GlassPanel";
import { cn } from "@/lib/cn";

export default function InspectionDetailPage() {
  return <AuthGuard><InspectionDetailContent /></AuthGuard>;
}

function InspectionDetailContent() {
  const params = useParams();
  const router = useRouter();
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
      const idx = inspection.additionalImages.findIndex((img) => img.imageUrl === url);
      setActiveImageIndex(idx >= 0 ? idx + 1 : 0);
    }
  };

  if (!inspection) return null;

  const isHighRisk = inspection.forensicResult
    ? ["High", "Critical"].includes(inspection.forensicResult.overallRiskLevel)
    : false;

  return (
    <div className="relative">
      <div className="pointer-events-none absolute inset-0 -z-10 overflow-hidden">
        <div className="absolute -top-24 right-[20%] w-[500px] h-[500px] rounded-full deco-circle" />
      </div>
      <div className="max-w-7xl mx-auto px-4 sm:px-6 py-8 fade-up">
      {/* ── Header ── */}
      <div className="flex items-start justify-between mb-8">
        <div>
          <button onClick={() => router.back()} className="text-muted hover:text-foreground text-sm mb-2 flex items-center gap-1 transition-colors">
            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" /></svg>
            Natrag
          </button>
          <h1 className="font-heading text-2xl font-bold">Forenzička analiza</h1>
          <div className="flex items-center gap-2 mt-1">
            <p className="text-muted text-sm">{formatDate(inspection.createdAt)}</p>
            <span className="text-muted text-sm">&middot; {inspection.originalFileName}</span>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <button onClick={handleShare} className={cn("px-4 py-2 bg-card border border-border rounded-lg text-sm transition-colors", copied ? "text-green-600 border-green-200" : "text-muted hover:text-foreground")}>
            {copied ? "Kopirano!" : "Podijeli"}
          </button>
          <button onClick={handleDelete} disabled={deleting} className="px-4 py-2 bg-card border border-border text-red-500 rounded-lg text-sm hover:bg-red-50 transition-colors disabled:opacity-50">
            {deleting ? "Brisanje..." : "Obriši"}
          </button>
        </div>
      </div>

      {/* ── 1. VERDICT HERO ── */}
      {inspection.forensicResult && (
        <div className="mb-8">
          <VerdictDashboard
            riskScore={inspection.forensicResult.overallRiskScore}
            riskLevel={inspection.forensicResult.overallRiskLevel}
            c2paStatus={inspection.forensicResult.c2paStatus}
            predictedSource={inspection.forensicResult.predictedSource}
            sourceConfidence={inspection.forensicResult.sourceConfidence}
            totalProcessingTimeMs={inspection.forensicResult.totalProcessingTimeMs}
            inspectionId={inspection.id}
            summary={inspection.summary}
            decisionOutcome={inspection.decisionOutcome}
            decisionReason={inspection.decisionReason}
            verdictProbabilities={inspection.forensicResult.verdictProbabilities}
            fileName={inspection.originalFileName}
          />
        </div>
      )}

      {/* ── 2. IMAGE + FINDINGS ── */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <div className="space-y-3">
          <DamageOverlay imageUrl={activeImageUrl || inspection.imageUrl} damages={inspection.damages} selectedIndex={selectedDamageIndex} onSelectDamage={setSelectedDamageIndex} activeImageIndex={activeImageIndex} fileName={inspection.originalFileName} pagePreviewUrls={inspection.forensicResult?.pagePreviewUrls} />
          <ImageGallery primaryImageUrl={inspection.imageUrl} additionalImages={inspection.additionalImages} activeImageUrl={activeImageUrl || inspection.imageUrl} onSelect={handleImageSelect} />
          <GlassPanel>
            <div className="text-xs text-muted">
              <span>Datoteka: {inspection.originalFileName}</span>
              <span className="mx-2">|</span>
              <span>ID: {inspection.id.slice(0, 8)}...</span>
            </div>
          </GlassPanel>
        </div>
        <DamageReport inspection={inspection} selectedDamageIndex={selectedDamageIndex} onSelectDamage={setSelectedDamageIndex} forensicResult={inspection.forensicResult} />
      </div>

      {/* ── 3. HOW WE DECIDED ── */}
      {(inspection.agentDecision || (inspection.decisionTraces && inspection.decisionTraces.length > 0)) && (
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

          {inspection.decisionTraces && inspection.decisionTraces.length > 0 && (
            <div className="mt-4">
              <DecisionTrace traces={inspection.decisionTraces} />
            </div>
          )}
        </section>
      )}

      {/* ── 4. FORENSIC MODULES ── */}
      {inspection.forensicResult && (
        <div className="mt-8">
          <ForensicModuleTable
            result={inspection.forensicResult}
            originalImageUrl={activeImageUrl || inspection.imageUrl}
          />
        </div>
      )}

      {/* ── 5. EVIDENCE & ACTIONS ── */}
      <div className="mt-8 space-y-4">
        {inspection.evidenceHash && (
          <EvidenceIntegrity inspection={inspection} />
        )}

        {inspection.decisionOutcome && (
          <OverridePanel inspectionId={inspection.id} currentOutcome={inspection.decisionOutcome} overrides={inspection.decisionOverrides} onOverrideComplete={loadInspection} />
        )}
      </div>
      </div>
    </div>
  );
}
