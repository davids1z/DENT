/**
 * Group document forensic findings into user-friendly categories
 * for the DocumentForensicsView sidebar.
 */

import type { ForensicFinding, ForensicModuleResult } from "@/lib/api";

export interface FindingCategory {
  id: string;
  label: string;
  icon: string;
  findings: ForensicFinding[];
  maxRisk: number;
}

// Category definitions — order matters (displayed top-to-bottom)
const CATEGORY_DEFS: { id: string; label: string; icon: string; prefixes: string[] }[] = [
  {
    id: "signatures",
    label: "Potpisi i redakcija",
    icon: "shield",
    prefixes: ["DOC_SIG_", "DOC_FAKE_REDACTION"],
  },
  {
    id: "security",
    label: "Sigurnosne prijetnje",
    icon: "alert",
    prefixes: ["DOC_SHADOW_", "DOC_FORM_OVERLAY_", "DOC_EVIL_", "DOC_DANGEROUS_", "DOC_XFA_"],
  },
  {
    id: "visual",
    label: "Vizualna analiza",
    icon: "eye",
    prefixes: ["DOC_VISUAL_", "DOC_VERSION_", "DOC_EMBEDDED_"],
  },
  {
    id: "fonts",
    label: "Fontovi i tekst",
    icon: "type",
    prefixes: ["DOC_FONT_", "DOC_ZERO_WIDTH_", "DOC_MIXED_SCRIPTS", "DOC_CHAR_METRICS_"],
  },
  {
    id: "structure",
    label: "Struktura i revizije",
    icon: "layers",
    prefixes: ["DOC_MULTIPLE_", "DOC_INCREMENTAL_", "DOC_META_", "DOC_ORPHANED_"],
  },
  {
    id: "content",
    label: "Sadržaj i kodiranje",
    icon: "code",
    prefixes: ["DOC_COLORSPACE_", "DOC_COMPRESSION_", "DOC_TOUNICODE_", "DOC_ACTUALTEXT_", "DOC_PRIVATE_", "DOC_OCG_"],
  },
];

/**
 * Group findings from document_forensics module into display categories.
 * Returns only categories that have at least one finding OR are important enough to show empty.
 */
export function groupDocumentFindings(modules: ForensicModuleResult[]): FindingCategory[] {
  // Collect all findings from document-related modules
  const allFindings: ForensicFinding[] = [];
  const docModuleNames = ["document_forensics", "text_ai_detection", "content_validation", "office_forensics"];

  for (const mod of modules) {
    if (docModuleNames.includes(mod.moduleName)) {
      allFindings.push(...mod.findings);
    }
  }

  // Add text_ai and content_validation as their own pseudo-category if they have findings
  const textAiFindings = modules
    .filter(m => m.moduleName === "text_ai_detection")
    .flatMap(m => m.findings);
  const contentValFindings = modules
    .filter(m => m.moduleName === "content_validation")
    .flatMap(m => m.findings);

  const categories: FindingCategory[] = [];

  for (const def of CATEGORY_DEFS) {
    const matched = allFindings.filter(f =>
      def.prefixes.some(p => f.code.startsWith(p))
    );
    categories.push({
      id: def.id,
      label: def.label,
      icon: def.icon,
      findings: matched,
      maxRisk: matched.length > 0 ? Math.max(...matched.map(f => f.riskScore)) : 0,
    });
  }

  // Add AI text detection as separate category if it has findings
  if (textAiFindings.length > 0) {
    categories.push({
      id: "text_ai",
      label: "AI tekst detekcija",
      icon: "sparkles",
      findings: textAiFindings,
      maxRisk: Math.max(...textAiFindings.map(f => f.riskScore)),
    });
  }

  // Add content validation as separate category if it has findings
  if (contentValFindings.length > 0) {
    categories.push({
      id: "content_val",
      label: "Validacija sadržaja",
      icon: "check",
      findings: contentValFindings,
      maxRisk: Math.max(...contentValFindings.map(f => f.riskScore)),
    });
  }

  // Sort: categories with findings first (by max risk desc), empty categories last
  categories.sort((a, b) => {
    if (a.findings.length > 0 && b.findings.length === 0) return -1;
    if (a.findings.length === 0 && b.findings.length > 0) return 1;
    return b.maxRisk - a.maxRisk;
  });

  return categories;
}

/**
 * Extract tool attribution from metadata findings.
 * Returns the editing software name if detected, null otherwise.
 */
export function extractToolAttribution(modules: ForensicModuleResult[]): string | null {
  for (const mod of modules) {
    if (mod.moduleName === "document_forensics") {
      for (const f of mod.findings) {
        if (f.code === "DOC_META_EDITING_SOFTWARE") {
          const ev = f.evidence as Record<string, unknown> | null;
          if (ev?.matched_software) return String(ev.matched_software);
          // Fallback: extract from description
          const match = f.description?.match(/softvera:\s*(.+?)(?:\s*\(|$)/);
          if (match) return match[1].trim();
        }
      }
    }
  }
  return null;
}

/**
 * Get overall document forensics risk score.
 */
export function getDocumentRiskScore(modules: ForensicModuleResult[]): { score: number; level: string } {
  const docMod = modules.find(m => m.moduleName === "document_forensics");
  if (docMod) return { score: docMod.riskScore, level: docMod.riskLevel };

  // Fallback: max across all document modules
  const docModules = modules.filter(m =>
    ["document_forensics", "text_ai_detection", "content_validation", "office_forensics"].includes(m.moduleName)
  );
  if (docModules.length === 0) return { score: 0, level: "Low" };

  const maxMod = docModules.reduce((a, b) => a.riskScore > b.riskScore ? a : b);
  return { score: maxMod.riskScore, level: maxMod.riskLevel };
}
