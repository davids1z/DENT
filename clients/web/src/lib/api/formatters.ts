import type { BoundingBox } from "./types";

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
    Scratch: "Ogrebotina", Dent: "Udubljenje", Crack: "Pukotina",
    PaintDamage: "Oštećenje boje", BrokenGlass: "Slomljeno staklo", Rust: "Hrđa",
    BodyDeformation: "Deformacija karoserije", BumperDamage: "Oštećenje branika",
    LightDamage: "Oštećenje svjetla", TireDamage: "Oštećenje gume",
    MirrorDamage: "Oštećenje retrovizora", Other: "Ostalo",
  };
  return labels[type] || type;
}

export function carPartLabel(part: string): string {
  const labels: Record<string, string> = {
    FrontBumper: "Prednji branik", RearBumper: "Stražnji branik",
    Hood: "Hauba", Trunk: "Prtljažnik",
    FrontLeftDoor: "Prednja lijeva vrata", FrontRightDoor: "Prednja desna vrata",
    RearLeftDoor: "Stražnja lijeva vrata", RearRightDoor: "Stražnja desna vrata",
    FrontLeftFender: "Prednji lijevi blatobran", FrontRightFender: "Prednji desni blatobran",
    RearLeftFender: "Stražnji lijevi blatobran", RearRightFender: "Stražnji desni blatobran",
    Roof: "Krov", Windshield: "Vjetrobransko staklo", RearWindow: "Stražnje staklo",
    SideWindowLeft: "Bočno staklo lijevo", SideWindowRight: "Bočno staklo desno",
    SideMirrorLeft: "Retrovizor lijevi", SideMirrorRight: "Retrovizor desni",
    HeadlightLeft: "Prednje svjetlo lijevo", HeadlightRight: "Prednje svjetlo desno",
    TaillightLeft: "Stražnje svjetlo lijevo", TaillightRight: "Stražnje svjetlo desno",
    WheelFrontLeft: "Kotač prednji lijevi", WheelFrontRight: "Kotač prednji desni",
    WheelRearLeft: "Kotač stražnji lijevi", WheelRearRight: "Kotač stražnji desni",
    Undercarriage: "Podvozje", Other: "Ostalo",
  };
  return labels[part] || part;
}

export function severityLabel(severity: string): string {
  const labels: Record<string, string> = {
    Minor: "Niska sumnja", Moderate: "Umjerena sumnja",
    Severe: "Visoka sumnja", Critical: "Kriticna sumnja",
  };
  return labels[severity] || severity;
}

export function urgencyLabel(urgency: string): string {
  const labels: Record<string, string> = {
    Low: "Niska", Medium: "Srednja", High: "Visoka", Critical: "Kritična",
  };
  return labels[urgency] || urgency;
}

export function repairCategoryLabel(category: string): string {
  const labels: Record<string, string> = { Replace: "Zamjena", Repair: "Popravak", Polish: "Poliranje" };
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
  const labels: Record<string, string> = { Safe: "Autenticno", Warning: "Sumnjivo", Critical: "Krivotvoreno" };
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
    AutoApprove: "Autenticno", HumanReview: "Potreban pregled", Escalate: "Sumnja na krivotvorinu",
  };
  return labels[outcome] || outcome;
}

export function findingCategoryLabel(cause: string | null): string {
  if (!cause) return "Nepoznato";
  const labels: Record<string, string> = {
    "AI generiranje": "AI generiranje", "Digitalna manipulacija": "Digitalna manipulacija",
    "Copy-paste krivotvorina": "Copy-paste krivotvorina", "Rekompresijski artefakti": "Rekompresijski artefakti",
    "Nekonzistentno osvjetljenje": "Nekonzistentno osvjetljenje", "Metadata anomalija": "Metadata anomalija",
    "Deepfake indikator": "Deepfake indikator", "Sumnjiva tekstura": "Sumnjiva tekstura",
    "Perspektivna anomalija": "Perspektivna anomalija", "Spektralna anomalija": "Spektralna anomalija",
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
    Body: "Limarija", Refinish: "Lakiranje", Mechanical: "Mehanika",
    Electrical: "Elektrika", Glass: "Staklo",
  };
  return labels[type] || type;
}

export function fraudRiskLabel(level: string): string {
  const labels: Record<string, string> = {
    Low: "Nizak rizik", Medium: "Srednji rizik", High: "Visok rizik", Critical: "Kritican rizik",
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
    metadata_analysis: "Analiza metapodataka", modification_detection: "Detekcija modifikacija",
    deep_modification_detection: "Duboka analiza modifikacija (CNN)", optical_forensics: "Opticka forenzika",
    semantic_forensics: "Semanticka forenzika", document_forensics: "Forenzika dokumenata",
    office_forensics: "Office dokument forenzika", ai_generation_detection: "Detekcija AI generiranja",
    spectral_forensics: "Spektralna forenzika", clip_ai_detection: "CLIP AI detekcija",
    dinov2_ai_detection: "DINOv2 AI detekcija", safe_ai_detection: "SAFE AI detekcija",
    efficientnet_ai_detection: "EfficientNet AI detekcija",
    community_forensics_detection: "Community Forensics detekcija",
    npr_ai_detection: "NPR detekcija artefakata", mesorch_detection: "Mesorch detekcija manipulacija",
    bfree_detection: "B-Free AI detekcija (CVPR 2025)", spai_detection: "SPAI spektralna AI detekcija (CVPR 2025)",
    vae_reconstruction: "VAE rekonstrukcija", text_ai_detection: "AI tekst detekcija",
    content_validation: "Validacija sadrzaja", prnu_detection: "PRNU senzorska analiza",
  };
  return labels[moduleName] || moduleName;
}

export function custodyEventLabel(event: string): string {
  const labels: Record<string, string> = {
    image_received: "Slika zaprimljena", analysis_complete: "Analiza dovršena",
    forensics_complete: "Forenzika dovršena", decision_complete: "Odluka donesena",
    evidence_sealed: "Dokazi zapečaćeni", timestamp_failed: "Vremenski pečat neuspješan",
  };
  return labels[event] || event;
}
