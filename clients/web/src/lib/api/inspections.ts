import { API_BASE, authFetch, authHeaders } from "./client";
import type { CaptureMetadata, DashboardStats, Inspection, VehicleContext } from "./types";

const UPLOAD_TIMEOUT_MS = 120_000;
const POLL_INTERVAL_MS = 1_000;
const POLL_MAX_MS = 600_000;

// ---------------------------------------------------------------------------
// Client-side image compression — reduces upload from 5-10MB to ~150-300KB
//
// IMPORTANT (Sprint 2, 2026-04-07): the previous implementation drew every
// uploaded image into a canvas and re-encoded it as JPEG. That destroys
// every piece of metadata the backend uses for forensic analysis:
//
//   - EXIF (Make/Model/DateTimeOriginal/GPS) — primary device fingerprint
//   - XMP and IPTC blocks (editing history, creator tags)
//   - ICC profiles (colour space anomalies)
//   - PNG iTXt/tEXt chunks (Stable Diffusion / ComfyUI / Auto1111 prompts!)
//   - C2PA provenance manifests (DALL-E 3, Adobe Firefly, GPT-Image-1)
//   - WebP-specific chunks
//
// Every authentic photo from a phone arrived at the backend looking like
// it had been laundered through a metadata stripper. The metadata module
// has been blind in production since the day this was written.
//
// New policy: NEVER compress unless we have to.
//   1. Non-image files (PDF, DOCX) → pass through unchanged
//   2. PNG / WebP / HEIC / AVIF → ALWAYS pass through unchanged
//      (these formats carry the most-discriminative metadata: SD prompts,
//      C2PA manifests, modern AI generator signatures)
//   3. JPEG ≤ 4MB → pass through unchanged (preserves EXIF/XMP)
//   4. JPEG > 4MB → compress as a last resort, ONLY when the file is too
//      big for the upload path. This is the only branch that strips EXIF
//      and we accept the trade-off because the alternative is failed
//      uploads on huge photos.
// ---------------------------------------------------------------------------
const COMPRESS_MAX_DIM = 1536; // px — enough for all ML models (max input 518px)
const COMPRESS_QUALITY = 0.85; // JPEG quality (was 0.80; bumped now that we
                                // only ever recompress huge files)
const COMPRESS_THRESHOLD_BYTES = 4 * 1024 * 1024; // 4 MB

/** Image MIME types whose metadata we MUST preserve at all costs. */
const METADATA_CRITICAL_TYPES = new Set([
  "image/png",
  "image/webp",
  "image/heic",
  "image/heif",
  "image/avif",
  "image/tiff",
  "image/gif",
]);

/**
 * Compress an image File on the client only when strictly necessary.
 * Preserves the original bytes (and therefore EXIF / PNG chunks / C2PA)
 * whenever possible.
 */
async function compressImage(file: File): Promise<File> {
  // Pass through non-image files (PDF, DOCX, etc.)
  if (!file.type.startsWith("image/")) return file;

  // Pass through metadata-critical formats unchanged. Re-encoding any of
  // these as JPEG would destroy forensic signal we cannot recover.
  if (METADATA_CRITICAL_TYPES.has(file.type)) return file;

  // JPEG below the threshold → pass through unchanged. This preserves
  // EXIF/XMP/IPTC/ICC for the metadata module without an upload penalty.
  if (file.size <= COMPRESS_THRESHOLD_BYTES) return file;

  // JPEG above 4MB → fall back to canvas re-encode. This DOES strip EXIF
  // — accepted trade-off because the alternative is upload failure.
  return new Promise<File>((resolve) => {
    const img = new Image();
    img.onload = () => {
      let { width, height } = img;

      // Downscale if larger than max dimension
      if (width > COMPRESS_MAX_DIM || height > COMPRESS_MAX_DIM) {
        const ratio = Math.min(COMPRESS_MAX_DIM / width, COMPRESS_MAX_DIM / height);
        width = Math.round(width * ratio);
        height = Math.round(height * ratio);
      }

      const canvas = document.createElement("canvas");
      canvas.width = width;
      canvas.height = height;
      const ctx = canvas.getContext("2d")!;
      ctx.drawImage(img, 0, 0, width, height);

      canvas.toBlob(
        (blob) => {
          if (blob && blob.size < file.size) {
            // Use compressed version. Keep the original filename so the
            // backend filename heuristics (`gemini_generated_image_…`)
            // still fire. Only the extension changes.
            const name = file.name.replace(/\.[^.]+$/i, ".jpg");
            resolve(new File([blob], name, { type: "image/jpeg" }));
          } else {
            // Compressed is larger (rare for >4MB inputs) — use original
            resolve(file);
          }
          URL.revokeObjectURL(img.src);
        },
        "image/jpeg",
        COMPRESS_QUALITY,
      );
    };
    img.onerror = () => {
      URL.revokeObjectURL(img.src);
      resolve(file); // fallback to original on error
    };
    img.src = URL.createObjectURL(file);
  });
}

/** Compress multiple files in parallel. */
async function compressFiles(files: File[]): Promise<File[]> {
  return Promise.all(files.map(compressImage));
}

/**
 * Upload files as a single inspection with all images.
 * Optionally include capture metadata (GPS, device) and vehicle context.
 */
