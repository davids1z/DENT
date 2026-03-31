import { API_BASE, authFetch, authHeaders } from "./client";
import type { CaptureMetadata, DashboardStats, Inspection, VehicleContext } from "./types";

const UPLOAD_TIMEOUT_MS = 120_000;
const POLL_INTERVAL_MS = 1_000;
const POLL_MAX_MS = 300_000;

// ---------------------------------------------------------------------------
// Client-side image compression — reduces upload from 5-10MB to ~150-300KB
// ---------------------------------------------------------------------------
const COMPRESS_MAX_DIM = 1536; // px — enough for all ML models (max input 518px)
const COMPRESS_QUALITY = 0.80; // JPEG quality

/**
 * Compress an image File on the client using canvas.
 * Returns a smaller JPEG Blob. Skips non-image files (PDFs, DOCX).
 */
async function compressImage(file: File): Promise<File> {
  // Skip non-image files
  if (!file.type.startsWith("image/")) return file;

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
            // Use compressed version (rename to .jpg)
            const name = file.name.replace(/\.[^.]+$/, ".jpg");
            resolve(new File([blob], name, { type: "image/jpeg" }));
          } else {
            // Compressed is larger (tiny image) — use original
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

  throw new Error("Analiza traje predugo. Provjerite rezultat na popisu inspekcija.");
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
