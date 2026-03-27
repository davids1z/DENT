"use client";

import { useState, useRef } from "react";
import { cn } from "@/lib/cn";
import { ImageLightbox } from "@/components/ImageLightbox";

export interface DocumentPreviewProps {
  imageUrl: string;
  fileName?: string;
  pagePreviewUrls?: string[] | null;
}

export function DocumentPreview({
  imageUrl,
  fileName,
  pagePreviewUrls,
}: DocumentPreviewProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [activePageIndex, setActivePageIndex] = useState(0);
  const [lightboxSrc, setLightboxSrc] = useState<string | null>(null);

  const docName = fileName || imageUrl.split("/").pop() || "Dokument";
  const ext = docName.split(".").pop()?.toUpperCase() || "PDF";
  const hasPagePreviews = pagePreviewUrls && pagePreviewUrls.length > 0;

  // If we have rendered page previews, show them like images
  if (hasPagePreviews) {
    const activePageUrl = pagePreviewUrls[activePageIndex] || pagePreviewUrls[0];
    return (
      <div className="bg-card border border-border rounded-xl overflow-hidden" ref={containerRef}>
        {lightboxSrc && <ImageLightbox src={lightboxSrc} alt={docName} onClose={() => setLightboxSrc(null)} />}
        {/* Main page image */}
        <div className="bg-card cursor-pointer" onClick={() => setLightboxSrc(activePageUrl)}>
          <img
            src={activePageUrl}
            alt={`Stranica ${activePageIndex + 1}`}
            className="w-full h-auto object-contain"
          />
        </div>

        {/* Page thumbnails (if multi-page) */}
        {pagePreviewUrls.length > 1 && (
          <div className="flex gap-1.5 px-3 py-2 overflow-x-auto border-t border-border bg-card/50">
            {pagePreviewUrls.map((url, i) => (
              <button
                key={i}
                onClick={() => setActivePageIndex(i)}
                className={cn(
                  "flex-shrink-0 w-12 h-16 rounded border-2 overflow-hidden transition-all",
                  activePageIndex === i
                    ? "border-accent shadow-sm"
                    : "border-transparent opacity-50 hover:opacity-80"
                )}
              >
                <img src={url} alt={`Str. ${i + 1}`} className="w-full h-full object-cover object-top" />
              </button>
            ))}
          </div>
        )}

        {/* Footer */}
        <div className="flex items-center justify-between px-3 py-2 border-t border-border">
          <span className="text-[10px] text-muted">
            {docName} — Stranica {activePageIndex + 1}/{pagePreviewUrls.length}
          </span>
          <a
            href={imageUrl}
            target="_blank"
            rel="noopener noreferrer"
            className="text-[10px] text-accent hover:text-accent-hover transition-colors font-medium"
          >
            Preuzmi original
          </a>
        </div>
      </div>
    );
  }

  // Fallback: no page previews (legacy or rendering failed)
  return (
    <div className="bg-card border border-border rounded-xl overflow-hidden" ref={containerRef}>
      <div className="flex flex-col items-center justify-center py-12 px-6 bg-gradient-to-b from-card to-background">
        <div className="relative mb-4">
          <svg className="w-20 h-20 text-muted-light" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={0.8}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M19.5 14.25v-2.625a3.375 3.375 0 00-3.375-3.375h-1.5A1.125 1.125 0 0113.5 7.125v-1.5a3.375 3.375 0 00-3.375-3.375H8.25m2.25 0H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 00-9-9z" />
          </svg>
          <span className="absolute bottom-1 right-0 bg-accent text-white text-[10px] font-bold px-1.5 py-0.5 rounded">
            {ext}
          </span>
        </div>
        <h4 className="text-sm font-medium text-foreground mb-1 text-center break-all max-w-xs">
          {docName}
        </h4>
        <p className="text-xs text-muted">Analizirani dokument</p>
      </div>
      <div className="flex items-center justify-between px-3 py-2 border-t border-border">
        <span className="text-[10px] text-muted">
          Datoteka: {docName}
        </span>
        <a
          href={imageUrl}
          target="_blank"
          rel="noopener noreferrer"
          className="text-[10px] text-accent hover:text-accent-hover transition-colors font-medium"
        >
          Preuzmi original
        </a>
      </div>
    </div>
  );
}
