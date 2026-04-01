"use client";

import { useEffect, useCallback, useState } from "react";
import { createPortal } from "react-dom";

interface ImageLightboxProps {
  src: string;
  alt?: string;
  onClose: () => void;
  allImages?: string[];
  onNavigate?: (url: string) => void;
}

function LightboxContent({ src, alt = "", onClose, allImages, onNavigate }: ImageLightboxProps) {
  const [currentSrc, setCurrentSrc] = useState(src);
  const hasMultiple = allImages && allImages.length > 1;
  const currentIndex = hasMultiple ? allImages.indexOf(currentSrc) : -1;
  const canPrev = hasMultiple && currentIndex > 0;
  const canNext = hasMultiple && currentIndex < allImages.length - 1;

  useEffect(() => { setCurrentSrc(src); }, [src]);

  const goTo = useCallback((url: string) => {
    setCurrentSrc(url);
    onNavigate?.(url);
  }, [onNavigate]);

  const goPrev = useCallback(() => {
    if (canPrev && allImages) goTo(allImages[currentIndex - 1]);
  }, [canPrev, allImages, currentIndex, goTo]);

  const goNext = useCallback(() => {
    if (canNext && allImages) goTo(allImages[currentIndex + 1]);
  }, [canNext, allImages, currentIndex, goTo]);

  useEffect(() => {
    const handleKey = (e: KeyboardEvent) => {
      e.preventDefault();
      e.stopPropagation();
      if (e.key === "Escape") onClose();
      if (e.key === "ArrowLeft") goPrev();
      if (e.key === "ArrowRight") goNext();
    };

    // Block ALL scrolling and interaction behind overlay
    const scrollY = window.scrollY;
    document.body.style.position = "fixed";
    document.body.style.top = `-${scrollY}px`;
    document.body.style.left = "0";
    document.body.style.right = "0";
    document.body.style.overflow = "hidden";

    document.addEventListener("keydown", handleKey, true);

    return () => {
      document.removeEventListener("keydown", handleKey, true);
      document.body.style.position = "";
      document.body.style.top = "";
      document.body.style.left = "";
      document.body.style.right = "";
      document.body.style.overflow = "";
      window.scrollTo(0, scrollY);
    };
  }, [onClose, goPrev, goNext]);

  return (
    <div
      className="fixed inset-0 flex items-center justify-center bg-black/80 backdrop-blur-lg"
      style={{ zIndex: 99999 }}
      onClick={onClose}
    >
      {/* Close */}
      <button
        onClick={onClose}
        className="absolute top-5 right-5 z-10 w-10 h-10 rounded-full bg-white/10 hover:bg-white/20 flex items-center justify-center transition-colors"
      >
        <svg className="w-5 h-5 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
        </svg>
      </button>

      {/* Counter */}
      {hasMultiple && currentIndex >= 0 && (
        <div className="absolute top-5 left-5 text-white/60 text-sm font-mono">
          {currentIndex + 1} / {allImages.length}
        </div>
      )}

      {/* Prev */}
      {canPrev && (
        <button
          onClick={(e) => { e.stopPropagation(); goPrev(); }}
          className="absolute left-4 top-1/2 -translate-y-1/2 z-10 w-12 h-12 rounded-full bg-white/10 hover:bg-white/20 flex items-center justify-center transition-colors"
        >
          <svg className="w-6 h-6 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M15 19l-7-7 7-7" />
          </svg>
        </button>
      )}

      {/* Next */}
      {canNext && (
        <button
          onClick={(e) => { e.stopPropagation(); goNext(); }}
          className="absolute right-4 top-1/2 -translate-y-1/2 z-10 w-12 h-12 rounded-full bg-white/10 hover:bg-white/20 flex items-center justify-center transition-colors"
        >
          <svg className="w-6 h-6 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M9 5l7 7-7 7" />
          </svg>
        </button>
      )}

      {/* Image */}
      <img
        src={currentSrc}
        alt={alt}
        className="max-w-[92vw] max-h-[92dvh] object-contain cursor-default select-none"
        onClick={(e) => e.stopPropagation()}
        draggable={false}
      />
    </div>
  );
}

export function ImageLightbox(props: ImageLightboxProps) {
  const [mounted, setMounted] = useState(false);
  useEffect(() => { setMounted(true); }, []);
  if (!mounted) return null;
  return createPortal(<LightboxContent {...props} />, document.body);
}
