import type { ForensicResult, ForensicModuleResult, ForensicFinding, DamageDetection } from "./api";
import { findingCategoryLabel, forensicModuleLabel } from "./api";
import { getRiskStatus } from "./riskThresholds";

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
      "safe_ai_detection",             // SAFE (KDD 2025) — pixel correlation
      "dinov2_ai_detection",           // DINOv2 probe
      "community_forensics_detection", // CommFor (CVPR 2025)
      "efficientnet_ai_detection",     // EfficientNet-B4 pre-trained
      "clip_ai_detection",             // CLIP ViT-L/14 probe
      "bfree_detection",               // B-Free (CVPR 2025) — bias-free DINOv2
      "spai_detection",                // SPAI (CVPR 2025) — FFT spectral
      "rine_detection",                // RINE (ECCV 2024) — intermediate CLIP
      "organika_ai_detection",        // Organika Swin (98.1% accuracy)
      "ai_source_detection",          // AI Source ViT-Base (91.6% acc, SD/MJ/DALL-E)
      "pixel_forensics",              // 8 pixel-level signals
      "siglip_ai_detection",           // SigLIP fine-tuned (99.23% acc)
      "ai_generation_detection",       // EfficientNet legacy AI gen
      "vae_reconstruction",            // VAE reconstruction anomaly
      "npr_ai_detection",              // NPR AI detection
    ],
    description: "10 nezavisnih AI detektora: SAFE, DINOv2, CommFor, EfficientNet, CLIP, B-Free, SPAI, VAE, NPR",
  },
  {
    id: "modification",
    label: "Detekcija manipulacija",
    icon: "pencil",
    moduleNames: [
      "modification_detection",        // ELA + heuristic
      "mesorch_detection",             // Mesorch (AAAI 2025)
      "deep_modification_detection",   // CNN deep modification
    ],
    heatmapField: "elaHeatmapUrl",
    description: "ELA, copy-move, CNN duboka analiza, Mesorch (AAAI 2025)",
  },
  {
    id: "crypto_meta",
    label: "Metapodaci i potpisi",
    icon: "lock",
    moduleNames: [
      "metadata_analysis",             // EXIF/metadata
      "prnu_detection",                // PRNU sensor fingerprint
      "spectral_forensics",            // Spectral/frequency analysis
      "optical_forensics",             // Optical forensics
      "semantic_forensics",            // Semantic analysis
    ],
    description: "EXIF analiza, C2PA potpis, PRNU senzorski otisak, spektralna i optička forenzika",
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

// Modules that are unreliable for the pillar aggregate. They are still shown
// individually so the user can see them, but they cannot drive the pillar score.
//
// Two reasons for exclusion:
//   1) DEAD ON MODERN AI: returns ~0 even on obvious AI generators (RINE, B-Free,
//      SPAI, NPR, VAE, EfficientNet, SigLIP, AI Source, SAFE).
//   2) HIGH FALSE-POSITIVE BIAS on car damage photos (DINOv2).
//
// Note: community_forensics is NO LONGER in this set as of PR #32 because
// production stats showed +25.8pp gap (it's actually one of the strongest
// discriminators). It now contributes to both pillar score AND fusion weight.
const _DEAD_AI_MODULES = new Set<string>([
  "rine_detection",
  "bfree_detection",
  "spai_detection",
  "npr_ai_detection",
  "vae_reconstruction",
  "efficientnet_ai_detection",
  "siglip_ai_detection",
  "ai_source_detection",
  "safe_ai_detection",
  "dinov2_ai_detection",
]);

// AI detection pillar weighted aggregation — MUST stay in sync with the
// backend _CORE_AI_WEIGHTS in services/ml-service/app/forensics/fusion.py.
// These weights reflect production-discriminative power (Day 4 of path-to-95):
//   organika_ai_detection         +39.3pp gap (best)
//   community_forensics_detection +25.8pp gap
//   clip_ai_detection             +11.5pp gap
//   pixel_forensics               +10.9pp gap
//   dinov2_ai_detection           +6.4pp gap (capped, dead in pillar)
//   ai_generation_detection       legacy
//
// Sum is 1.00. The pillar uses these exact weights so the displayed pillar
// score matches what fusion.py would compute as core_score for the same
// modules. This fixes the UX issue where pixel_forensics at 0.29 alone
// would push the pillar to amber even though it contributes only 2.9% to
// the actual fused result.
const _CORE_AI_WEIGHTS_FRONTEND: Record<string, number> = {
  clip_ai_detection: 0.30,
  organika_ai_detection: 0.35,
  community_forensics_detection: 0.15,
  pixel_forensics: 0.10,
  dinov2_ai_detection: 0.02,
  ai_generation_detection: 0.08,
};

export function groupModulesIntoPillars(
  modules: ForensicModuleResult[],
  result: ForensicResult,
): PillarData[] {
  return FORENSIC_PILLARS.map((pillar) => {
    const pillarModules = modules.filter((m) =>
      pillar.moduleNames.includes(m.moduleName),
    );
    if (pillarModules.length === 0) return null;

    // For the AI detection pillar, compute the WEIGHTED contribution that
    // matches the backend fusion's core_score formula. This way a single
    // weak signal (e.g. pixel_forensics at 0.29 with weight 0.10 → 2.9%
    // contribution) doesn't push the entire pillar into the warning band.
    //
    // For other pillars (tampering, metadata) we keep the MAX behavior
    // because they don't have the weighted-fusion structure.
    const liveModules = pillar.id === "ai_detection"
      ? pillarModules.filter((m) => !_DEAD_AI_MODULES.has(m.moduleName) && !m.error)
      : pillarModules.filter((m) => !m.error);
    const scoreSource = liveModules.length > 0 ? liveModules : pillarModules;

    let aggregateRisk: number;
    if (pillar.id === "ai_detection") {
      // Weighted aggregation matching backend _CORE_AI_WEIGHTS
      let weightedSum = 0;
      let totalWeight = 0;
      for (const m of scoreSource) {
        const w = _CORE_AI_WEIGHTS_FRONTEND[m.moduleName] ?? 0;
        if (w > 0) {
          weightedSum += m.riskScore * w;
          totalWeight += w;
        }
      }
      aggregateRisk = totalWeight > 0 ? weightedSum / totalWeight : 0;
    } else {
      // Non-AI pillars use MAX (tampering, metadata)
      aggregateRisk = scoreSource.reduce(
        (max, m) => (m.riskScore > max ? m.riskScore : max),
        0,
      );
    }

    const riskOrder: Record<string, number> = { Low: 0, Medium: 1, High: 2, Critical: 3 };
    const worstLevel = scoreSource.reduce(
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
      aggregateRiskScore: aggregateRisk,
      aggregateRiskLevel: worstLevel,
      findings: allFindings,
      hasError,
      heatmapUrl,
      fftSpectrumUrl: pillar.id === "spectral" ? result.fftSpectrumUrl : null,
    };
  }).filter(Boolean) as PillarData[];
}

export function getPillarStatus(riskScore: number): PillarStatus {
  // Delegates to the canonical risk-band system in riskThresholds.ts so
  // pillar status, badge color, gauge color, and consensus thresholds all
  // come from a single source of truth. Score >= 0.40 (Povišen) → fail,
  // score >= 0.20 (Umjeren) → warning, otherwise pass.
  return getRiskStatus(riskScore);
}

// ── Text helpers ───────────────────────────────────────────────

export function sanitizeLlmText(text: string | null | undefined): string {
  if (!text) return "";
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
        : "Forenzička analiza nije utvrdila znakove manipulacije.";
    case "Medium":
      return `Forenzička analiza ukazuje na umjerenu sumnju (${pct}%). Preporučuje se ručni pregled.`;
    case "High":
      return `Utvrđena visoka sumnja na manipulaciju (${pct}%). Više modula detektiralo anomalije.`;
    case "Critical":
      return `Kritična razina rizika (${pct}%). Snažni dokazi manipulacije ili AI generiranja.`;
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
  ai_source_detection: "AI generiranje",
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
