"use client";

import { useState, useRef } from "react";
import type { DamageDetection, BoundingBox } from "@/lib/api";
import {
  parseBoundingBox,
  findingCategoryLabel,
  severityLabel,
} from "@/lib/api";
import { cn } from "@/lib/cn";
import { ImageLightbox } from "@/components/ImageLightbox";

export interface ImageOverlayProps {
  imageUrl: string;
  damages: DamageDetection[];
  selectedIndex?: number | null;
  onSelectDamage?: (index: number | null) => void;
  activeImageIndex?: number;
}

interface ParsedDamage {
  damage: DamageDetection;
  box: BoundingBox;
  index: number;
  color: string;
}

function severityToColor(severity: string): string {
  switch (severity) {
    case "Critical": return "#ef4444";
    case "Severe": return "#f97316";
    case "Moderate": return "#f59e0b";
    case "Minor": return "#22c55e";
    default: return "#71717a";
  }
}

function FindingTooltip({ damage }: { damage: ParsedDamage }) {
  const { box, damage: d, index, color } = damage;
  const tooltipLeft = `${(box.x + box.w / 2) * 100}%`;
  const tooltipTop = `${box.y * 100}%`;

  return (
    <div
      className="absolute z-10 pointer-events-none"
      style={{
        left: tooltipLeft,
        top: tooltipTop,
        transform: "translate(-50%, -100%) translateY(-8px)",
      }}
    >
      <div className="bg-background border border-border rounded-lg px-3 py-2 text-xs shadow-lg">
        <div className="flex items-center gap-2 mb-1">
          <div className="w-2 h-2 rounded-full" style={{ backgroundColor: color }} />
          <span className="font-medium">#{index + 1} {findingCategoryLabel(d.damageCause)}</span>
        </div>
        <div className="text-muted">
          {severityLabel(d.severity)}
        </div>
      </div>
    </div>
  );
}

function Legend() {
  return (
    <div className="flex items-center gap-2">
      <LegendItem color="#22c55e" label="Niska" />
      <LegendItem color="#f59e0b" label="Umjerena" />
      <LegendItem color="#f97316" label="Visoka" />
      <LegendItem color="#ef4444" label="Kriticna" />
    </div>
  );
}

function LegendItem({ color, label }: { color: string; label: string }) {
  return (
    <div className="flex items-center gap-1">
      <div className="w-2.5 h-2.5 rounded-sm" style={{ backgroundColor: color, opacity: 0.7 }} />
      <span className="text-[10px] text-muted">{label}</span>
    </div>
  );
}

