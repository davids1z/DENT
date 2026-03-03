"use client";

import { useCallback, useState } from "react";

interface ImageUploadProps {
  onUpload: (file: File) => void;
  isLoading: boolean;
}

export function ImageUpload({ onUpload, isLoading }: ImageUploadProps) {
  const [isDragging, setIsDragging] = useState(false);
  const [preview, setPreview] = useState<string | null>(null);

  const handleFile = useCallback(
    (file: File) => {
      if (!file.type.startsWith("image/")) return;
      setPreview(URL.createObjectURL(file));
      onUpload(file);
    },
    [onUpload]
  );

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      setIsDragging(false);
      const file = e.dataTransfer.files[0];
      if (file) handleFile(file);
    },
    [handleFile]
  );

  const handleChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const file = e.target.files?.[0];
      if (file) handleFile(file);
    },
    [handleFile]
  );

  return (
    <div
      onDragOver={(e) => {
        e.preventDefault();
        setIsDragging(true);
      }}
      onDragLeave={() => setIsDragging(false)}
      onDrop={handleDrop}
      className={`relative border-2 border-dashed rounded-2xl transition-all duration-300 ${
        isDragging
          ? "border-accent bg-accent/5 upload-zone-active"
          : "border-border hover:border-accent/50 hover:bg-card-hover/50"
      } ${isLoading ? "pointer-events-none opacity-60" : "cursor-pointer"}`}
    >
      <label className="flex flex-col items-center justify-center p-12 cursor-pointer">
        <input
          type="file"
          accept="image/jpeg,image/png,image/webp,image/heic"
          onChange={handleChange}
          className="hidden"
          disabled={isLoading}
        />

        {preview && !isLoading ? (
          <div className="relative w-full max-w-md">
            <img
              src={preview}
              alt="Preview"
              className="rounded-xl w-full h-64 object-cover"
            />
            <div className="absolute inset-0 bg-black/40 rounded-xl flex items-center justify-center opacity-0 hover:opacity-100 transition-opacity">
              <span className="text-white font-medium">Promijeni sliku</span>
            </div>
          </div>
        ) : (
          <>
            <div className="w-16 h-16 rounded-2xl bg-accent/10 flex items-center justify-center mb-4">
              <svg
                className="w-8 h-8 text-accent"
                fill="none"
                viewBox="0 0 24 24"
                stroke="currentColor"
              >
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth={1.5}
                  d="M3 16.5v2.25A2.25 2.25 0 005.25 21h13.5A2.25 2.25 0 0021 18.75V16.5m-13.5-9L12 3m0 0l4.5 4.5M12 3v13.5"
                />
              </svg>
            </div>
            {isLoading ? (
              <div className="flex flex-col items-center gap-3">
                <div className="w-8 h-8 border-2 border-accent border-t-transparent rounded-full animate-spin" />
                <p className="text-sm text-muted">AI analizira sliku...</p>
              </div>
            ) : (
              <>
                <p className="text-foreground font-medium mb-1">
                  Povucite sliku ovdje ili kliknite za odabir
                </p>
                <p className="text-sm text-muted">
                  JPG, PNG, WebP ili HEIC do 50MB
                </p>
              </>
            )}
          </>
        )}
      </label>
    </div>
  );
}
