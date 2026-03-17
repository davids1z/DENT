"use client";

import { useState } from "react";
import { uploadInspectionWithMetadata, uploadInspection, type Inspection, type CaptureMetadata } from "@/lib/api";
import { CameraCapture, type CapturedImage } from "@/components/CameraCapture";
import { QrHandoff } from "@/components/QrHandoff";
import { UploadFallback } from "@/components/UploadFallback";
import { DamageReport } from "@/components/DamageReport";
import { DamageOverlay } from "@/components/DamageOverlay";
import { DecisionBadge } from "@/components/DecisionBadge";
import { DecisionTrace } from "@/components/DecisionTrace";
import { ImageGallery } from "@/components/ImageGallery";
import { ProgressSteps } from "@/components/ui/ProgressSteps";
import { ForensicProgress, useForensicProgress } from "@/components/ForensicProgress";

export default function InspectPage() {
  const [isLoading, setIsLoading] = useState(false);
  const [result, setResult] = useState<Inspection | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [selectedDamageIndex, setSelectedDamageIndex] = useState<number | null>(null);
  const [activeImageUrl, setActiveImageUrl] = useState<string | null>(null);
  const [activeImageIndex, setActiveImageIndex] = useState(0);
  const [cameraUnavailable, setCameraUnavailable] = useState(false);
  const forensicProgress = useForensicProgress(isLoading);

  const currentStep = result ? 2 : isLoading ? 1 : 0;

  const handleCameraSubmit = async (captures: CapturedImage[]) => {
    setIsLoading(true);
    setError(null);
    setResult(null);
    setSelectedDamageIndex(null);

    try {
      const files = captures.map((c) => c.file);
      const metadata: CaptureMetadata[] = captures.map((c) => ({
        gps: c.gps,
        device: c.deviceMeta,
        capturedAt: c.capturedAt,
      }));

      const inspection = await uploadInspectionWithMetadata(files, metadata);
      forensicProgress.complete();
      setResult(inspection);
      setActiveImageUrl(inspection.imageUrl);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Došlo je do greške");
    } finally {
      setIsLoading(false);
    }
  };

  const handleUploadSubmit = async (files: File[]) => {
    setIsLoading(true);
    setError(null);
    setResult(null);
    setSelectedDamageIndex(null);

    try {
      // No captureMetadata → backend sets captureSource = "upload"
      const inspection = await uploadInspection(files);
      forensicProgress.complete();
      setResult(inspection);
      setActiveImageUrl(inspection.imageUrl);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Doslo je do greske");
    } finally {
      setIsLoading(false);
    }
  };

  const handleReset = () => {
    setResult(null);
    setError(null);
    setSelectedDamageIndex(null);
    setActiveImageUrl(null);
    setActiveImageIndex(0);
  };

  const handleImageSelect = (url: string) => {
    setActiveImageUrl(url);
    if (!result) return;
    if (url === result.imageUrl) {
      setActiveImageIndex(0);
    } else {
      const idx = result.additionalImages.findIndex((img) => img.imageUrl === url);
      setActiveImageIndex(idx >= 0 ? idx + 1 : 0);
    }
  };

  return (
    <div className="max-w-5xl mx-auto px-4 sm:px-6 py-8 md:py-12">
      {/* Header */}
      <div className="mb-8">
        <div className="max-w-2xl mx-auto text-center">
          <h1 className="font-heading text-2xl sm:text-3xl font-bold tracking-tight mb-2">
            Nova analiza
          </h1>
          <p className="text-muted text-sm sm:text-base mb-6">
            Forenzicka verifikacija digitalnih medija
          </p>
          <ProgressSteps currentStep={currentStep} />
        </div>
      </div>

      {/* Camera capture state */}
      {!result && !isLoading && (
        <div className="space-y-6">
          <CameraCapture
            onCapture={handleCameraSubmit}
            isLoading={isLoading}
            onCameraUnavailable={() => setCameraUnavailable(true)}
          />

          {/* Fallback options — shown when camera hardware is unavailable */}
          {cameraUnavailable && (
            <div className="space-y-6">
              <div className="flex items-center gap-4">
                <div className="flex-1 h-px bg-border" />
                <span className="text-sm text-muted">ili</span>
                <div className="flex-1 h-px bg-border" />
              </div>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <QrHandoff />
                <UploadFallback
                  onUpload={handleUploadSubmit}
                  isLoading={isLoading}
                />
              </div>
            </div>
          )}

          {error && (
            <div className="bg-red-50 border border-red-200 rounded-xl p-4 text-red-700 text-sm">
              {error}
            </div>
          )}

          {/* Info cards */}
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 pt-2">
            <div className="flex items-start gap-3 p-4 rounded-xl bg-card border border-border">
              <div className="w-8 h-8 rounded-lg bg-accent-light flex items-center justify-center flex-shrink-0">
                <svg className="w-4 h-4 text-accent" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M6.827 6.175A2.31 2.31 0 015.186 7.23c-.38.054-.757.112-1.134.175C2.999 7.58 2.25 8.507 2.25 9.574V18a2.25 2.25 0 002.25 2.25h15A2.25 2.25 0 0021.75 18V9.574c0-1.067-.75-1.994-1.802-2.169a47.865 47.865 0 00-1.134-.175 2.31 2.31 0 01-1.64-1.055l-.822-1.316a2.192 2.192 0 00-1.736-1.039 48.774 48.774 0 00-5.232 0 2.192 2.192 0 00-1.736 1.039l-.821 1.316z" />
                  <path strokeLinecap="round" strokeLinejoin="round" d="M16.5 12.75a4.5 4.5 0 11-9 0 4.5 4.5 0 019 0z" />
                </svg>
              </div>
              <div>
                <div className="text-sm font-medium mb-0.5">Live kamera</div>
                <div className="text-xs text-muted">Slikajte uzivo za maksimalnu sigurnost i tocnost</div>
              </div>
            </div>
            <div className="flex items-start gap-3 p-4 rounded-xl bg-card border border-border">
              <div className="w-8 h-8 rounded-lg bg-accent-light flex items-center justify-center flex-shrink-0">
                <svg className="w-4 h-4 text-accent" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M12 6v6h4.5m4.5 0a9 9 0 11-18 0 9 9 0 0118 0z" />
                </svg>
              </div>
              <div>
                <div className="text-sm font-medium mb-0.5">30-90 sekundi</div>
                <div className="text-xs text-muted">Forenzicka analiza traje manje od 2 minute</div>
              </div>
            </div>
            <div className="flex items-start gap-3 p-4 rounded-xl bg-card border border-border">
              <div className="w-8 h-8 rounded-lg bg-accent-light flex items-center justify-center flex-shrink-0">
                <svg className="w-4 h-4 text-accent" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M9 12.75L11.25 15 15 9.75m-3-7.036A11.959 11.959 0 013.598 6 11.99 11.99 0 003 9.749c0 5.592 3.824 10.29 9 11.623 5.176-1.332 9-6.03 9-11.622 0-1.31-.21-2.571-.598-3.751h-.152c-3.196 0-6.1-1.248-8.25-3.285z" />
                </svg>
              </div>
              <div>
                <div className="text-sm font-medium mb-0.5">Anti-fraud zastita</div>
                <div className="text-xs text-muted">GPS, uredaj i frekvencijska analiza u realnom vremenu</div>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Analyzing state — real-time forensic progress */}
      {isLoading && (
        <div className="bg-card border border-border rounded-2xl p-6 sm:p-8 max-w-lg mx-auto">
          <h3 className="font-heading font-semibold text-lg mb-1 text-center">Forenzicka analiza u tijeku</h3>
          <p className="text-sm text-muted mb-6 text-center">
            10 forenzickih modula provjerava autenticnost, detektira manipulacije i AI-generirani sadrzaj.
          </p>
          <ForensicProgress
            steps={forensicProgress.steps}
            progress={forensicProgress.progress}
          />
          <p className="text-xs text-muted mt-5 text-center">Ovo moze potrajati do 2 minute za vise datoteka</p>
        </div>
      )}

      {/* Result state */}
      {result && (
        <div className="space-y-6">
          {result.decisionOutcome && (
            <DecisionBadge outcome={result.decisionOutcome} reason={result.decisionReason} />
          )}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            <div className="space-y-3">
              <DamageOverlay imageUrl={activeImageUrl || result.imageUrl} damages={result.damages} selectedIndex={selectedDamageIndex} onSelectDamage={setSelectedDamageIndex} activeImageIndex={activeImageIndex} />
              <ImageGallery primaryImageUrl={result.imageUrl} additionalImages={result.additionalImages} activeImageUrl={activeImageUrl || result.imageUrl} onSelect={handleImageSelect} />
            </div>
            <div>
              <DamageReport inspection={result} selectedDamageIndex={selectedDamageIndex} onSelectDamage={setSelectedDamageIndex} />
            </div>
          </div>
          {result.decisionTraces && result.decisionTraces.length > 0 && (
            <DecisionTrace traces={result.decisionTraces} />
          )}
          <div className="flex gap-3">
            <button onClick={handleReset} className="px-6 py-2.5 bg-accent text-white rounded-xl font-medium text-sm hover:bg-accent-hover transition-colors">
              Nova analiza
            </button>
            <button onClick={() => window.print()} className="px-6 py-2.5 bg-card border border-border rounded-xl font-medium text-sm hover:bg-card-hover transition-colors">
              Isprintaj izvjestaj
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
