"use client";

import { useState } from "react";
import { cn } from "@/lib/cn";

interface FftSpectrumOverlayProps {
  fftSpectrumUrl: string;
}

export function FftSpectrumOverlay({ fftSpectrumUrl }: FftSpectrumOverlayProps) {
  const [showSpectrum, setShowSpectrum] = useState(false);

  return (
    <div className="bg-card border border-border rounded-xl overflow-hidden">
      <div className="flex items-center justify-between px-4 py-2.5 border-b border-border">
        <div className="flex items-center gap-2">
          <SpectrumIcon />
          <span className="text-sm font-medium">FFT Spektar</span>
          <span className="text-[10px] text-muted">
            (Frekvencijska analiza)
          </span>
        </div>
        <button
          onClick={() => setShowSpectrum(!showSpectrum)}
          className={cn(
            "px-3 py-1 text-xs font-medium rounded-full border transition-colors",
            showSpectrum
              ? "bg-violet-50 border-violet-200 text-violet-700"
              : "bg-gray-50 border-gray-200 text-gray-600 hover:bg-gray-100"
          )}
        >
          {showSpectrum ? "Sakrij FFT spektar" : "Prikazi FFT spektar"}
        </button>
      </div>

      {showSpectrum && (
        <>
          <div className="relative bg-black flex items-center justify-center">
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img
              src={fftSpectrumUrl}
              alt="FFT frekvencijski spektar"
              className="max-w-full h-auto max-h-[400px] object-contain"
            />
          </div>
          <div className="px-4 py-2.5 border-t border-border">
            <p className="text-xs text-muted">
              Periodicni vrhovi u spektru (svijetle tocke podalje od centra)
              ukazuju na Moire uzorke nastale fotografiranjem ekrana. Centar
              predstavlja niske frekvencije, rubovi visoke.
            </p>
          </div>
        </>
      )}
    </div>
  );
}

function SpectrumIcon() {
  return (
    <svg
      className="w-4 h-4 text-violet-500"
      fill="none"
      viewBox="0 0 24 24"
      stroke="currentColor"
      strokeWidth={1.5}
    >
      <path
        strokeLinecap="round"
        strokeLinejoin="round"
        d="M3.75 3v11.25A2.25 2.25 0 006 16.5h2.25M3.75 3h-1.5m1.5 0h16.5m0 0h1.5m-1.5 0v11.25A2.25 2.25 0 0118 16.5h-2.25m-7.5 0h7.5m-7.5 0l-1 3m8.5-3l1 3m0 0l.5 1.5m-.5-1.5h-9.5m0 0l-.5 1.5M9 11.25v1.5M12 9v3.75m3-6v6"
      />
    </svg>
  );
}
