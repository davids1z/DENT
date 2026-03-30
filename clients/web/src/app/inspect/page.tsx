"use client";

import { useState, useMemo } from "react";
import { uploadInspections, pollInspectionUntilComplete, type Inspection, type ForensicResult } from "@/lib/api";
import { AuthGuard } from "@/components/AuthGuard";
import { ImageUpload } from "@/components/ImageUpload";
import { DamageReport } from "@/components/DamageReport";
import { DamageOverlay } from "@/components/DamageOverlay";
import { DecisionBadge } from "@/components/DecisionBadge";
import { DecisionTrace } from "@/components/DecisionTrace";
import { ImageGallery } from "@/components/ImageGallery";
import { ProgressSteps } from "@/components/ui/ProgressSteps";
import { ForensicProgress, useForensicProgress } from "@/components/ForensicProgress";
import Link from "next/link";

export default function InspectPage() {
  return <AuthGuard><InspectContent /></AuthGuard>;
}

function InspectContent() {
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

    const currentUrl = activeImageUrl || result.imageUrl;

    // Match by fileUrl (exact)
    const matchByUrl = fileResults.find((fr) => fr.fileUrl && fr.fileUrl === currentUrl);
    if (matchByUrl) return matchByUrl;

    // Fallback: if viewing primary image, use sort=0
    if (currentUrl === result.imageUrl) {
      return fileResults.find((fr) => fr.sortOrder === 0) || result.forensicResult;
    }

    // Fallback: match additional image by fileName
    const additionalImg = result.additionalImages.find((img) => img.imageUrl === currentUrl);
    if (additionalImg) {
      const matchByName = fileResults.find((fr) => fr.fileName === additionalImg.originalFileName);
      if (matchByName) return matchByName;
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
      // Each file becomes a SEPARATE inspection
      const created = await uploadInspections(files);

      // Poll ALL inspections in parallel
      const inspections = await Promise.all(
        created.map((c) => pollInspectionUntilComplete(c.id))
      );

      const failed = inspections.filter((i) => i.status === "Failed");
      if (failed.length === inspections.length) {
        throw new Error(failed[0]?.errorMessage || "Analiza nije uspjela");
      }

      await forensicProgress.complete();

      // Show the first completed inspection result
      const firstCompleted = inspections.find((i) => i.status === "Completed") || inspections[0];
      setResult(firstCompleted);
      setActiveImageUrl(firstCompleted.imageUrl);
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
    <div className="relative">
      <div className="pointer-events-none absolute inset-0 -z-10 overflow-hidden">
        <div className="absolute -top-64 -right-64 w-[500px] h-[500px] rounded-full deco-circle" />
        <div className="absolute -bottom-48 -left-48 w-[350px] h-[350px] rounded-full deco-circle" />
      </div>
      <div className="max-w-5xl mx-auto px-4 sm:px-6 py-8 md:py-12 fade-up">
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
              <DamageOverlay imageUrl={activeImageUrl || result.imageUrl} damages={result.damages} selectedIndex={selectedDamageIndex} onSelectDamage={setSelectedDamageIndex} activeImageIndex={activeImageIndex} fileName={result.originalFileName} pagePreviewUrls={activeForensicResult?.pagePreviewUrls} />
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
            {uploadedFiles.length > 1 && (
              <Link href="/inspections" className="px-6 py-2.5 bg-accent text-white rounded-xl font-medium text-sm hover:bg-accent-hover transition-colors inline-flex items-center gap-2">
                Pogledaj sve analize ({uploadedFiles.length})
              </Link>
            )}
            <button onClick={() => window.print()} className="px-6 py-2.5 bg-card border border-border rounded-xl font-medium text-sm hover:bg-card-hover transition-colors">
              Isprintaj izvjestaj
            </button>
          </div>
        </div>
      )}
      </div>
    </div>
  );
}
