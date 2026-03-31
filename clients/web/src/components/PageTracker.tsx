"use client";

import { usePageTrack } from "@/lib/hooks/usePageTrack";
import { useScrollToTopOnNav } from "@/hooks/useScrollToTopOnNav";

export function PageTracker() {
  usePageTrack();
  useScrollToTopOnNav();
  return null;
}
