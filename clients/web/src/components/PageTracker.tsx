"use client";

import { usePageTrack } from "@/lib/hooks/usePageTrack";

export function PageTracker() {
  usePageTrack();
  return null;
}
