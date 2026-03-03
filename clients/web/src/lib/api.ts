const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8080/api";

export interface DamageDetection {
  id: string;
  damageType: string;
  carPart: string;
  severity: string;
  description: string;
  confidence: number;
  repairMethod: string | null;
  estimatedCostMin: number | null;
  estimatedCostMax: number | null;
  laborHours: number | null;
  partsNeeded: string | null;
}

export interface Inspection {
  id: string;
  imageUrl: string;
  originalFileName: string;
  thumbnailUrl: string | null;
  status: string;
  createdAt: string;
  completedAt: string | null;
  vehicleMake: string | null;
  vehicleModel: string | null;
  vehicleYear: number | null;
  vehicleColor: string | null;
  summary: string | null;
  totalEstimatedCostMin: number | null;
  totalEstimatedCostMax: number | null;
  currency: string;
  isDriveable: boolean | null;
  urgencyLevel: string | null;
  errorMessage: string | null;
  damages: DamageDetection[];
}

export interface DashboardStats {
  totalInspections: number;
  completedInspections: number;
  pendingInspections: number;
  averageCostMin: number;
  averageCostMax: number;
  damageTypeDistribution: Record<string, number>;
  severityDistribution: Record<string, number>;
  carPartDistribution: Record<string, number>;
  recentInspections: Inspection[];
}

export async function uploadInspection(file: File): Promise<Inspection> {
  const formData = new FormData();
  formData.append("image", file);

  const res = await fetch(`${API_BASE}/inspections`, {
    method: "POST",
    body: formData,
  });

  if (!res.ok) {
    const err = await res.json().catch(() => ({ error: "Upload failed" }));
    throw new Error(err.error || `Upload failed: ${res.status}`);
  }

  return res.json();
}

export async function getInspections(
  page = 1,
  pageSize = 20,
  status?: string
): Promise<Inspection[]> {
  const params = new URLSearchParams({ page: String(page), pageSize: String(pageSize) });
  if (status) params.set("status", status);

  const res = await fetch(`${API_BASE}/inspections?${params}`);
  if (!res.ok) throw new Error(`Failed to fetch inspections: ${res.status}`);
  return res.json();
}

export async function getInspection(id: string): Promise<Inspection> {
  const res = await fetch(`${API_BASE}/inspections/${id}`);
  if (!res.ok) throw new Error(`Inspection not found: ${res.status}`);
  return res.json();
}

export async function deleteInspection(id: string): Promise<void> {
  const res = await fetch(`${API_BASE}/inspections/${id}`, { method: "DELETE" });
  if (!res.ok) throw new Error(`Failed to delete: ${res.status}`);
}

export async function getDashboardStats(): Promise<DashboardStats> {
  const res = await fetch(`${API_BASE}/dashboard/stats`);
  if (!res.ok) throw new Error(`Failed to fetch stats: ${res.status}`);
  return res.json();
}

// Helpers
export function formatCurrency(amount: number | null, currency = "EUR"): string {
  if (amount == null) return "N/A";
  return new Intl.NumberFormat("hr-HR", { style: "currency", currency }).format(amount);
}

export function formatDate(dateStr: string): string {
  return new Intl.DateTimeFormat("hr-HR", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(dateStr));
}

export function severityColor(severity: string): string {
  switch (severity.toLowerCase()) {
    case "minor": return "text-green-400";
    case "moderate": return "text-yellow-400";
    case "severe": return "text-orange-400";
    case "critical": return "text-red-400";
    default: return "text-zinc-400";
  }
}

export function severityBg(severity: string): string {
  switch (severity.toLowerCase()) {
    case "minor": return "bg-green-400/10 border-green-400/20";
    case "moderate": return "bg-yellow-400/10 border-yellow-400/20";
    case "severe": return "bg-orange-400/10 border-orange-400/20";
    case "critical": return "bg-red-400/10 border-red-400/20";
    default: return "bg-zinc-400/10 border-zinc-400/20";
  }
}

export function damageTypeLabel(type: string): string {
  const labels: Record<string, string> = {
    Scratch: "Ogrebotina",
    Dent: "Udubljenje",
    Crack: "Pukotina",
    PaintDamage: "Ostecenje boje",
    BrokenGlass: "Slomljeno staklo",
    Rust: "Hrdja",
    BodyDeformation: "Deformacija karoserije",
    BumperDamage: "Ostecenje branika",
    LightDamage: "Ostecenje svjetla",
    TireDamage: "Ostecenje gume",
    MirrorDamage: "Ostecenje retrovizora",
    Other: "Ostalo",
  };
  return labels[type] || type;
}

export function carPartLabel(part: string): string {
  const labels: Record<string, string> = {
    FrontBumper: "Prednji branik",
    RearBumper: "Straznji branik",
    Hood: "Hauba",
    Trunk: "Prtljaznik",
    FrontLeftDoor: "Prednja lijeva vrata",
    FrontRightDoor: "Prednja desna vrata",
    RearLeftDoor: "Straznja lijeva vrata",
    RearRightDoor: "Straznja desna vrata",
    FrontLeftFender: "Prednji lijevi blatobran",
    FrontRightFender: "Prednji desni blatobran",
    RearLeftFender: "Straznji lijevi blatobran",
    RearRightFender: "Straznji desni blatobran",
    Roof: "Krov",
    Windshield: "Vjetrobransko staklo",
    RearWindow: "Straznje staklo",
    SideWindowLeft: "Bocno staklo lijevo",
    SideWindowRight: "Bocno staklo desno",
    SideMirrorLeft: "Retrovizor lijevi",
    SideMirrorRight: "Retrovizor desni",
    HeadlightLeft: "Prednje svjetlo lijevo",
    HeadlightRight: "Prednje svjetlo desno",
    TaillightLeft: "Straznje svjetlo lijevo",
    TaillightRight: "Straznje svjetlo desno",
    WheelFrontLeft: "Kotac prednji lijevi",
    WheelFrontRight: "Kotac prednji desni",
    WheelRearLeft: "Kotac straznji lijevi",
    WheelRearRight: "Kotac straznji desni",
    Undercarriage: "Podvozje",
    Other: "Ostalo",
  };
  return labels[part] || part;
}
