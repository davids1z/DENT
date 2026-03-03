"use client";

import { useState } from "react";
import { uploadInspection, type Inspection } from "@/lib/api";
import { ImageUpload } from "@/components/ImageUpload";
import { DamageReport } from "@/components/DamageReport";
import { DamageOverlay } from "@/components/DamageOverlay";
import { DecisionBadge } from "@/components/DecisionBadge";
import { DecisionTrace } from "@/components/DecisionTrace";
import { RepairEstimateTable } from "@/components/RepairEstimateTable";
import { ImageGallery } from "@/components/ImageGallery";
import { ProgressSteps } from "@/components/ui/ProgressSteps";

export default function InspectPage() {
  const [isLoading, setIsLoading] = useState(false);
  const [result, setResult] = useState<Inspection | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [selectedDamageIndex, setSelectedDamageIndex] = useState<number | null>(null);
  const [activeImageUrl, setActiveImageUrl] = useState<string | null>(null);
  const [activeImageIndex, setActiveImageIndex] = useState(0);

  const currentStep = result ? 2 : isLoading ? 1 : 0;

  const handleUpload = async (files: File[]) => {
    setIsLoading(true);
    setError(null);
    setResult(null);
    setSelectedDamageIndex(null);

    try {
      const inspection = await uploadInspection(files);
      setResult(inspection);
      setActiveImageUrl(inspection.imageUrl);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Došlo je do greške");
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
            Nova inspekcija
          </h1>
          <p className="text-muted text-sm sm:text-base mb-6">
            Dodajte fotografije oštećenja za AI analizu vozila
          </p>
          <ProgressSteps currentStep={currentStep} />
        </div>
      </div>

      {/* Upload state */}
      {!result && !isLoading && (
        <div className="space-y-6">
          <ImageUpload onUpload={handleUpload} isLoading={isLoading} />

          {error && (
            <div className="bg-red-50 border border-red-200 rounded-xl p-4 text-red-700 text-sm">
              {error}
            </div>
          )}

          {/* Info cards below upload */}
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 pt-2">
            <div className="flex items-start gap-3 p-4 rounded-xl bg-card border border-border">
              <div className="w-8 h-8 rounded-lg bg-accent-light flex items-center justify-center flex-shrink-0">
                <svg className="w-4 h-4 text-accent" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M6.827 6.175A2.31 2.31 0 015.186 7.23c-.38.054-.757.112-1.134.175C2.999 7.58 2.25 8.507 2.25 9.574V18a2.25 2.25 0 002.25 2.25h15A2.25 2.25 0 0021.75 18V9.574c0-1.067-.75-1.994-1.802-2.169a47.865 47.865 0 00-1.134-.175 2.31 2.31 0 01-1.64-1.055l-.822-1.316a2.192 2.192 0 00-1.736-1.039 48.774 48.774 0 00-5.232 0 2.192 2.192 0 00-1.736 1.039l-.821 1.316z" />
                  <path strokeLinecap="round" strokeLinejoin="round" d="M16.5 12.75a4.5 4.5 0 11-9 0 4.5 4.5 0 019 0z" />
                </svg>
              </div>
              <div>
                <div className="text-sm font-medium mb-0.5">Do 8 slika</div>
                <div className="text-xs text-muted">Fotografirajte vozilo iz više kutova za bolju preciznost</div>
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
                <div className="text-xs text-muted">Analiza traje manje od 2 minute za više fotografija</div>
              </div>
            </div>
            <div className="flex items-start gap-3 p-4 rounded-xl bg-card border border-border">
              <div className="w-8 h-8 rounded-lg bg-accent-light flex items-center justify-center flex-shrink-0">
                <svg className="w-4 h-4 text-accent" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M19.5 14.25v-2.625a3.375 3.375 0 00-3.375-3.375h-1.5A1.125 1.125 0 0113.5 7.125v-1.5a3.375 3.375 0 00-3.375-3.375H8.25m0 12.75h7.5m-7.5 3H12M10.5 2.25H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 00-9-9z" />
                </svg>
              </div>
              <div>
                <div className="text-sm font-medium mb-0.5">Detaljan izvještaj</div>
                <div className="text-xs text-muted">Štete, ozbiljnost, troškovi i preporuka za djelovanje</div>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Analyzing state */}
      {isLoading && (
        <div className="bg-card border border-border rounded-2xl p-8 max-w-lg mx-auto text-center">
          <div className="w-12 h-12 border-2 border-accent border-t-transparent rounded-full animate-spin mx-auto mb-4" />
          <h3 className="font-heading font-semibold text-lg mb-2">AI analizira vaše vozilo</h3>
          <p className="text-sm text-muted mb-6">
            Napredni vizijski model detektira i klasificira svako oštećenje na fotografijama.
          </p>
          <div className="space-y-2 max-w-xs mx-auto">
            <div className="h-2 skeleton rounded-full w-3/4 mx-auto" />
            <div className="h-2 skeleton rounded-full w-1/2 mx-auto" />
            <div className="h-2 skeleton rounded-full w-2/3 mx-auto" />
          </div>
          <p className="text-xs text-muted mt-6">Ovo može potrajati do 2 minute za više slika</p>
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
          <RepairEstimateTable inspection={result} />
          {result.decisionTraces && result.decisionTraces.length > 0 && (
            <DecisionTrace traces={result.decisionTraces} />
          )}
          <div className="flex gap-3">
            <button onClick={handleReset} className="px-6 py-2.5 bg-accent text-white rounded-xl font-medium text-sm hover:bg-accent-hover transition-colors">
              Nova inspekcija
            </button>
            <button onClick={() => window.print()} className="px-6 py-2.5 bg-card border border-border rounded-xl font-medium text-sm hover:bg-card-hover transition-colors">
              Isprintaj izvještaj
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
