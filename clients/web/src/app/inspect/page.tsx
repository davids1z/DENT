"use client";

import { useState } from "react";
import { uploadInspection, type Inspection } from "@/lib/api";
import { ImageUpload } from "@/components/ImageUpload";
import { DamageReport } from "@/components/DamageReport";

export default function InspectPage() {
  const [isLoading, setIsLoading] = useState(false);
  const [result, setResult] = useState<Inspection | null>(null);
  const [error, setError] = useState<string | null>(null);

  const handleUpload = async (file: File) => {
    setIsLoading(true);
    setError(null);
    setResult(null);

    try {
      const inspection = await uploadInspection(file);
      setResult(inspection);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Doslo je do greske");
    } finally {
      setIsLoading(false);
    }
  };

  const handleReset = () => {
    setResult(null);
    setError(null);
  };

  return (
    <div className="max-w-5xl mx-auto px-6 py-8">
      <div className="mb-8">
        <h1 className="text-3xl font-bold mb-2">Nova inspekcija</h1>
        <p className="text-muted">
          Uploadajte fotografiju ostecenja na vozilu za AI analizu
        </p>
      </div>

      {!result ? (
        <div className="space-y-4">
          <ImageUpload onUpload={handleUpload} isLoading={isLoading} />

          {error && (
            <div className="bg-red-500/10 border border-red-500/20 rounded-xl p-4 text-red-400 text-sm">
              {error}
            </div>
          )}

          {isLoading && (
            <div className="bg-card rounded-2xl border border-border p-6">
              <div className="flex items-center gap-3 mb-4">
                <div className="w-6 h-6 border-2 border-accent border-t-transparent rounded-full animate-spin" />
                <span className="font-medium">AI analizira vase vozilo...</span>
              </div>
              <div className="space-y-2">
                <div className="h-3 skeleton rounded-full w-3/4" />
                <div className="h-3 skeleton rounded-full w-1/2" />
                <div className="h-3 skeleton rounded-full w-2/3" />
              </div>
            </div>
          )}
        </div>
      ) : (
        <div className="space-y-6">
          {/* Image + Report side by side */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            {/* Image */}
            <div className="bg-card rounded-2xl border border-border overflow-hidden">
              <img
                src={result.imageUrl}
                alt="Uploaded vehicle"
                className="w-full h-auto max-h-[500px] object-contain bg-black"
              />
            </div>

            {/* Report */}
            <div>
              <DamageReport inspection={result} />
            </div>
          </div>

          {/* Actions */}
          <div className="flex gap-3">
            <button
              onClick={handleReset}
              className="px-6 py-3 bg-accent hover:bg-accent-hover text-white rounded-xl font-medium transition-colors"
            >
              Nova inspekcija
            </button>
            <button
              onClick={() => window.print()}
              className="px-6 py-3 bg-card border border-border hover:border-accent/30 rounded-xl font-medium transition-colors"
            >
              Isprintaj izvjestaj
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
