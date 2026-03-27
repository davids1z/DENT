import { API_BASE, authFetch, authHeaders, getToken } from "./client";
import type { CaptureMetadata, DashboardStats, Inspection, VehicleContext } from "./types";

const UPLOAD_TIMEOUT_MS = 120_000;
const POLL_INTERVAL_MS = 1_000;
const POLL_MAX_MS = 300_000;

/**
 * Upload files as a single inspection with all images.
 * Optionally include capture metadata (GPS, device) and vehicle context.
 */
export async function uploadInspection(
  files: File[],
  options?: {
    captureMetadata?: CaptureMetadata[];
    vehicle?: VehicleContext;
  },
): Promise<Inspection> {
  const formData = new FormData();
  files.forEach((f) => formData.append("images", f));

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
  const uploads = files.map(async (file) => {
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
    await new Promise((r) => setTimeout(r, POLL_INTERVAL_MS));

    const inspection = await getInspection(id);
    if (inspection.status !== "Analyzing") {
      return inspection;
    }
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
  const token = getToken();
  const base = `${API_BASE}/inspections/${inspectionId}/report`;
  return token ? `${base}?access_token=${encodeURIComponent(token)}` : base;
}

export function getCertificateUrl(inspectionId: string): string {
  const token = getToken();
  const base = `${API_BASE}/inspections/${inspectionId}/certificate`;
  return token ? `${base}?access_token=${encodeURIComponent(token)}` : base;
}
