"use client";

import { useState } from "react";
import { cn } from "@/lib/cn";

interface SpectralHeatmapOverlayProps {
  originalImageUrl: string;
  heatmapUrl: string;
}

export function SpectralHeatmapOverlay({
  originalImageUrl,
  heatmapUrl,
}: SpectralHeatmapOverlayProps) {
  const [showHeatmap, setShowHeatmap] = useState(false);
  const [opacity, setOpacity] = useState(60);

  return (
    <div className="bg-card border border-border rounded-xl overflow-hidden">
      <div className="flex items-center justify-between px-4 py-2.5 border-b border-border">
        <div className="flex items-center gap-2">
          <SpectralIcon />
          <span className="text-sm font-medium">Spektralna Forenzika</span>
          <span className="text-[10px] text-muted">
            (Frekvencijsko-fazna analiza)
          </span>
        </div>
        <button
          onClick={() => setShowHeatmap(!showHeatmap)}
          className={cn(
            "px-3 py-1 text-xs font-medium rounded-full border transition-colors",
            showHeatmap
              ? "bg-red-500/10 border-red-500/20 text-red-600 dark:text-red-400"
              : "bg-card border-border text-muted hover:bg-card-hover"
          )}
        >
          {showHeatmap ? "Sakrij spektralnu mapu" : "Prikazi spektralnu mapu"}
        </button>
      </div>

      {showHeatmap && (
        <>
          <div className="relative">
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img
              src={originalImageUrl}
              alt="Originalna slika"
              className="w-full h-auto"
            />
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img
              src={heatmapUrl}
              alt="Spektralna toplinska mapa"
              className="absolute inset-0 w-full h-full object-cover pointer-events-none"
              style={{ opacity: opacity / 100 }}
            />
          </div>

          <div className="px-4 py-2.5 border-t border-border space-y-2">
            <div className="flex items-center gap-3">
              <span className="text-xs text-muted flex-shrink-0">
                Prozirnost
              </span>
              <input
                type="range"
                min={0}
                max={100}
                value={opacity}
                onChange={(e) => setOpacity(Number(e.target.value))}
                className="flex-1 h-1.5 bg-border rounded-full appearance-none cursor-pointer accent-red-500"
              />
              <span className="text-xs font-mono text-muted w-8 text-right">
                {opacity}%
              </span>
            </div>
            <p className="text-xs text-muted">
              Crvena podrucja oznacavaju frekvencijske anomalije tipicne za AI
              generirane slike — niska fazna koherencija, plosnati spektar i
              deficit visokih frekvencija. Plava podrucja imaju prirodnu
              frekvencijsku distribuciju.
            </p>
          </div>
        </>
      )}
    </div>
  );
}

function SpectralIcon() {
  return (
    <svg
      className="w-4 h-4 text-red-500"
      fill="none"
      viewBox="0 0 24 24"
      stroke="currentColor"
      strokeWidth={1.5}
    >
      <path
        strokeLinecap="round"
        strokeLinejoin="round"
        d="M9.348 14.652a3.75 3.75 0 010-5.304m5.304 0a3.75 3.75 0 010 5.304m-7.425 2.121a6.75 6.75 0 010-9.546m9.546 0a6.75 6.75 0 010 9.546M5.106 18.894c-3.808-3.807-3.808-9.98 0-13.788m13.788 0c3.808 3.807 3.808 9.98 0 13.788M12 12h.008v.008H12V12zm.375 0a.375.375 0 11-.75 0 .375.375 0 01.75 0z"
      />
    </svg>
  );
}
