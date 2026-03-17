const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8080/api";

export interface BoundingBox {
  x: number;
  y: number;
  w: number;
  h: number;
  imageIndex: number;
}

export interface RepairLineItem {
  lineNumber: number;
  partName: string;
  operation: string;
  laborType: string;
  laborHours: number;
  partType: string;
  quantity: number;
  unitCost: number | null;
  totalCost: number | null;
}

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
  boundingBox: string | null;
  damageCause: string | null;
  safetyRating: string | null;
  materialType: string | null;
  repairOperations: string | null;
  repairCategory: string | null;
  repairLineItems: RepairLineItem[];
}

export interface InspectionImage {
  id: string;
  imageUrl: string;
  originalFileName: string;
  sortOrder: number;
}

export interface DecisionTraceEntry {
  ruleName: string;
  ruleDescription: string;
  triggered: boolean;
  thresholdValue: string | null;
  actualValue: string | null;
  evaluationOrder: number;
}

export interface DecisionOverride {
  originalOutcome: string;
  newOutcome: string;
  reason: string;
  operatorName: string;
  createdAt: string;
}

export interface AgentReasoningStep {
  step: number;
  category: string;
  observation: string;
  assessment: string;
  impact: string;
}

export interface AgentWeatherVerification {
  queried: boolean;
  hadHail: boolean;
  hadPrecipitation: boolean;
  precipitationMm: number;
  corroboratesClaim: boolean | null;
  discrepancyNote: string | null;
  weatherDescription: string | null;
}

export interface AgentDecision {
  outcome: string;
  confidence: number;
  reasoningSteps: AgentReasoningStep[];
  weatherAssessment: string | null;
  fraudIndicators: string[];
  recommendedActions: string[];
  summaryHr: string;
  stpEligible: boolean;
  stpBlockers: string[];
  modelUsed: string;
  processingTimeMs: number;
  weatherVerification: AgentWeatherVerification | null;
}

export interface ForensicFinding {
  code: string;
  title: string;
  description: string;
  riskScore: number;
  confidence: number;
}

export interface ForensicModuleResult {
  moduleName: string;
  moduleLabel: string;
  riskScore: number;
  riskLevel: string;
  findings: ForensicFinding[];
  processingTimeMs: number;
  error: string | null;
}

export interface ForensicResult {
  overallRiskScore: number;
  overallRiskLevel: string;
  modules: ForensicModuleResult[];
  elaHeatmapUrl: string | null;
  fftSpectrumUrl: string | null;
  spectralHeatmapUrl: string | null;
  totalProcessingTimeMs: number;
}

export interface ImageHash {
  fileName: string;
  sha256: string;
}

export interface CustodyEvent {
  event: string;
  timestamp: string;
  hash: string | null;
  details: string | null;
}

export interface Inspection {
  id: string;
  imageUrl: string;
  originalFileName: string;
  thumbnailUrl: string | null;
  status: string;
  createdAt: string;
  completedAt: string | null;
  // User-provided vehicle context
  userProvidedMake: string | null;
  userProvidedModel: string | null;
  userProvidedYear: number | null;
  mileage: number | null;
  // AI-detected
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
  structuralIntegrity: string | null;
  errorMessage: string | null;
  // Structured totals
  laborTotal: number | null;
  partsTotal: number | null;
  materialsTotal: number | null;
  grossTotal: number | null;
  // Decision engine
  decisionOutcome: string | null;
  decisionReason: string | null;
  decisionTraces: DecisionTraceEntry[];
  decisionOverrides: DecisionOverride[];
  // Agent decision (Phase 7)
  agentDecision: AgentDecision | null;
  agentConfidence: number | null;
  agentStpEligible: boolean;
  agentFallbackUsed: boolean;
  agentProcessingTimeMs: number;
  // Fraud detection
  fraudRiskScore: number | null;
  fraudRiskLevel: string | null;
  forensicResult: ForensicResult | null;
  // Capture metadata (Phase 6)
  captureLatitude: number | null;
  captureLongitude: number | null;
  captureGpsAccuracy: number | null;
  captureDeviceInfo: string | null;
  captureSource: string | null;
  // Evidence integrity (Phase 8)
  evidenceHash: string | null;
  imageHashes: ImageHash[] | null;
  forensicResultHash: string | null;
  agentDecisionHash: string | null;
  chainOfCustody: CustodyEvent[] | null;
  hasTimestamp: boolean;
  timestampedAt: string | null;
  timestampAuthority: string | null;
  // Multi-image
  additionalImages: InspectionImage[];
  damages: DamageDetection[];
}

