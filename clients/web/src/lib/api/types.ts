export interface AuthUser {
  id: string;
  email: string;
  fullName: string;
  role: string;
}

export interface AuthResponse {
  token: string;
  refreshToken: string;
  user: AuthUser;
}

export interface AdminUser {
  id: string;
  email: string;
  fullName: string;
  role: string;
  createdAt: string;
  lastLoginAt: string | null;
  isActive: boolean;
  inspectionCount: number;
}

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
  riskScore100: number;
  riskLevel: string;
  findings: ForensicFinding[];
  processingTimeMs: number;
  error: string | null;
}

export interface ForensicResult {
  fileName: string | null;
  fileUrl: string | null;
  sortOrder: number;
  overallRiskScore: number;
  overallRiskScore100: number;
  overallRiskLevel: string;
  modules: ForensicModuleResult[];
  elaHeatmapUrl: string | null;
  fftSpectrumUrl: string | null;
  spectralHeatmapUrl: string | null;
  totalProcessingTimeMs: number;
  predictedSource: string | null;
  sourceConfidence: number;
  c2paStatus: string | null;
  c2paIssuer: string | null;
  verdictProbabilities: Record<string, number> | null;
  pagePreviewUrls?: string[] | null;
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

export interface CrossImageFinding {
  code: string;
  title: string;
  description: string;
  riskScore: number;
  confidence: number;
  affectedFiles: number[];
  evidence: Record<string, unknown> | null;
}

export interface CrossImageReport {
  findings: CrossImageFinding[];
  groupRiskModifier: number;
  processingTimeMs: number;
}

export interface Inspection {
  id: string;
  imageUrl: string;
  originalFileName: string;
  thumbnailUrl: string | null;
  status: string;
  createdAt: string;
  completedAt: string | null;
  ownerEmail: string | null;
  ownerFullName: string | null;
  analysisMode: string | null;
  crossImageReport: CrossImageReport | null;
  userProvidedMake: string | null;
  userProvidedModel: string | null;
  userProvidedYear: number | null;
  mileage: number | null;
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
  laborTotal: number | null;
  partsTotal: number | null;
  materialsTotal: number | null;
  grossTotal: number | null;
  decisionOutcome: string | null;
  decisionReason: string | null;
  decisionTraces: DecisionTraceEntry[];
  decisionOverrides: DecisionOverride[];
  agentDecision: AgentDecision | null;
  agentConfidence: number | null;
  agentStpEligible: boolean;
  agentFallbackUsed: boolean;
  agentProcessingTimeMs: number;
  fraudRiskScore: number | null;
  fraudRiskLevel: string | null;
  forensicResult: ForensicResult | null;
  fileForensicResults: ForensicResult[];
  captureLatitude: number | null;
  captureLongitude: number | null;
  captureGpsAccuracy: number | null;
  captureDeviceInfo: string | null;
  captureSource: string | null;
  evidenceHash: string | null;
  imageHashes: ImageHash[] | null;
  forensicResultHash: string | null;
  agentDecisionHash: string | null;
  chainOfCustody: CustodyEvent[] | null;
  hasTimestamp: boolean;
  timestampedAt: string | null;
  timestampAuthority: string | null;
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

export interface AdminStats {
  totalUsers: number;
  activeUsers: number;
  usersRegisteredToday: number;
  usersRegisteredThisWeek: number;
  totalInspections: number;
  completedInspections: number;
  pendingInspections: number;
  analyzingInspections: number;
  failedInspections: number;
  averageProcessingTimeMs: number;
  queuePending: number;
  queueActiveUsers: number;
  analysesPerDay: { date: string; count: number }[];
  analysesPerHour: { hour: number; count: number }[];
  analysesPerDayOfWeek: { day: number; count: number }[];
  riskLevelDistribution: Record<string, number>;
  verdictDistribution: Record<string, number>;
  decisionOutcomeDistribution: Record<string, number>;
  fileTypeDistribution: Record<string, number>;
  fraudRiskDistribution: Record<string, number>;
  captureSourceDistribution: Record<string, number>;
  processingTimeP50: number;
  processingTimeP90: number;
  processingTimeP95: number;
  processingTimeP99: number;
  usersPerDay: { date: string; count: number }[];
  averageFraudRiskScore: number;
  recentFailures: {
    id: string;
    originalFileName: string;
    errorMessage: string | null;
    userFullName: string | null;
    createdAt: string;
  }[];
}
