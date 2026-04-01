"use client";

import { useState, useMemo } from "react";
import { uploadInspections, uploadInspection, pollInspectionUntilComplete, type Inspection, type ForensicResult } from "@/lib/api";
import { AuthGuard } from "@/components/AuthGuard";
import { ImageUpload } from "@/components/ImageUpload";
import { DamageReport } from "@/components/DamageReport";
import { DamageOverlay } from "@/components/DamageOverlay";
import { DecisionBadge } from "@/components/DecisionBadge";
import { DecisionTrace } from "@/components/DecisionTrace";
import { ImageGallery } from "@/components/ImageGallery";
import { ProgressSteps } from "@/components/ui/ProgressSteps";
import { ForensicProgress, useForensicProgress } from "@/components/ForensicProgress";
import { GroupOverviewCard } from "@/components/GroupOverviewCard";
import { CrossImageFindings } from "@/components/CrossImageFindings";
import { ForensicModuleTable } from "@/components/ForensicModuleTable";
import { VerdictDashboard } from "@/components/VerdictDashboard";
import { cn } from "@/lib/cn";
import Link from "next/link";

type AnalysisMode = "individual" | "group";

export default function InspectPage() {
  return <AuthGuard><InspectContent /></AuthGuard>;
}

function InspectContent() {
  const [mode, setMode] = useState<AnalysisMode>("individual");
  const [isLoading, setIsLoading] = useState(false);
  const [uploadedFiles, setUploadedFiles] = useState<File[]>([]);
  const [result, setResult] = useState<Inspection | null>(null);
  const [allResults, setAllResults] = useState<Inspection[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [selectedDamageIndex, setSelectedDamageIndex] = useState<number | null>(null);
  const [activeImageUrl, setActiveImageUrl] = useState<string | null>(null);
  const [activeImageIndex, setActiveImageIndex] = useState(0);
  const [expandedFileIndex, setExpandedFileIndex] = useState<number | null>(null);
  const forensicProgress = useForensicProgress(isLoading, uploadedFiles);

  const currentStep = result ? 2 : isLoading ? 1 : 0;
  const isGroupMode = mode === "group";
  const isGroupResult = isGroupMode && result && (result.fileForensicResults?.length > 1 || result.additionalImages?.length > 0);

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
    const additionalImg = (result.additionalImages ?? []).find((img) => img.imageUrl === currentUrl);
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
    setAllResults([]);
    setSelectedDamageIndex(null);
    setUploadedFiles(files);
    setExpandedFileIndex(null);

    try {
      if (isGroupMode) {
        // Group mode: single inspection with all files + cross-image analysis
        const created = await uploadInspection(files, { analysisMode: "group" });
        const completed = await pollInspectionUntilComplete(created.id);
        if (completed.status === "Failed") {
          throw new Error(completed.errorMessage || "Analiza nije uspjela");
        }
        await forensicProgress.complete();
        setResult(completed);
        setActiveImageUrl(completed.imageUrl);
      } else {
        // Individual mode: each file → separate inspection
        const created = await uploadInspections(files);
        const inspections = await Promise.all(
          created.map((c) => pollInspectionUntilComplete(c.id))
        );
        const failed = inspections.filter((i) => i.status === "Failed");
        if (failed.length === inspections.length) {
          throw new Error(failed[0]?.errorMessage || "Analiza nije uspjela");
        }
        await forensicProgress.complete();
        setAllResults(inspections);
        const firstCompleted = inspections.find((i) => i.status === "Completed") || inspections[0];
        setResult(firstCompleted);
        setActiveImageUrl(firstCompleted.imageUrl);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Došlo je do greške");
    } finally {
      setIsLoading(false);
    }
  };

  const handleReset = () => {
    setResult(null);
    setAllResults([]);
    setError(null);
    setSelectedDamageIndex(null);
    setActiveImageUrl(null);
    setActiveImageIndex(0);
    setUploadedFiles([]);
    setExpandedFileIndex(null);
  };

  const handleImageSelect = (url: string) => {
    setActiveImageUrl(url);
    if (!result) return;
    if (url === result.imageUrl) {
      setActiveImageIndex(0);
    } else {
      const idx = (result.additionalImages ?? []).findIndex((img) => img.imageUrl === url);
      setActiveImageIndex(idx >= 0 ? idx + 1 : 0);
    }
  };

  // Build file list for group view
  const groupFiles = useMemo(() => {
    if (!result) return [];
    const files: { url: string; fileName: string; sortOrder: number; forensicResult: ForensicResult | null }[] = [];

    // Primary
    const primaryFr = result.fileForensicResults?.find((fr) => fr.sortOrder === 0) || result.forensicResult;
    files.push({ url: result.imageUrl, fileName: result.originalFileName, sortOrder: 0, forensicResult: primaryFr });

    // Additional images
    for (const img of result.additionalImages) {
      const fr = result.fileForensicResults?.find(
        (fr) => fr.sortOrder === img.sortOrder || fr.fileName === img.originalFileName
      ) || null;
      files.push({ url: img.imageUrl, fileName: img.originalFileName, sortOrder: img.sortOrder, forensicResult: fr });
    }

    return files;
  }, [result]);

  return (
    <div className="relative">
      <div className="pointer-events-none absolute inset-0 -z-10 overflow-hidden">
        <div className="absolute -top-32 -right-32 w-[280px] h-[280px] sm:-top-40 sm:-right-40 sm:w-[380px] sm:h-[380px] lg:-top-44 lg:-right-44 lg:w-[480px] lg:h-[480px] rounded-full deco-circle" />
        <div className="absolute bottom-32 left-4 w-[120px] h-[120px] sm:bottom-24 sm:left-6 sm:w-[160px] sm:h-[160px] lg:w-[200px] lg:h-[200px] rounded-full deco-circle" />
      </div>
      <div className="max-w-5xl mx-auto px-4 sm:px-6 py-8 md:py-12 fade-up">
      {/* Header */}
      <div className="mb-8">
        <div className="max-w-2xl mx-auto text-center">
          <h1 className="font-heading text-2xl sm:text-3xl font-bold tracking-tight mb-2">
            Nova analiza
          </h1>
          <p className="text-muted text-sm sm:text-base mb-6">
            Forenzička verifikacija digitalnih medija
          </p>
          <ProgressSteps currentStep={currentStep} />
        </div>
      </div>

      {/* System training notice */}
      {!result && (
        <div className="max-w-lg mx-auto mb-4">
          <div className="flex items-start gap-3 p-3 rounded-lg bg-amber-500/10 border border-amber-500/20">
            <svg className="w-4 h-4 text-amber-500 flex-shrink-0 mt-0.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v3.75m-9.303 3.376c-.866 1.5.217 3.374 1.948 3.374h14.71c1.73 0 2.813-1.874 1.948-3.374L13.949 3.378c-.866-1.5-3.032-1.5-3.898 0L2.697 16.126zM12 15.75h.007v.008H12v-.008z" />
            </svg>
            <div>
              <p className="text-xs font-medium text-amber-600 dark:text-amber-400">Sustav se trenutno trenira</p>
              <p className="text-[11px] text-amber-600/80 dark:text-amber-400/70 mt-0.5">
                Analiza može trajati duže od uobičajenog i postoji mogućnost da ne uspije iz prvog pokušaja. Ako analiza ne uspije, pokušajte ponovno.
              </p>
            </div>
          </div>
        </div>
      )}

      {/* Upload state */}
      {!result && !isLoading && (
        <div className="max-w-lg mx-auto space-y-6">
          {/* Mode selector */}
          <div className="flex justify-center">
            <div className="inline-flex bg-card border border-border rounded-xl p-1">
              <button
                onClick={() => setMode("individual")}
                className={cn(
                  "px-4 py-2 rounded-lg text-sm font-medium transition-all",
                  mode === "individual"
                    ? "bg-accent text-white shadow-sm"
                    : "text-muted hover:text-foreground"
                )}
              >
                Pojedinacna analiza
              </button>
              <button
                onClick={() => setMode("group")}
                className={cn(
                  "px-4 py-2 rounded-lg text-sm font-medium transition-all",
                  mode === "group"
                    ? "bg-accent text-white shadow-sm"
                    : "text-muted hover:text-foreground"
                )}
              >
                Skupna analiza
              </button>
            </div>
          </div>

          {/* Mode description */}
          <p className="text-xs text-muted text-center">
            {isGroupMode
              ? "Sve datoteke analiziraju se zajedno — sustav trazi nekonzistentnosti među datotekama i daje skupnu ocjenu."
              : "Svaka datoteka analizira se zasebno kao nezavisna inspekcija."}
          </p>

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
          <h3 className="font-heading font-semibold text-lg mb-1 text-center">
            {isGroupMode ? "Skupna forenzička analiza u tijeku" : "Forenzička analiza u tijeku"}
          </h3>
          <p className="text-sm text-muted mb-6 text-center">
            {isGroupMode
              ? `Analiziram ${uploadedFiles.length} datoteka kao skupinu — individualna analiza + usporedba među datotekama.`
              : uploadedFiles.length > 1
                ? `Analiziram ${uploadedFiles.length} datoteka — svaka prolazi zasebnu forenzičku analizu.`
                : "Forenzički moduli provjeravaju autentičnost, detektiraju manipulacije i AI-generirani sadržaj."}
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

      {/* ── GROUP RESULT VIEW ── */}
      {result && isGroupResult && (
        <div className="space-y-6">
          {/* Group overview */}
          <GroupOverviewCard inspection={result} files={groupFiles} />

          {/* Cross-image findings */}
          {result.crossImageReport && (result.crossImageReport?.findings?.length ?? 0) > 0 && (
            <CrossImageFindings report={result.crossImageReport} files={groupFiles} />
          )}

          {/* Per-file grid */}
          <div>
            <h3 className="font-heading font-semibold text-base mb-3">Rezultati po datoteci</h3>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              {groupFiles.map((file, idx) => {
                const fr = file.forensicResult;
                const isExpanded = expandedFileIndex === idx;
                const riskLevel = fr?.overallRiskLevel || "Low";
                const riskColor = riskLevel === "Critical" ? "border-red-500" : riskLevel === "High" ? "border-orange-500" : riskLevel === "Medium" ? "border-amber-500" : "border-green-500";
                const riskBg = riskLevel === "Critical" ? "bg-red-500" : riskLevel === "High" ? "bg-orange-500" : riskLevel === "Medium" ? "bg-amber-500" : "bg-green-500";

                return (
                  <div key={idx}>
                    <button
                      onClick={() => setExpandedFileIndex(isExpanded ? null : idx)}
                      className={cn(
                        "w-full bg-card border-2 rounded-xl overflow-hidden text-left transition-all hover:shadow-md",
                        isExpanded ? riskColor : "border-border"
                      )}
                    >
                      <div className="flex items-center gap-3 p-3">
                        <div className="w-16 h-16 flex-shrink-0 rounded-lg overflow-hidden bg-card">
                          {file.url && file.fileName?.match(/\.(jpe?g|png|webp|heic)$/i) ? (
                            <img src={file.url} alt={file.fileName} className="w-full h-full object-cover" />
                          ) : (
                            <div className="w-full h-full flex items-center justify-center text-muted">
                              <svg className="w-8 h-8" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" /></svg>
                            </div>
                          )}
                        </div>
                        <div className="flex-1 min-w-0">
                          <p className="text-sm font-medium truncate">{file.fileName}</p>
                          <div className="flex items-center gap-2 mt-1">
                            <span className={cn("w-2 h-2 rounded-full", riskBg)} />
                            <span className="text-xs text-muted">
                              {fr ? `${fr.overallRiskScore100}% rizik` : "U obradi..."}
                            </span>
                          </div>
                        </div>
                        <svg className={cn("w-5 h-5 text-muted transition-transform", isExpanded && "rotate-180")} fill="none" viewBox="0 0 24 24" stroke="currentColor">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
                        </svg>
                      </div>
                    </button>

                    {/* Expanded detail */}
                    {isExpanded && fr && (
                      <div className="mt-2 bg-card border border-border rounded-xl p-4 space-y-4">
                        <VerdictDashboard
                          riskScore={fr.overallRiskScore}
                          riskLevel={fr.overallRiskLevel}
                          c2paStatus={fr.c2paStatus}
                          predictedSource={fr.predictedSource}
                          sourceConfidence={fr.sourceConfidence}
                          totalProcessingTimeMs={fr.totalProcessingTimeMs}
                          inspectionId={result.id}
                          verdictProbabilities={fr.verdictProbabilities}
                          fileName={file.fileName}
                        />
                        {fr.modules && fr.modules.length > 0 && (
                          <ForensicModuleTable result={fr} originalImageUrl={file.url} pagePreviewUrls={fr.pagePreviewUrls} />
                        )}
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          </div>

          {/* Actions */}
          <div className="flex gap-3">
            <button onClick={handleReset} className="px-6 py-2.5 bg-accent text-white rounded-xl font-medium text-sm hover:bg-accent-hover transition-colors">
              Nova analiza
            </button>
            <Link href={`/inspections/${result.id}`} className="px-6 py-2.5 bg-card border border-border rounded-xl font-medium text-sm hover:bg-card-hover transition-colors inline-flex items-center gap-2">
              Detaljan pregled
            </Link>
          </div>
        </div>
      )}

      {/* ── INDIVIDUAL RESULT VIEW (existing) ── */}
      {result && !isGroupResult && (
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
          {result.decisionTraces && (result.decisionTraces?.length ?? 0) > 0 && (
            <DecisionTrace traces={result.decisionTraces} />
          )}
          <div className="flex gap-3">
            <button onClick={handleReset} className="px-6 py-2.5 bg-accent text-white rounded-xl font-medium text-sm hover:bg-accent-hover transition-colors">
              Nova analiza
            </button>
            {allResults.length > 1 && (
              <Link href="/inspections" className="px-6 py-2.5 bg-accent text-white rounded-xl font-medium text-sm hover:bg-accent-hover transition-colors inline-flex items-center gap-2">
                Pogledaj sve analize ({allResults.length})
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