export interface CaptureMetadata {
  gps: { latitude: number; longitude: number; accuracy: number } | null;
  device: {
    userAgent: string;
    cameraLabel: string;
    screenWidth: number;
    screenHeight: number;
    captureTimestamp: string;
  };
  capturedAt: string;
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
  decisionOutcomeDistribution: Record<string, number>;
  recentInspections: Inspection[];
}

export interface VehicleContext {
  vehicleMake?: string;
  vehicleModel?: string;
  vehicleYear?: number;
  mileage?: number;
}

/** 3-minute timeout for analysis requests (CPU-only server can be slow). */
const ANALYSIS_TIMEOUT_MS = 180_000;

export async function uploadInspectionWithMetadata(
  files: File[],
  captureMetadata: CaptureMetadata[],
  vehicle?: VehicleContext,
): Promise<Inspection> {
  const formData = new FormData();
  files.forEach((f) => formData.append("images", f));
  if (vehicle?.vehicleMake) formData.append("vehicleMake", vehicle.vehicleMake);
  if (vehicle?.vehicleModel) formData.append("vehicleModel", vehicle.vehicleModel);
  if (vehicle?.vehicleYear) formData.append("vehicleYear", String(vehicle.vehicleYear));
  if (vehicle?.mileage) formData.append("mileage", String(vehicle.mileage));
  formData.append("captureMetadata", JSON.stringify(captureMetadata));

  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), ANALYSIS_TIMEOUT_MS);

  try {
    const res = await fetch(`${API_BASE}/inspections`, {
      method: "POST",
      body: formData,
      signal: controller.signal,
    });

    if (!res.ok) {
      const err = await res.json().catch(() => ({ error: "Upload failed" }));
      throw new Error(err.error || `Upload failed: ${res.status}`);
    }

    return res.json();
  } catch (e) {
    if (e instanceof DOMException && e.name === "AbortError") {
      throw new Error("Analiza je istekla — server nije odgovorio unutar 3 minute. Pokusajte ponovo.");
    }
    throw e;
  } finally {
    clearTimeout(timer);
  }
}

export async function uploadInspection(
  files: File[],
  vehicle?: VehicleContext
): Promise<Inspection> {
  const formData = new FormData();
  files.forEach((f) => formData.append("images", f));
  if (vehicle?.vehicleMake) formData.append("vehicleMake", vehicle.vehicleMake);
  if (vehicle?.vehicleModel) formData.append("vehicleModel", vehicle.vehicleModel);
  if (vehicle?.vehicleYear) formData.append("vehicleYear", String(vehicle.vehicleYear));
  if (vehicle?.mileage) formData.append("mileage", String(vehicle.mileage));

  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), ANALYSIS_TIMEOUT_MS);

  try {
    const res = await fetch(`${API_BASE}/inspections`, {
      method: "POST",
      body: formData,
      signal: controller.signal,
    });

    if (!res.ok) {
      const err = await res.json().catch(() => ({ error: "Upload failed" }));
      throw new Error(err.error || `Upload failed: ${res.status}`);
    }

    return res.json();
  } catch (e) {
    if (e instanceof DOMException && e.name === "AbortError") {
      throw new Error("Analiza je istekla — server nije odgovorio unutar 3 minute. Pokusajte ponovo.");
    }
    throw e;
  } finally {
    clearTimeout(timer);
  }
}

