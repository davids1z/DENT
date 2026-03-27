import type { ForensicResult, ForensicModuleResult, ForensicFinding, DamageDetection } from "./api";
import { findingCategoryLabel, forensicModuleLabel } from "./api";

// ── Pillar definitions ─────────────────────────────────────────

export interface ForensicPillar {
  id: string;
  label: string;
  icon: string;
  moduleNames: string[];
  heatmapField?: keyof ForensicResult;
  description: string;
}

export const FORENSIC_PILLARS: ForensicPillar[] = [
  {
    id: "ai_detection",
    label: "AI detekcija",
    icon: "sparkles",
    moduleNames: [
      "safe_ai_detection",           // SAFE (KDD 2025) — pixel correlation
      "dinov2_ai_detection",         // DINOv2 probe
      "community_forensics_detection", // CommFor (CVPR 2025)
      "efficientnet_ai_detection",   // EfficientNet-B4 pre-trained
      "clip_ai_detection",           // CLIP ViT-L/14 probe
    ],
    description: "5 nezavisnih AI detektora: SAFE, DINOv2, CommFor, EfficientNet, CLIP",
  },
  {
    id: "modification",
    label: "Detekcija manipulacija",
    icon: "pencil",
    moduleNames: ["modification_detection", "mesorch_detection"],
    heatmapField: "elaHeatmapUrl",
    description: "ELA, copy-move, Mesorch (AAAI 2025) detekcija manipulacija",
  },
  {
    id: "crypto_meta",
    label: "Metapodaci i potpisi",
    icon: "lock",
    moduleNames: ["metadata_analysis", "prnu_detection"],
    description: "EXIF analiza, C2PA potpis, PRNU senzorski otisak",
  },
  {
    id: "documents",
    label: "Forenzika dokumenata",
    icon: "file",
    moduleNames: ["document_forensics", "office_forensics", "text_ai_detection", "content_validation"],
    description: "PDF struktura, AI tekst, OIB/IBAN validacija",
  },
];

// ── Pillar data ────────────────────────────────────────────────

export type PillarStatus = "pass" | "warning" | "fail";

export interface PillarData {
  pillar: ForensicPillar;
  modules: ForensicModuleResult[];
  aggregateRiskScore: number;
  aggregateRiskLevel: string;
  findings: ForensicFinding[];
  hasError: boolean;
  heatmapUrl: string | null;
  fftSpectrumUrl: string | null;
}

export function groupModulesIntoPillars(
  modules: ForensicModuleResult[],
  result: ForensicResult,
): PillarData[] {
  return FORENSIC_PILLARS.map((pillar) => {
    const pillarModules = modules.filter((m) =>
      pillar.moduleNames.includes(m.moduleName),
    );
    if (pillarModules.length === 0) return null;

    const maxRisk = Math.max(...pillarModules.map((m) => m.riskScore), 0);
    const riskOrder: Record<string, number> = { Low: 0, Medium: 1, High: 2, Critical: 3 };
    const worstLevel = pillarModules.reduce(
      (worst, m) => ((riskOrder[m.riskLevel] ?? 0) > (riskOrder[worst] ?? 0) ? m.riskLevel : worst),
      "Low",
    );
    const allFindings = pillarModules.flatMap((m) => m.findings);
    const hasError = pillarModules.some((m) => m.error);
    const heatmapUrl = pillar.heatmapField
      ? (result[pillar.heatmapField] as string | null)
      : null;

    return {
      pillar,
      modules: pillarModules,
      aggregateRiskScore: maxRisk,
      aggregateRiskLevel: worstLevel,
      findings: allFindings,
      hasError,
      heatmapUrl,
      fftSpectrumUrl: pillar.id === "spectral" ? result.fftSpectrumUrl : null,
    };
  }).filter(Boolean) as PillarData[];
}

export function getPillarStatus(riskScore: number): PillarStatus {
  if (riskScore >= 0.50) return "fail";
  if (riskScore >= 0.25) return "warning";
  return "pass";
}

