"use client";

import { useState, useMemo } from "react";
import { uploadInspection, pollInspectionUntilComplete, type Inspection, type ForensicResult } from "@/lib/api";
import { ImageUpload } from "@/components/ImageUpload";
import { DamageReport } from "@/components/DamageReport";
import { DamageOverlay } from "@/components/DamageOverlay";
import { DecisionBadge } from "@/components/DecisionBadge";
import { DecisionTrace } from "@/components/DecisionTrace";
import { ImageGallery } from "@/components/ImageGallery";
import { ProgressSteps } from "@/components/ui/ProgressSteps";
import { ForensicProgress, useForensicProgress } from "@/components/ForensicProgress";

export default function InspectPage() {
  const [isLoading, setIsLoading] = useState(false);
  const [uploadedFiles, setUploadedFiles] = useState<File[]>([]);
  const [result, setResult] = useState<Inspection | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [selectedDamageIndex, setSelectedDamageIndex] = useState<number | null>(null);
  const [activeImageUrl, setActiveImageUrl] = useState<string | null>(null);
  const [activeImageIndex, setActiveImageIndex] = useState(0);
  const forensicProgress = useForensicProgress(isLoading, uploadedFiles);

  const currentStep = result ? 2 : isLoading ? 1 : 0;

  // Find the forensic result matching the currently active image
  const activeForensicResult = useMemo<ForensicResult | null>(() => {
    if (!result) return null;
    const fileResults = result.fileForensicResults;
    if (!fileResults || fileResults.length === 0) return result.forensicResult;

    // Match by fileUrl
    const currentUrl = activeImageUrl || result.imageUrl;
    const match = fileResults.find((fr) => fr.fileUrl === currentUrl);
    if (match) return match;

    // Fallback: if viewing primary image, use sort=0
    if (currentUrl === result.imageUrl) {
      return fileResults.find((fr) => fr.sortOrder === 0) || result.forensicResult;
    }

    return result.forensicResult;
  }, [result, activeImageUrl]);

  const handleUploadSubmit = async (files: File[]) => {
    setIsLoading(true);
    setError(null);
    setResult(null);
    setSelectedDamageIndex(null);
    setUploadedFiles(files);

    try {
      // Upload returns immediately with status=Analyzing
      const created = await uploadInspection(files);

      // Poll until analysis completes in background
      const inspection = await pollInspectionUntilComplete(created.id);

      if (inspection.status === "Failed") {
        throw new Error(inspection.errorMessage || "Analiza nije uspjela");
      }

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
    setUploadedFiles([]);
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

      {/* Upload state */}
      {!result && !isLoading && (
        <div className="max-w-lg mx-auto space-y-6">
          <ImageUpload onUpload={handleUploadSubmit} isLoading={isLoading} />

          {error && (
            <div className="bg-red-50 border border-red-200 rounded-xl p-4 text-red-700 text-sm">
              {error}
            </div>
          )}
        </div>
      )}

      {/* Analyzing state — real-time forensic progress */}
      {isLoading && (
        <div className="bg-card border border-border rounded-2xl p-6 sm:p-8 max-w-lg mx-auto">
          <h3 className="font-heading font-semibold text-lg mb-1 text-center">Forenzicka analiza u tijeku</h3>
          <p className="text-sm text-muted mb-6 text-center">
            {uploadedFiles.length > 1
              ? `Analiziram ${uploadedFiles.length} datoteka — svaka prolazi zasebnu forenzicku analizu.`
              : "Forenzicki moduli provjeravaju autenticnost, detektiraju manipulacije i AI-generirani sadrzaj."}
          </p>
          <ForensicProgress
            steps={forensicProgress.steps}
            progress={forensicProgress.progress}
            fileProgresses={forensicProgress.fileProgresses}
            currentFileIndex={forensicProgress.currentFileIndex}
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
              <DamageReport inspection={result} selectedDamageIndex={selectedDamageIndex} onSelectDamage={setSelectedDamageIndex} forensicResult={activeForensicResult} />
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
