"use client";

import { useState } from "react";
import { cn } from "@/lib/cn";

interface ElaHeatmapOverlayProps {
  originalImageUrl: string;
  heatmapUrl: string;
}

export function ElaHeatmapOverlay({
  originalImageUrl,
  heatmapUrl,
}: ElaHeatmapOverlayProps) {
  const [showHeatmap, setShowHeatmap] = useState(false);
  const [opacity, setOpacity] = useState(50);

  return (
    <div className="bg-card border border-border rounded-xl overflow-hidden">
      <div className="flex items-center justify-between px-4 py-2.5 border-b border-border">
        <div className="flex items-center gap-2">
          <HeatmapIcon />
          <span className="text-sm font-medium">ELA Analiza</span>
          <span className="text-[10px] text-muted">(Error Level Analysis)</span>
        </div>
        <button
          onClick={() => setShowHeatmap(!showHeatmap)}
          className={cn(
            "px-3 py-1 text-xs font-medium rounded-full border transition-colors",
            showHeatmap
              ? "bg-orange-50 border-orange-200 text-orange-700"
              : "bg-card border-border text-muted hover:bg-card-hover"
          )}
        >
          {showHeatmap ? "Sakrij ELA" : "Prikazi ELA"}
        </button>
      </div>

      <div className="relative">
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img
          src={originalImageUrl}
          alt="Originalna slika"
          className="w-full h-auto"
        />
        {showHeatmap && (
          /* eslint-disable-next-line @next/next/no-img-element */
          <img
            src={heatmapUrl}
            alt="ELA toplinska mapa"
            className="absolute inset-0 w-full h-full object-cover pointer-events-none"
            style={{ opacity: opacity / 100 }}
          />
        )}
      </div>

      {showHeatmap && (
        <div className="px-4 py-2.5 border-t border-border flex items-center gap-3">
          <span className="text-xs text-muted flex-shrink-0">Prozirnost</span>
          <input
            type="range"
            min={0}
            max={100}
            value={opacity}
            onChange={(e) => setOpacity(Number(e.target.value))}
            className="flex-1 h-1.5 bg-border rounded-full appearance-none cursor-pointer accent-orange-500"
          />
          <span className="text-xs font-mono text-muted w-8 text-right">
            {opacity}%
          </span>
        </div>
      )}
    </div>
  );
}

function HeatmapIcon() {
  return (
    <svg
      className="w-4 h-4 text-orange-500"
      fill="none"
      viewBox="0 0 24 24"
      stroke="currentColor"
      strokeWidth={1.5}
    >
      <path
        strokeLinecap="round"
        strokeLinejoin="round"
        d="M15.362 5.214A8.252 8.252 0 0112 21 8.25 8.25 0 016.038 7.048 8.287 8.287 0 009 9.6a8.983 8.983 0 013.361-6.867 8.21 8.21 0 003 2.48z"
      />
      <path
        strokeLinecap="round"
        strokeLinejoin="round"
        d="M12 18a3.75 3.75 0 00.495-7.467 5.99 5.99 0 00-1.925 3.546 5.974 5.974 0 01-2.133-1A3.75 3.75 0 0012 18z"
      />
    </svg>
  );
}
