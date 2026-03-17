"use client";

import { useState } from "react";
import { ImageUpload } from "@/components/ImageUpload";

interface UploadFallbackProps {
  onUpload: (files: File[]) => void;
  isLoading: boolean;
}

export function UploadFallback({ onUpload, isLoading }: UploadFallbackProps) {
  const [expanded, setExpanded] = useState(false);

  return (
    <div className="rounded-xl border border-amber-200 bg-amber-50/50 p-6 space-y-4">
      <div className="text-center space-y-3">
        <div className="w-12 h-12 rounded-xl bg-amber-100 flex items-center justify-center mx-auto">
          <svg
            className="w-6 h-6 text-amber-600"
            fill="none"
            viewBox="0 0 24 24"
            stroke="currentColor"
            strokeWidth={1.5}
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              d="M3 16.5v2.25A2.25 2.25 0 005.25 21h13.5A2.25 2.25 0 0021 18.75V16.5m-13.5-9L12 3m0 0l4.5 4.5M12 3v13.5"
            />
          </svg>
        </div>

        <div>
          <div className="flex items-center justify-center gap-2 mb-1">
            <p className="text-sm font-semibold text-foreground">
              Ucitaj iz galerije
            </p>
            <span className="inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-medium bg-amber-200 text-amber-800">
              Nepotvrden izvor
            </span>
          </div>
          <p className="text-xs text-amber-800 max-w-xs mx-auto">
            Uploadane slike podlijezu strozoj forenzickoj analizi.
            Za najbolju tocnost koristite kameru mobilnog telefona.
          </p>
        </div>
      </div>

      {!expanded ? (
        <button
          onClick={() => setExpanded(true)}
          className="w-full flex items-center justify-center gap-2 py-2.5 rounded-lg border border-amber-300 text-sm font-medium text-amber-800 hover:bg-amber-100 transition-colors"
        >
          <svg
            className="w-4 h-4"
            fill="none"
            viewBox="0 0 24 24"
            stroke="currentColor"
            strokeWidth={1.5}
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              d="M19.5 8.25l-7.5 7.5-7.5-7.5"
            />
          </svg>
          Nastavi s uploadom
        </button>
      ) : (
        <div className="pt-2">
          <ImageUpload onUpload={onUpload} isLoading={isLoading} />
        </div>
      )}
    </div>
  );
}
