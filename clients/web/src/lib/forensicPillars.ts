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
    id: "crypto_meta",
    label: "Kriptografija i metapodaci",
    icon: "lock",
    moduleNames: ["metadata_analysis"],
    description: "C2PA potpis, EXIF metapodaci, hash konzistentnost",
  },
  {
    id: "sensor",
    label: "Senzorska forenzika",
    icon: "cpu",
    moduleNames: ["prnu_detection"],
    description: "PRNU senzorski otisak kamere",
  },
  {
    id: "ai_detection",
    label: "AI detekcija",
    icon: "sparkles",
    moduleNames: ["ai_generation_detection", "clip_ai_detection", "vae_reconstruction"],
    description: "CNN, CLIP i VAE detekcija AI-generiranih slika",
  },
  {
    id: "modification",
    label: "Detekcija modifikacija",
    icon: "pencil",
    moduleNames: ["modification_detection", "deep_modification_detection"],
    heatmapField: "elaHeatmapUrl",
    description: "ELA, copy-move, JPEG artefakti, CNN manipulacije",
  },
  {
    id: "spectral",
    label: "Spektralna analiza",
    icon: "signal",
    moduleNames: ["spectral_forensics", "optical_forensics"],
    heatmapField: "spectralHeatmapUrl",
    description: "FFT spektar, fazna koherencija, frekvencijske anomalije",
  },
  {
    id: "semantic",
    label: "Semanticka analiza",
    icon: "brain",
    moduleNames: ["semantic_forensics"],
    description: "VLM provjera sjena, teksta i perspektive",
  },
  {
    id: "documents",
    label: "Forenzika dokumenata",
    icon: "file",
    moduleNames: ["document_forensics", "office_forensics", "text_ai_detection", "content_validation"],
    description: "PDF, Office, AI tekst, OIB/IBAN validacija",
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
  ai_generation_detection: "AI generiranje",
  clip_ai_detection: "AI generiranje",
  vae_reconstruction: "AI generiranje",
  modification_detection: "Digitalna manipulacija",
  deep_modification_detection: "Digitalna manipulacija",
  spectral_forensics: "Spektralna anomalija",
  optical_forensics: "Nekonzistentno osvjetljenje",
  prnu_detection: "Sumnjiva tekstura",
  semantic_forensics: "Perspektivna anomalija",
  metadata_analysis: "Metadata anomalija",
  document_forensics: "Digitalna manipulacija",
  office_forensics: "Digitalna manipulacija",
  text_ai_detection: "AI generiranje",
  content_validation: "Digitalna manipulacija",
};

export function deriveFindingCategory(
  damage: DamageDetection,
  forensicResult: ForensicResult | null,
): string {
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