export async function overrideDecision(
  inspectionId: string,
  newOutcome: string,
  reason: string,
  operatorName: string
): Promise<Inspection> {
  const res = await fetch(`${API_BASE}/inspections/${inspectionId}/override`, {
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
    case "minor": return "text-green-600";
    case "moderate": return "text-amber-600";
    case "severe": return "text-orange-600";
    case "critical": return "text-red-600";
    default: return "text-gray-500";
  }
}

export function severityBg(severity: string): string {
  switch (severity.toLowerCase()) {
    case "minor": return "bg-green-50 border-green-200";
    case "moderate": return "bg-amber-50 border-amber-200";
    case "severe": return "bg-orange-50 border-orange-200";
    case "critical": return "bg-red-50 border-red-200";
    default: return "bg-gray-50 border-gray-200";
  }
}

export function damageTypeLabel(type: string): string {
  const labels: Record<string, string> = {
    Scratch: "Ogrebotina",
    Dent: "Udubljenje",
    Crack: "Pukotina",
    PaintDamage: "Oštećenje boje",
    BrokenGlass: "Slomljeno staklo",
    Rust: "Hrđa",
    BodyDeformation: "Deformacija karoserije",
    BumperDamage: "Oštećenje branika",
    LightDamage: "Oštećenje svjetla",
    TireDamage: "Oštećenje gume",
    MirrorDamage: "Oštećenje retrovizora",
    Other: "Ostalo",
  };
  return labels[type] || type;
}

export function carPartLabel(part: string): string {
  const labels: Record<string, string> = {
    FrontBumper: "Prednji branik",
    RearBumper: "Stražnji branik",
    Hood: "Hauba",
    Trunk: "Prtljažnik",
    FrontLeftDoor: "Prednja lijeva vrata",
    FrontRightDoor: "Prednja desna vrata",
    RearLeftDoor: "Stražnja lijeva vrata",
    RearRightDoor: "Stražnja desna vrata",
    FrontLeftFender: "Prednji lijevi blatobran",
    FrontRightFender: "Prednji desni blatobran",
    RearLeftFender: "Stražnji lijevi blatobran",
    RearRightFender: "Stražnji desni blatobran",
    Roof: "Krov",
    Windshield: "Vjetrobransko staklo",
    RearWindow: "Stražnje staklo",
    SideWindowLeft: "Bočno staklo lijevo",
    SideWindowRight: "Bočno staklo desno",
    SideMirrorLeft: "Retrovizor lijevi",
    SideMirrorRight: "Retrovizor desni",
    HeadlightLeft: "Prednje svjetlo lijevo",
    HeadlightRight: "Prednje svjetlo desno",
    TaillightLeft: "Stražnje svjetlo lijevo",
    TaillightRight: "Stražnje svjetlo desno",
    WheelFrontLeft: "Kotač prednji lijevi",
    WheelFrontRight: "Kotač prednji desni",
    WheelRearLeft: "Kotač stražnji lijevi",
    WheelRearRight: "Kotač stražnji desni",
    Undercarriage: "Podvozje",
    Other: "Ostalo",
  };
  return labels[part] || part;
}

export function severityLabel(severity: string): string {
  const labels: Record<string, string> = {
    Minor: "Niska sumnja",
    Moderate: "Umjerena sumnja",
    Severe: "Visoka sumnja",
    Critical: "Kriticna sumnja",
  };
  return labels[severity] || severity;
}

export function urgencyLabel(urgency: string): string {
  const labels: Record<string, string> = {
    Low: "Niska",
    Medium: "Srednja",
    High: "Visoka",
    Critical: "Kritična",
  };
  return labels[urgency] || urgency;
}

export function repairCategoryLabel(category: string): string {
  const labels: Record<string, string> = {
    Replace: "Zamjena",
    Repair: "Popravak",
    Polish: "Poliranje",
  };
  return labels[category] || category;
}

export function repairCategoryColor(category: string): string {
  switch (category) {
    case "Replace": return "#ef4444";
    case "Repair": return "#f97316";
    case "Polish": return "#eab308";
    default: return "#71717a";
  }
}

export function safetyRatingLabel(rating: string): string {
  const labels: Record<string, string> = {
    Safe: "Autenticno",
    Warning: "Sumnjivo",
    Critical: "Krivotvoreno",
  };
  return labels[rating] || rating;
}

export function safetyRatingColor(rating: string): string {
  switch (rating) {
    case "Safe": return "text-green-600";
    case "Warning": return "text-amber-600";
    case "Critical": return "text-red-600";
    default: return "text-gray-500";
  }
}

export function safetyRatingBg(rating: string): string {
  switch (rating) {
    case "Safe": return "bg-green-50 border-green-200";
    case "Warning": return "bg-amber-50 border-amber-200";
    case "Critical": return "bg-red-50 border-red-200";
    default: return "bg-gray-50 border-gray-200";
  }
}

export function parseBoundingBox(json: string | null): BoundingBox | null {
  if (!json) return null;
  try {
    const box = JSON.parse(json);
    if (typeof box.x === "number" && typeof box.y === "number" && typeof box.w === "number" && typeof box.h === "number") {
      return { x: box.x, y: box.y, w: box.w, h: box.h, imageIndex: box.imageIndex ?? 0 };
    }
    return null;
  } catch {
    return null;
  }
}

export function decisionOutcomeLabel(outcome: string): string {
  const labels: Record<string, string> = {
    AutoApprove: "Autenticno",
    HumanReview: "Potreban pregled",
    Escalate: "Sumnja na krivotvorinu",
  };
  return labels[outcome] || outcome;
}

export function findingCategoryLabel(cause: string | null): string {
  if (!cause) return "Nepoznato";
  const labels: Record<string, string> = {
    "AI generiranje": "AI generiranje",
    "Digitalna manipulacija": "Digitalna manipulacija",
    "Copy-paste krivotvorina": "Copy-paste krivotvorina",
    "Rekompresijski artefakti": "Rekompresijski artefakti",
    "Nekonzistentno osvjetljenje": "Nekonzistentno osvjetljenje",
    "Metadata anomalija": "Metadata anomalija",
    "Deepfake indikator": "Deepfake indikator",
    "Sumnjiva tekstura": "Sumnjiva tekstura",
    "Perspektivna anomalija": "Perspektivna anomalija",
    "Spektralna anomalija": "Spektralna anomalija",
    "Autenticno": "Autenticno",
  };
  return labels[cause] || cause;
}

export function decisionOutcomeColor(outcome: string): string {
  switch (outcome) {
    case "AutoApprove": return "text-green-600";
    case "HumanReview": return "text-amber-600";
    case "Escalate": return "text-red-600";
    default: return "text-gray-500";
  }
}

export function decisionOutcomeBg(outcome: string): string {
  switch (outcome) {
    case "AutoApprove": return "bg-green-50 border-green-200";
    case "HumanReview": return "bg-amber-50 border-amber-200";
    case "Escalate": return "bg-red-50 border-red-200";
    default: return "bg-gray-50 border-gray-200";
  }
}

export function laborTypeLabel(type: string): string {
  const labels: Record<string, string> = {
    Body: "Limarija",
    Refinish: "Lakiranje",
    Mechanical: "Mehanika",
    Electrical: "Elektrika",
    Glass: "Staklo",
  };
  return labels[type] || type;
}

// Forensic helpers
export function fraudRiskLabel(level: string): string {
  const labels: Record<string, string> = {
    Low: "Nizak rizik",
    Medium: "Srednji rizik",
    High: "Visok rizik",
    Critical: "Kritican rizik",
  };
  return labels[level] || level;
}

export function fraudRiskColor(level: string): string {
  switch (level) {
    case "Low": return "text-green-600";
    case "Medium": return "text-amber-600";
    case "High": return "text-orange-600";
    case "Critical": return "text-red-600";
    default: return "text-gray-500";
  }
}

export function fraudRiskBg(level: string): string {
  switch (level) {
    case "Low": return "bg-green-50 border-green-200";
    case "Medium": return "bg-amber-50 border-amber-200";
    case "High": return "bg-orange-50 border-orange-200";
    case "Critical": return "bg-red-50 border-red-200";
    default: return "bg-gray-50 border-gray-200";
  }
}

export function forensicModuleLabel(moduleName: string): string {
  const labels: Record<string, string> = {
    metadata_analysis: "Analiza metapodataka",
    modification_detection: "Detekcija modifikacija",
    deep_modification_detection: "Duboka analiza modifikacija (CNN)",
    optical_forensics: "Opticka forenzika",
    semantic_forensics: "Semanticka forenzika",
    document_forensics: "Forenzika dokumenata",
    office_forensics: "Office dokument forenzika",
    ai_generation_detection: "Detekcija AI generiranja",
    spectral_forensics: "Spektralna forenzika",
  };
  return labels[moduleName] || moduleName;
}

// Evidence integrity helpers (Phase 8)
export function getReportUrl(inspectionId: string): string {
  return `${API_BASE}/inspections/${inspectionId}/report`;
}

export function getCertificateUrl(inspectionId: string): string {
  return `${API_BASE}/inspections/${inspectionId}/certificate`;
}

export function custodyEventLabel(event: string): string {
  const labels: Record<string, string> = {
    image_received: "Slika zaprimljena",
    analysis_complete: "Analiza dovršena",
    forensics_complete: "Forenzika dovršena",
    decision_complete: "Odluka donesena",
    evidence_sealed: "Dokazi zapečaćeni",
    timestamp_failed: "Vremenski pečat neuspješan",
  };
  return labels[event] || event;
}