export function ImageOverlay({
  imageUrl,
  damages,
  selectedIndex = null,
  onSelectDamage,
  activeImageIndex = 0,
}: ImageOverlayProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [showOverlay, setShowOverlay] = useState(true);
  const [hoveredIndex, setHoveredIndex] = useState<number | null>(null);
  const [imageLoaded, setImageLoaded] = useState(false);
  const [lightboxSrc, setLightboxSrc] = useState<string | null>(null);

  const parsedDamages: ParsedDamage[] = damages
    .map((d, i) => {
      const box = parseBoundingBox(d.boundingBox);
      if (!box) return null;
      if (box.imageIndex !== activeImageIndex) return null;
      const color = severityToColor(d.severity);
      return { damage: d, box, index: i, color };
    })
    .filter((d): d is ParsedDamage => d !== null);

  const hasBoundingBoxes = parsedDamages.length > 0;

  return (
    <div className="bg-card border border-border rounded-xl overflow-hidden" ref={containerRef}>
      {lightboxSrc && <ImageLightbox src={lightboxSrc} alt="Analizirani sadrzaj" onClose={() => setLightboxSrc(null)} />}
      <div className="relative">
        <div
          className="cursor-pointer"
          onClick={() => {
            if (!hasBoundingBoxes || !showOverlay) setLightboxSrc(imageUrl);
          }}
        >
          <img
            src={imageUrl}
            alt="Analizirani sadrzaj"
            className="w-full h-auto object-contain bg-card"
            onLoad={() => setImageLoaded(true)}
          />
        </div>

        {hasBoundingBoxes && showOverlay && imageLoaded && (
          <svg
            className="absolute inset-0 w-full h-full pointer-events-none"
            viewBox="0 0 1 1"
            preserveAspectRatio="none"
          >
            {parsedDamages.map(({ box, index, color }) => {
              const isActive = selectedIndex === index || hoveredIndex === index;
              const opacity = selectedIndex !== null && selectedIndex !== index ? 0.15 : isActive ? 0.35 : 0.2;
              const strokeOpacity = selectedIndex !== null && selectedIndex !== index ? 0.3 : isActive ? 1 : 0.6;

              return (
                <g key={index}>
                  <rect
                    x={box.x}
                    y={box.y}
                    width={box.w}
                    height={box.h}
                    fill={color}
                    fillOpacity={opacity}
                    stroke={color}
                    strokeWidth={isActive ? 0.004 : 0.002}
                    strokeOpacity={strokeOpacity}
                    rx={0.005}
                    className="pointer-events-auto cursor-pointer"
                    onMouseEnter={() => setHoveredIndex(index)}
                    onMouseLeave={() => setHoveredIndex(null)}
                    onClick={(e) => {
                      e.preventDefault();
                      e.stopPropagation();
                      onSelectDamage?.(selectedIndex === index ? null : index);
                    }}
                  />
                  <g
                    className="pointer-events-auto cursor-pointer"
                    onMouseEnter={() => setHoveredIndex(index)}
                    onMouseLeave={() => setHoveredIndex(null)}
                    onClick={(e) => {
                      e.preventDefault();
                      e.stopPropagation();
                      onSelectDamage?.(selectedIndex === index ? null : index);
                    }}
                  >
                    <circle
                      cx={box.x + box.w - 0.012}
                      cy={box.y + 0.012}
                      r={0.018}
                      fill={color}
                      fillOpacity={0.95}
                    />
                    <text
                      x={box.x + box.w - 0.012}
                      y={box.y + 0.012}
                      textAnchor="middle"
                      dominantBaseline="central"
                      fill="white"
                      fontSize={0.018}
                      fontWeight="bold"
                      fontFamily="system-ui, sans-serif"
                    >
                      {index + 1}
                    </text>
                  </g>
                </g>
              );
            })}
          </svg>
        )}

        {hoveredIndex !== null && showOverlay && parsedDamages.find((d) => d.index === hoveredIndex) && (
          <FindingTooltip damage={parsedDamages.find((d) => d.index === hoveredIndex)!} />
        )}
      </div>

      <div className="flex items-center justify-between px-3 py-2 border-t border-border">
        <div className="flex items-center gap-3">
          {hasBoundingBoxes && (
            <>
              <button
                onClick={() => setShowOverlay(!showOverlay)}
                className={cn(
                  "flex items-center gap-1.5 text-xs transition-colors",
                  showOverlay ? "text-foreground" : "text-muted hover:text-foreground"
                )}
              >
                <div className={cn(
                  "w-3.5 h-3.5 rounded border flex items-center justify-center",
                  showOverlay ? "bg-accent/10 border-accent" : "border-border"
                )}>
                  {showOverlay && (
                    <svg className="w-2.5 h-2.5 text-accent" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={3}>
                      <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
                    </svg>
                  )}
                </div>
                Prekrivanje
              </button>
              <div className="h-3 w-px bg-border" />
              <Legend />
            </>
          )}
        </div>
        <button
          onClick={() => setLightboxSrc(imageUrl)}
          className="text-[10px] text-muted hover:text-foreground transition-colors"
        >
          Puna velicina
        </button>
      </div>
    </div>
  );
}