export async function uploadInspection(
  files: File[],
  options?: {
    captureMetadata?: CaptureMetadata[];
    vehicle?: VehicleContext;
    analysisMode?: "individual" | "group";
  },
): Promise<Inspection> {
  const compressed = await compressFiles(files);
  const formData = new FormData();
  compressed.forEach((f) => formData.append("images", f));

  if (options?.analysisMode) formData.append("analysisMode", options.analysisMode);

  const vehicle = options?.vehicle;
  if (vehicle?.vehicleMake) formData.append("vehicleMake", vehicle.vehicleMake);
  if (vehicle?.vehicleModel) formData.append("vehicleModel", vehicle.vehicleModel);
  if (vehicle?.vehicleYear) formData.append("vehicleYear", String(vehicle.vehicleYear));
  if (vehicle?.mileage) formData.append("mileage", String(vehicle.mileage));

  if (options?.captureMetadata) {
    formData.append("captureMetadata", JSON.stringify(options.captureMetadata));
  }

  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), UPLOAD_TIMEOUT_MS);

  try {
    const res = await fetch(`${API_BASE}/inspections`, {
      method: "POST",
      body: formData,
      signal: controller.signal,
      headers: authHeaders(),
    });

    if (res.status === 429) {
      throw new Error("Previše zahtjeva. Pričekajte minutu pa pokušajte ponovo.");
    }
    if (!res.ok) {
      const err = await res.json().catch(() => ({ error: "Upload failed" }));
      throw new Error(err.error || `Upload failed: ${res.status}`);
    }

    return res.json();
  } catch (e) {
    if (e instanceof DOMException && e.name === "AbortError") {
      throw new Error("Upload nije uspio — server nije odgovorio. Pokusajte ponovo.");
    }
    throw e;
  } finally {
    clearTimeout(timer);
  }
}

/**
 * Upload files as SEPARATE inspections — one inspection per file.
 * Returns ALL created inspections.
 */
export async function uploadInspectionsSeparate(
  files: File[],
  vehicle?: VehicleContext,
): Promise<Inspection[]> {
  // Compress all images in parallel first (5MB → ~200KB each)
  const compressed = await compressFiles(files);

  const uploads = compressed.map(async (file) => {
    const formData = new FormData();
    formData.append("images", file);
    if (vehicle?.vehicleMake) formData.append("vehicleMake", vehicle.vehicleMake);
    if (vehicle?.vehicleModel) formData.append("vehicleModel", vehicle.vehicleModel);
    if (vehicle?.vehicleYear) formData.append("vehicleYear", String(vehicle.vehicleYear));
    if (vehicle?.mileage) formData.append("mileage", String(vehicle.mileage));

    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), UPLOAD_TIMEOUT_MS);

    try {
      const res = await fetch(`${API_BASE}/inspections`, {
        method: "POST",
        body: formData,
        signal: controller.signal,
        headers: authHeaders(),
      });

      if (!res.ok) {
        const err = await res.json().catch(() => ({ error: "Upload failed" }));
        throw new Error(err.error || `Upload failed: ${res.status}`);
      }

      return res.json() as Promise<Inspection>;
    } finally {
      clearTimeout(timer);
    }
  });

  return Promise.all(uploads);
}

export class PollTimeoutError extends Error {
  public readonly inspectionId: string;
  constructor(id: string) {
    super("Analiza traje predugo. Provjerite rezultat na popisu inspekcija.");
    this.name = "PollTimeoutError";
    this.inspectionId = id;
  }
}

export async function pollInspectionUntilComplete(id: string): Promise<Inspection> {
  const start = Date.now();

  while (Date.now() - start < POLL_MAX_MS) {
    // Check FIRST, sleep after — saves up to 1s on every completion
    const inspection = await getInspection(id);
    if (inspection.status !== "Analyzing") {
      return inspection;
    }

    await new Promise((r) => setTimeout(r, POLL_INTERVAL_MS));
  }

  throw new PollTimeoutError(id);
}

export async function overrideDecision(
  inspectionId: string,
  newOutcome: string,
  reason: string,
  operatorName: string,
): Promise<Inspection> {
  const res = await authFetch(`${API_BASE}/inspections/${inspectionId}/override`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ newOutcome, reason, operatorName }),
  });

  if (!res.ok) {
    const err = await res.json().catch(() => ({ error: "Override failed" }));
    throw new Error(err.error || `Override failed: ${res.status}`);
  }

  return res.json();
}

export async function getInspections(
  page = 1,
  pageSize = 20,
  status?: string,
): Promise<Inspection[]> {
  const params = new URLSearchParams({ page: String(page), pageSize: String(pageSize) });
  if (status) params.set("status", status);

  const res = await authFetch(`${API_BASE}/inspections?${params}`);
  if (!res.ok) throw new Error(`Failed to fetch inspections: ${res.status}`);
  return res.json();
}

export async function getInspection(id: string): Promise<Inspection> {
  const res = await authFetch(`${API_BASE}/inspections/${id}`);
  if (!res.ok) throw new Error(`Inspection not found: ${res.status}`);
  return res.json();
}

export async function deleteInspection(id: string): Promise<void> {
  const res = await authFetch(`${API_BASE}/inspections/${id}`, { method: "DELETE" });
  if (!res.ok) throw new Error(`Failed to delete: ${res.status}`);
}

export async function getDashboardStats(): Promise<DashboardStats> {
  const res = await authFetch(`${API_BASE}/dashboard/stats`);
  if (!res.ok) throw new Error(`Failed to fetch stats: ${res.status}`);
  return res.json();
}

export function getReportUrl(inspectionId: string): string {
  return `${API_BASE}/inspections/${inspectionId}/report`;
}

export function getCertificateUrl(inspectionId: string): string {
  return `${API_BASE}/inspections/${inspectionId}/certificate`;
}
