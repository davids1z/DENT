"use client";

import { useState, useRef, useEffect, useCallback } from "react";
import type { BboxRect } from "@/lib/findingBbox";
import { cn } from "@/lib/cn";

interface DocumentPageViewerProps {
  pagePreviewUrls: string[];
  /** Active page bboxes to overlay (PDF coordinate space) */
  activeBboxes?: { rects: BboxRect[]; label?: string }[];
  /** Active page index (0-based), controlled externally */
  activePage?: number;
  onPageChange?: (page: number) => void;
  /** Version diff heatmap (base64 JPEG) for diff tab */
  diffHeatmapB64?: string | null;
  /** Metadata summary for meta tab */
  metadataSummary?: { label: string; value: string }[];
}

const RENDER_DPI = 150;
const PDF_PPI = 72;
const SCALE = RENDER_DPI / PDF_PPI;

type ViewTab = "pages" | "diff" | "meta";

export function DocumentPageViewer({
  pagePreviewUrls,
  activeBboxes,
  activePage: controlledPage,
  onPageChange,
  diffHeatmapB64,
  metadataSummary,
}: DocumentPageViewerProps) {
  const [internalPage, setInternalPage] = useState(0);
  const activePage = controlledPage ?? internalPage;
  const setActivePage = useCallback((p: number) => {
    setInternalPage(p);
    onPageChange?.(p);
  }, [onPageChange]);

  const [tab, setTab] = useState<ViewTab>("pages");
  const [imgNatural, setImgNatural] = useState<{ w: number; h: number } | null>(null);
  const imgRef = useRef<HTMLImageElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);

  const pageUrl = pagePreviewUrls[activePage];
  const totalPages = pagePreviewUrls.length;

  // Reset natural size when page changes
  useEffect(() => { setImgNatural(null); }, [activePage]);

  function handleImageLoad() {
    const img = imgRef.current;
    if (img) setImgNatural({ w: img.naturalWidth, h: img.naturalHeight });
  }

  function scaleBbox(rect: BboxRect) {
    if (!imgNatural || !imgRef.current) return null;
    const displayScale = imgRef.current.clientWidth / imgNatural.w;
    return {
      left: rect.x0 * SCALE * displayScale,
      top: rect.y0 * SCALE * displayScale,
      width: (rect.x1 - rect.x0) * SCALE * displayScale,
      height: (rect.y1 - rect.y0) * SCALE * displayScale,
    };
  }

  return (
    <div className="flex flex-col h-full">
      {/* Tabs */}
      <div className="flex items-center gap-1 px-2 py-1.5 border-b border-border bg-card/50">
        {(["pages", "diff", "meta"] as ViewTab[]).map(t => {
          const disabled = (t === "diff" && !diffHeatmapB64) || (t === "meta" && (!metadataSummary || metadataSummary.length === 0));
          const labels: Record<ViewTab, string> = { pages: "Stranice", diff: "Diff", meta: "Metapodaci" };
          return (
            <button
              key={t}
              onClick={() => !disabled && setTab(t)}
              disabled={disabled}
              className={cn(
                "px-3 py-1 text-[11px] font-medium rounded-md transition-colors",
                tab === t ? "bg-foreground text-background" : disabled ? "text-muted/40 cursor-not-allowed" : "text-muted hover:bg-card-hover"
              )}
            >
              {labels[t]}
            </button>
          );
        })}
        {/* Page counter */}
        {tab === "pages" && totalPages > 0 && (
          <span className="ml-auto text-[10px] text-muted">
            {activePage + 1} / {totalPages}
          </span>
        )}
      </div>

      {/* Content area */}
      <div ref={containerRef} className="flex-1 overflow-auto bg-card/30 relative">
        {tab === "pages" && pageUrl && (
          <div className="relative inline-block">
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img
              ref={imgRef}
              src={pageUrl}
              alt={`Stranica ${activePage + 1}`}
              className="block w-full"
              onLoad={handleImageLoad}
            />
            {/* Bbox overlays */}
            {imgNatural && activeBboxes?.map((group, gi) =>
              group.rects.map((rect, ri) => {
                const s = scaleBbox(rect);
                if (!s) return null;
                return (
                  <div
                    key={`${gi}-${ri}`}
                    className="absolute border-2 border-red-500 bg-red-500/10 pointer-events-none transition-all duration-200"
                    style={{ left: s.left, top: s.top, width: s.width, height: s.height }}
                  >
                    {ri === 0 && group.label && (
                      <span className="absolute -top-5 left-0 text-[9px] font-medium text-red-500 bg-red-500/10 px-1 rounded whitespace-nowrap">
                        {group.label}
                      </span>
                    )}
                  </div>
                );
              })
            )}
          </div>
        )}

        {tab === "diff" && diffHeatmapB64 && (
          <div className="p-4 space-y-3">
            <p className="text-xs text-muted">Pixel razlike između verzija dokumenta. Crvena područja označavaju promjene.</p>
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img
              src={`data:image/jpeg;base64,${diffHeatmapB64}`}
              alt="Version diff heatmap"
              className="w-full rounded-lg border border-border"
            />
          </div>
        )}

        {tab === "meta" && metadataSummary && (
          <div className="p-4 space-y-1.5">
            {metadataSummary.map((item, i) => (
              <div key={i} className="flex items-start gap-2 py-1">
                <span className="text-[11px] text-muted flex-shrink-0 w-28">{item.label}</span>
                <span className="text-[11px] text-foreground break-all">{item.value}</span>
              </div>
            ))}
          </div>
        )}

        {tab === "pages" && !pageUrl && (
          <div className="flex items-center justify-center h-48 text-muted text-sm">
            Nema pregleda stranica
          </div>
        )}
      </div>

      {/* Thumbnail strip */}
      {tab === "pages" && totalPages > 1 && (
        <div className="flex gap-1.5 p-2 border-t border-border bg-card/50 overflow-x-auto">
          {pagePreviewUrls.map((url, i) => (
            <button
              key={i}
              onClick={() => setActivePage(i)}
              className={cn(
                "flex-shrink-0 w-12 h-16 rounded border overflow-hidden transition-all",
                activePage === i ? "border-foreground ring-1 ring-foreground/30" : "border-border opacity-60 hover:opacity-100"
              )}
            >
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img src={url} alt={`${i + 1}`} className="w-full h-full object-cover" />
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
