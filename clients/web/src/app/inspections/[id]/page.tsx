"use client";

import { useEffect, useState, useCallback } from "react";
import { useParams, useRouter } from "next/navigation";
import { getInspection, deleteInspection, formatDate, type Inspection } from "@/lib/api";
import { DamageReport } from "@/components/DamageReport";
import { DamageOverlay } from "@/components/DamageOverlay";
import { DecisionBadge } from "@/components/DecisionBadge";
import { DecisionTrace } from "@/components/DecisionTrace";
import { ForensicBadge } from "@/components/ForensicBadge";
import { ForensicReport } from "@/components/ForensicReport";
import { ElaHeatmapOverlay } from "@/components/ElaHeatmapOverlay";
import { FftSpectrumOverlay } from "@/components/FftSpectrumOverlay";
import { AgentReasoningTrace } from "@/components/AgentReasoningTrace";
import { OverridePanel } from "@/components/OverridePanel";
import { RepairEstimateTable } from "@/components/RepairEstimateTable";
import { ImageGallery } from "@/components/ImageGallery";
import { SeverityGauge } from "@/components/ui/SeverityGauge";
import { GlassPanel } from "@/components/ui/GlassPanel";
import { Skeleton } from "@/components/ui/Skeleton";
import { cn } from "@/lib/cn";

export default function InspectionDetailPage() {
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
    if (!inspection || !confirm("Jeste li sigurni da želite obrisati ovu inspekciju?")) return;
    setDeleting(true);
    try { await deleteInspection(inspection.id); router.push("/inspections"); } catch { setDeleting(false); }
  };

  const handleShare = async () => {
    try { await navigator.clipboard.writeText(window.location.href); setCopied(true); setTimeout(() => setCopied(false), 2000); } catch {}
  };

  if (loading) {
    return (
      <div className="max-w-7xl mx-auto px-4 sm:px-6 py-8">
        <Skeleton className="h-8 w-48 mb-4" />
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          <Skeleton variant="card" className="h-96" />
          <div className="space-y-4">
            <Skeleton variant="card" className="h-32" />
            <Skeleton variant="card" className="h-24" />
            <Skeleton variant="card" className="h-48" />
          </div>
        </div>
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

  const worstSeverity = inspection.damages.reduce(
    (worst, d) => {
      const order = ["Minor", "Moderate", "Severe", "Critical"];
      return order.indexOf(d.severity) > order.indexOf(worst) ? d.severity : worst;
    },
    "Minor"
  );

  return (
    <div className="max-w-7xl mx-auto px-4 sm:px-6 py-8">
      <div className="flex items-start justify-between mb-8">
        <div>
          <button onClick={() => router.back()} className="text-muted hover:text-foreground text-sm mb-2 flex items-center gap-1 transition-colors">
            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" /></svg>
            Natrag
          </button>
          <h1 className="font-heading text-2xl font-bold">
            {inspection.vehicleMake && inspection.vehicleModel ? `${inspection.vehicleMake} ${inspection.vehicleModel}` : "Inspekcija"}
          </h1>
          <div className="flex items-center gap-2 mt-1">
            <p className="text-muted text-sm">{formatDate(inspection.createdAt)}</p>
            {inspection.mileage && <span className="text-muted text-sm">&middot; {inspection.mileage.toLocaleString("hr-HR")} km</span>}
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

      {inspection.decisionOutcome && (
        <div className="mb-6">
          <DecisionBadge outcome={inspection.decisionOutcome} reason={inspection.decisionReason} />
        </div>
      )}

      {inspection.forensicResult && (
        <div className="mb-6">
          <ForensicBadge
            riskScore={inspection.forensicResult.overallRiskScore}
            riskLevel={inspection.forensicResult.overallRiskLevel}
          />
        </div>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <div className="space-y-3">
          <DamageOverlay imageUrl={activeImageUrl || inspection.imageUrl} damages={inspection.damages} selectedIndex={selectedDamageIndex} onSelectDamage={setSelectedDamageIndex} activeImageIndex={activeImageIndex} />
          <ImageGallery primaryImageUrl={inspection.imageUrl} additionalImages={inspection.additionalImages} activeImageUrl={activeImageUrl || inspection.imageUrl} onSelect={handleImageSelect} />
          {inspection.damages.length > 0 && (
            <GlassPanel className="flex items-center justify-between">
              <div>
                <div className="text-xs text-muted mb-1">Ukupna ozbiljnost</div>
                <SeverityGauge severity={worstSeverity} size={100} />
              </div>
              <div className="text-right">
                <div className="text-xs text-muted">
                  <div>Datoteka: {inspection.originalFileName}</div>
                  <div className="mt-0.5 font-mono text-[10px]">ID: {inspection.id.slice(0, 8)}...</div>
                </div>
              </div>
            </GlassPanel>
          )}
          {inspection.damages.length === 0 && (
            <GlassPanel>
              <div className="text-xs text-muted">
                <span>Datoteka: {inspection.originalFileName}</span>
                <span className="mx-2">|</span>
                <span>ID: {inspection.id.slice(0, 8)}...</span>
              </div>
            </GlassPanel>
          )}
        </div>
        <DamageReport inspection={inspection} selectedDamageIndex={selectedDamageIndex} onSelectDamage={setSelectedDamageIndex} />
      </div>

      <div className="mt-6"><RepairEstimateTable inspection={inspection} /></div>

      {inspection.forensicResult && (
        <div className="mt-6 space-y-4">
          <ForensicReport result={inspection.forensicResult} />
          {inspection.forensicResult.elaHeatmapUrl && (
            <ElaHeatmapOverlay
              originalImageUrl={activeImageUrl || inspection.imageUrl}
              heatmapUrl={inspection.forensicResult.elaHeatmapUrl}
            />
          )}
          {inspection.forensicResult.fftSpectrumUrl && (
            <FftSpectrumOverlay
              fftSpectrumUrl={inspection.forensicResult.fftSpectrumUrl}
            />
          )}
        </div>
      )}

      {inspection.agentDecision && (
        <div className="mt-6">
          <AgentReasoningTrace
            decision={inspection.agentDecision}
            fallbackUsed={inspection.agentFallbackUsed}
            processingTimeMs={inspection.agentProcessingTimeMs}
          />
        </div>
      )}

      {inspection.decisionOutcome && (
        <div className="mt-6 space-y-4">
          {inspection.decisionTraces && inspection.decisionTraces.length > 0 && <DecisionTrace traces={inspection.decisionTraces} />}
          <OverridePanel inspectionId={inspection.id} currentOutcome={inspection.decisionOutcome} overrides={inspection.decisionOverrides} onOverrideComplete={loadInspection} />
        </div>
      )}
    </div>
  );
}
