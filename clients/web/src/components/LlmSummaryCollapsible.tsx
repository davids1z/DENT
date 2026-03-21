"use client";

import { useState } from "react";
import { sanitizeLlmText } from "@/lib/forensicPillars";
import { cn } from "@/lib/cn";

interface LlmSummaryCollapsibleProps {
  summary: string | null;
}

export function LlmSummaryCollapsible({ summary }: LlmSummaryCollapsibleProps) {
  const [open, setOpen] = useState(false);

  if (!summary) return null;

  const cleaned = sanitizeLlmText(summary);
  if (!cleaned) return null;

  return (
    <div className="bg-card border border-border rounded-xl overflow-hidden">
      <button
        onClick={() => setOpen(!open)}
        className="w-full flex items-center justify-between px-4 py-3 text-left hover:bg-card-hover transition-colors"
      >
        <div className="flex items-center gap-2">
          <svg className="w-4 h-4 text-muted" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M7.5 8.25h9m-9 3H12m-9.75 1.51c0 1.6 1.123 2.994 2.707 3.227 1.129.166 2.27.293 3.423.379.35.026.67.21.865.501L12 21l2.755-4.133a1.14 1.14 0 01.865-.501 48.172 48.172 0 003.423-.379c1.584-.233 2.707-1.626 2.707-3.228V6.741c0-1.602-1.123-2.995-2.707-3.228A48.394 48.394 0 0012 3c-2.392 0-4.744.175-7.043.513C3.373 3.746 2.25 5.14 2.25 6.741v6.018z" />
          </svg>
          <span className="text-sm font-medium text-muted">AI sazetak (Gemini)</span>
        </div>
        <svg
          className={cn("w-4 h-4 text-muted transition-transform", open && "rotate-180")}
          fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}
        >
          <path strokeLinecap="round" strokeLinejoin="round" d="M19.5 8.25l-7.5 7.5-7.5-7.5" />
        </svg>
      </button>

      {open && (
        <div className="px-4 pb-4">
          <p className="text-sm text-muted leading-relaxed">{cleaned}</p>
          <p className="text-[10px] text-muted/60 mt-2 italic">
            Ovaj sazetak generirao je jezicni model i moze sadrzavati netocnosti.
          </p>
        </div>
      )}
    </div>
  );
}
