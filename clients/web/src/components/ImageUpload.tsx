"use client";

import { useCallback, useState } from "react";
import { cn } from "@/lib/cn";

interface ImageUploadProps {
  onUpload: (files: File[]) => void;
  isLoading: boolean;
}

const MAX_IMAGES = 8;

export function ImageUpload({ onUpload, isLoading }: ImageUploadProps) {
  const [isDragging, setIsDragging] = useState(false);
  const [files, setFiles] = useState<File[]>([]);
  const [previews, setPreviews] = useState<string[]>([]);

  const addFiles = useCallback((newFiles: File[]) => {
    const imageFiles = newFiles.filter((f) => f.type.startsWith("image/"));
    setFiles((prev) => {
      const combined = [...prev, ...imageFiles].slice(0, MAX_IMAGES);
      setPreviews(combined.map((f) => URL.createObjectURL(f)));
      return combined;
    });
  }, []);

  const removeFile = useCallback((index: number) => {
    setFiles((prev) => {
      const next = prev.filter((_, i) => i !== index);
      setPreviews(next.map((f) => URL.createObjectURL(f)));
      return next;
    });
  }, []);

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      setIsDragging(false);
      addFiles(Array.from(e.dataTransfer.files));
    },
    [addFiles]
  );

  const handleChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      if (e.target.files) addFiles(Array.from(e.target.files));
      e.target.value = "";
    },
    [addFiles]
  );

  const handleSubmit = () => {
    if (files.length > 0) onUpload(files);
  };

  return (
    <div className="space-y-4">
      <div
        onDragOver={(e) => { e.preventDefault(); setIsDragging(true); }}
        onDragLeave={() => setIsDragging(false)}
        onDrop={handleDrop}
        className={cn(
          "border-2 border-dashed rounded-xl transition-colors",
          isDragging
            ? "border-accent bg-accent/5"
            : "border-gray-300 hover:border-accent/50",
          isLoading && "pointer-events-none opacity-60"
        )}
      >
        <label className="flex flex-col items-center justify-center p-8 cursor-pointer">
          <input
            type="file"
            accept="image/jpeg,image/png,image/webp,image/heic"
            onChange={handleChange}
            className="hidden"
            disabled={isLoading}
            multiple
          />
          <div className="w-12 h-12 rounded-xl bg-accent/10 flex items-center justify-center mb-3">
            <svg className="w-6 h-6 text-accent" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M3 16.5v2.25A2.25 2.25 0 005.25 21h13.5A2.25 2.25 0 0021 18.75V16.5m-13.5-9L12 3m0 0l4.5 4.5M12 3v13.5" />
            </svg>
          </div>
          <p className="text-foreground font-medium text-sm mb-1">
            Povucite datoteke ovdje ili kliknite za odabir
          </p>
          <p className="text-xs text-muted">
            Do {MAX_IMAGES} datoteka &middot; JPG, PNG, WebP ili HEIC
          </p>
        </label>
      </div>

      {previews.length > 0 && (
        <div className="space-y-3">
          <div className="flex items-center justify-between">
            <span className="text-sm text-muted">{files.length}/{MAX_IMAGES} slika</span>
            {files.length > 0 && !isLoading && (
              <button
                onClick={() => { setFiles([]); setPreviews([]); }}
                className="text-xs text-muted hover:text-red-500 transition-colors"
              >
                Ukloni sve
              </button>
            )}
          </div>
          <div className="grid grid-cols-4 gap-2">
            {previews.map((src, i) => (
              <div key={i} className="relative group aspect-square rounded-lg overflow-hidden border border-border">
                <img src={src} alt={`Preview ${i + 1}`} className="w-full h-full object-cover" />
                {!isLoading && (
                  <button
                    onClick={() => removeFile(i)}
                    className="absolute top-1 right-1 w-5 h-5 rounded-full bg-black/60 text-white flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity"
                  >
                    <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                      <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
                    </svg>
                  </button>
                )}
                {i === 0 && (
                  <div className="absolute bottom-1 left-1 px-1.5 py-0.5 rounded text-[9px] bg-accent text-white font-medium">
                    Glavna
                  </div>
                )}
              </div>
            ))}
            {files.length < MAX_IMAGES && !isLoading && (
              <label className="aspect-square rounded-lg border-2 border-dashed border-gray-300 hover:border-accent/50 flex items-center justify-center cursor-pointer transition-colors">
                <input
                  type="file"
                  accept="image/jpeg,image/png,image/webp,image/heic"
                  onChange={handleChange}
                  className="hidden"
                  multiple
                />
                <svg className="w-6 h-6 text-muted" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M12 4.5v15m7.5-7.5h-15" />
                </svg>
              </label>
            )}
          </div>
        </div>
      )}

      {files.length > 0 && (
        <button
          onClick={handleSubmit}
          disabled={isLoading}
          className={cn(
            "w-full py-3 rounded-lg font-medium text-sm transition-colors",
            isLoading
              ? "bg-gray-100 text-muted cursor-wait"
              : "bg-accent text-white hover:bg-accent-hover"
          )}
        >
          {isLoading ? (
            <span className="flex items-center justify-center gap-2">
              <div className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />
              Analiziranje...
            </span>
          ) : (
            `Analiziraj ${files.length} ${files.length === 1 ? "sliku" : files.length < 5 ? "slike" : "slika"}`
          )}
        </button>
      )}
    </div>
  );
}
