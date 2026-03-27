"use client";

import type { DamageDetection } from "@/lib/api";
import { DocumentPreview } from "@/components/DocumentPreview";
import { ImageOverlay } from "@/components/ImageOverlay";

interface DamageOverlayProps {
  imageUrl: string;
  damages: DamageDetection[];
  selectedIndex?: number | null;
  onSelectDamage?: (index: number | null) => void;
  activeImageIndex?: number;
  fileName?: string;
  pagePreviewUrls?: string[] | null;
}

function isDocumentUrl(url: string, name?: string): boolean {
  const ext = (name || url).split(".").pop()?.toLowerCase() ?? "";
  return ["pdf", "docx", "xlsx", "doc", "xls"].includes(ext);
}

export function DamageOverlay({
  imageUrl,
  damages,
  selectedIndex,
  onSelectDamage,
  activeImageIndex,
  fileName,
  pagePreviewUrls,
}: DamageOverlayProps) {
  if (isDocumentUrl(imageUrl, fileName)) {
    return (
      <DocumentPreview
        imageUrl={imageUrl}
        fileName={fileName}
        pagePreviewUrls={pagePreviewUrls}
      />
    );
  }

  return (
    <ImageOverlay
      imageUrl={imageUrl}
      damages={damages}
      selectedIndex={selectedIndex}
      onSelectDamage={onSelectDamage}
      activeImageIndex={activeImageIndex}
    />
  );
}
