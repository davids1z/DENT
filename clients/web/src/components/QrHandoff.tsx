"use client";

import { useEffect, useState } from "react";
import QRCode from "qrcode";

const INSPECT_URL = "https://dent.xyler.ai/inspect";

export function QrHandoff() {
  const [qrUrl, setQrUrl] = useState<string | null>(null);

  useEffect(() => {
    QRCode.toDataURL(INSPECT_URL, {
      width: 200,
      margin: 2,
      color: { dark: "#1a1a1a", light: "#ffffff" },
    }).then(setQrUrl);
  }, []);

  return (
    <div className="rounded-xl border border-border bg-card p-6 text-center space-y-4">
      <div className="w-12 h-12 rounded-xl bg-blue-500/10 flex items-center justify-center mx-auto">
        <svg
          className="w-6 h-6 text-blue-600"
          fill="none"
          viewBox="0 0 24 24"
          stroke="currentColor"
          strokeWidth={1.5}
        >
          <path
            strokeLinecap="round"
            strokeLinejoin="round"
            d="M10.5 1.5H8.25A2.25 2.25 0 006 3.75v16.5a2.25 2.25 0 002.25 2.25h7.5A2.25 2.25 0 0018 20.25V3.75a2.25 2.25 0 00-2.25-2.25H13.5m-3 0V3h3V1.5m-3 0h3m-3 18.75h3"
          />
        </svg>
      </div>

      <div>
        <p className="text-sm font-semibold text-foreground mb-1">
          Nastavite na mobitelu
        </p>
        <p className="text-xs text-muted">
          Skenirajte QR kod mobilnim telefonom za fotografiranje kamerom
        </p>
      </div>

      {qrUrl ? (
        <img
          src={qrUrl}
          alt="QR kod za mobilnu inspekciju"
          className="w-[180px] h-[180px] mx-auto rounded-lg border border-border"
        />
      ) : (
        <div className="w-[180px] h-[180px] mx-auto rounded-lg bg-card-hover animate-pulse" />
      )}

      <p className="text-[11px] text-muted break-all">{INSPECT_URL}</p>
    </div>
  );
}