// ── Text helpers ───────────────────────────────────────────────

export function sanitizeLlmText(text: string): string {
  return text.replace(/\s*\[C#\s*safety\s*net:[^\]]*\]/gi, "").trim();
}

export function getVerdictSentence(
  riskLevel: string,
  riskScore: number,
  c2paStatus: string | null,
): string {
  const pct = Math.round(riskScore * 100);
  switch (riskLevel) {
    case "Low":
      return c2paStatus === "valid"
        ? "Slika ima valjan kriptografski potpis i ne pokazuje znakove manipulacije."
        : "Forenzicka analiza nije utvrdila znakove manipulacije.";
    case "Medium":
      return `Forenzicka analiza ukazuje na umjerenu sumnju (${pct}%). Preporuca se rucni pregled.`;
    case "High":
      return `Utvrdjena visoka sumnja na manipulaciju (${pct}%). Vise modula detektiralo anomalije.`;
    case "Critical":
      return `Kriticna razina rizika (${pct}%). Snazni dokazi manipulacije ili AI generiranja.`;
    default:
      return "Analiza u tijeku.";
  }
}

const MODULE_TO_CATEGORY: Record<string, string> = {
  safe_ai_detection: "AI generiranje",
  dinov2_ai_detection: "AI generiranje",
  community_forensics_detection: "AI generiranje",
  efficientnet_ai_detection: "AI generiranje",
  clip_ai_detection: "AI generiranje",
  ai_generation_detection: "AI generiranje",
  modification_detection: "Digitalna manipulacija",
  mesorch_detection: "Digitalna manipulacija",
  deep_modification_detection: "Digitalna manipulacija",
  prnu_detection: "Senzorska anomalija",
  metadata_analysis: "Metadata anomalija",
  document_forensics: "Dokument anomalija",
  office_forensics: "Dokument anomalija",
  text_ai_detection: "AI generirani tekst",
  content_validation: "Nevalidni identifikatori",
};

export function deriveFindingCategory(
  damage: DamageDetection,
  forensicResult: ForensicResult | null,
): string {
  // Smart category derivation from description content
  const desc = (damage.description || "").toLowerCase();

  // If description indicates authenticity, label as "Autenticno"
  const authenticKeywords = [
    "autentičn", "konzistentn", "realistič", "plauzibil",
    "potvrđuje autentičnost", "ne pokazuje znakove",
    "fizički ispravne", "nema naznaka",
  ];
  const isAuthentic = authenticKeywords.some((kw) => desc.includes(kw));

  // If description indicates manipulation
  const manipKeywords = [
    "manipulacij", "krivotvor", "montaž", "zamućen",
    "prebrisano", "zalijepljen", "kopiran", "splice",
  ];
  const isManipulated = manipKeywords.some((kw) => desc.includes(kw));

  // If description indicates AI generation
  const aiKeywords = [
    "ai gener", "umjetn", "sintetič", "generirano",
    "stable diffusion", "midjourney", "dall-e",
  ];
  const isAI = aiKeywords.some((kw) => desc.includes(kw));

  if (isAuthentic && !isManipulated && !isAI) {
    return "Autenticno";
  }
  if (isManipulated) {
    return "Digitalna manipulacija";
  }
  if (isAI) {
    return "AI generiranje";
  }

  // Fallback: use module-based detection
  if (damage.damageCause === "Metadata anomalija" && forensicResult) {
    const highRiskModules = forensicResult.modules
      .filter((m) => m.riskScore >= 0.40)
      .sort((a, b) => b.riskScore - a.riskScore);
    if (highRiskModules.length > 0) {
      const topModule = highRiskModules[0].moduleName;
      return MODULE_TO_CATEGORY[topModule] || damage.damageCause || "Nepoznato";
    }
  }
  return findingCategoryLabel(damage.damageCause);
}

export { forensicModuleLabel };
