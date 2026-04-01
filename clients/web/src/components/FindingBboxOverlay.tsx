"use client";

import { useState, useRef, useEffect } from "react";
import type { BboxRect } from "@/lib/findingBbox";

interface FindingBboxOverlayProps {
  /** URL of the PDF page preview image */
  pagePreviewUrl: string;
  /** Bounding boxes in PDF coordinate space (points, 1pt = 1/72 inch) */
  bboxes: BboxRect[];
  /** Label to show above the overlay */
  label?: string;
  /** Page number (1-based) */
  pageNumber: number;
  /** Close callback */
  onClose: () => void;
}

// PDF pages are rendered at 150 DPI in pipeline.py
const RENDER_DPI = 150;
const PDF_POINTS_PER_INCH = 72;
const SCALE_FACTOR = RENDER_DPI / PDF_POINTS_PER_INCH; // 2.083

export function FindingBboxOverlay({
  pagePreviewUrl,
  bboxes,
  label,
  pageNumber,
  onClose,
}: FindingBboxOverlayProps) {
  const imgRef = useRef<HTMLImageElement>(null);
  const [imgSize, setImgSize] = useState<{ natural: { w: number; h: number }; display: { w: number; h: number } } | null>(null);

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  function handleImageLoad() {
    const img = imgRef.current;
    if (!img) return;
    setImgSize({
      natural: { w: img.naturalWidth, h: img.naturalHeight },
      display: { w: img.clientWidth, h: img.clientHeight },
    });
  }

  // Scale PDF points → rendered pixels → display pixels
  function scaleRect(rect: BboxRect) {
    if (!imgSize) return null;
    const displayScale = imgSize.display.w / imgSize.natural.w;
    return {
      left: rect.x0 * SCALE_FACTOR * displayScale,
      top: rect.y0 * SCALE_FACTOR * displayScale,
      width: (rect.x1 - rect.x0) * SCALE_FACTOR * displayScale,
      height: (rect.y1 - rect.y0) * SCALE_FACTOR * displayScale,
    };
  }

  return (
    // Backdrop
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm"
      onClick={onClose}
    >
      {/* Modal */}
      <div
        className="relative max-w-[90vw] max-h-[90vh] bg-background rounded-xl border border-border shadow-2xl overflow-hidden"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-4 py-2.5 border-b border-border bg-card">
          <div className="flex items-center gap-2">
            <span className="text-xs font-medium text-foreground">
              Stranica {pageNumber}
            </span>
            {label && (
              <span className="text-[10px] px-2 py-0.5 rounded-full bg-red-500/10 text-red-500 border border-red-500/20">
                {label}
              </span>
            )}
            <span className="text-[10px] text-muted">
              {bboxes.length} {bboxes.length === 1 ? "područje" : "područja"}
            </span>
          </div>
          <button
            onClick={onClose}
            className="w-7 h-7 flex items-center justify-center rounded-md hover:bg-card-hover transition-colors text-muted"
          >
            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        {/* Image + Overlays */}
        <div className="relative overflow-auto" style={{ maxHeight: "calc(90vh - 48px)" }}>
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            ref={imgRef}
            src={pagePreviewUrl}
            alt={`Stranica ${pageNumber}`}
            className="block max-w-full"
            onLoad={handleImageLoad}
            style={{ maxHeight: "85vh" }}
          />

          {/* Bbox overlays */}
          {imgSize && bboxes.map((bbox, i) => {
            const scaled = scaleRect(bbox);
            if (!scaled) return null;
            return (
              <div
                key={i}
                className="absolute border-2 border-red-500 bg-red-500/10 pointer-events-none"
                style={{
                  left: scaled.left,
                  top: scaled.top,
                  width: scaled.width,
                  height: scaled.height,
                }}
              >
                {/* Corner markers for visibility */}
                <div className="absolute -top-0.5 -left-0.5 w-2 h-2 bg-red-500 rounded-full" />
                <div className="absolute -top-0.5 -right-0.5 w-2 h-2 bg-red-500 rounded-full" />
                <div className="absolute -bottom-0.5 -left-0.5 w-2 h-2 bg-red-500 rounded-full" />
                <div className="absolute -bottom-0.5 -right-0.5 w-2 h-2 bg-red-500 rounded-full" />
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
