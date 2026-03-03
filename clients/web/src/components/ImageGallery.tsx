"use client";

import { cn } from "@/lib/cn";

interface ImageGalleryProps {
  primaryImageUrl: string;
  additionalImages: { id: string; imageUrl: string; originalFileName: string }[];
  activeImageUrl: string;
  onSelect: (url: string) => void;
}

export function ImageGallery({ primaryImageUrl, additionalImages, activeImageUrl, onSelect }: ImageGalleryProps) {
  const allImages = [
    { url: primaryImageUrl, label: "Glavna" },
    ...additionalImages.map((img, i) => ({ url: img.imageUrl, label: `${i + 2}` })),
  ];

  if (allImages.length <= 1) return null;

  return (
    <div className="flex gap-2 overflow-x-auto pb-1">
      {allImages.map((img, i) => (
        <button
          key={i}
          onClick={() => onSelect(img.url)}
          className={cn(
            "flex-shrink-0 w-16 h-16 rounded-lg overflow-hidden border-2 transition-all",
            activeImageUrl === img.url
              ? "border-accent"
              : "border-transparent opacity-60 hover:opacity-100"
          )}
        >
          <img
            src={img.url}
            alt={img.label}
            className="w-full h-full object-cover"
          />
        </button>
      ))}
    </div>
  );
}
