/**
 * Single source of truth for risk thresholds across the entire frontend.
 *
 * Before this file existed (2026-04-07), the frontend had at least 5 different
 * threshold systems:
 *   - VerdictDashboard badge: hard cuts at 20 / 75
 *   - VerdictDashboard gauge color: 15 / 35 / 55 / 75
 *   - VerdictDashboard gauge label: 15 / 35 / 55 / 75 (different from color!)
 *   - forensicPillars getPillarStatus: 25 / 50
 *   - ForensicModuleTable consensus: 30 / 20
 *
 * Result: a 24% authentic image showed pillar=Pass(green), gauge=Umjeren(teal),
 * badge=AMBER, all simultaneously. Confusing.
 *
 * This file aligns ALL of those onto the same 5-band scale, which matches the
 * backend RiskLevel enum (Low/Medium/High/Critical) plus a "VeryLow" band for
 * the cleanest images.
 *
 * The bands are designed so that:
 *   - The badge color (red/amber/green) matches the pillar status (fail/warn/pass)
 *   - The gauge color matches the risk label
 *   - The backend's RiskLevel.HIGH boundary at 0.40 maps to "Povišen" (raised)
 *
 * Backend boundaries (from thresholds.py):
 *   risk_medium = 0.20
 *   risk_high   = 0.40
 *   risk_critical = 0.85
 */

export type RiskBandId = "very_low" | "low" | "moderate" | "raised" | "high" | "critical";

export interface RiskBand {
  id: RiskBandId;
  /** Inclusive lower bound, score in [0, 1]. */
  min: number;
  /** Exclusive upper bound, score in [0, 1]. */
  max: number;
  /** Croatian label shown to users. */
  label: string;
  /** Three-state group used by pillar/badge/dot color. */
  status: "pass" | "warning" | "fail";
  /** Tailwind color name (used to build classnames). */
  color: "emerald" | "green" | "amber" | "orange" | "red";
  /** Hex color used by gauge SVG. */
  hex: string;
}

export const RISK_BANDS: RiskBand[] = [
  {
    id: "very_low",
    min: 0.0,
    max: 0.10,
    label: "Vrlo nizak",
    status: "pass",
    color: "emerald",
    hex: "#34D399",
  },
  {
    id: "low",
    min: 0.10,
    max: 0.20,
    label: "Nizak",
    status: "pass",
    color: "green",
    hex: "#22C55E",
  },
  {
    id: "moderate",
    min: 0.20,
    max: 0.40,
    label: "Umjeren",
    status: "warning",
    color: "amber",
    hex: "#FBBF24",
  },
  {
    id: "raised",
    min: 0.40,
    max: 0.65,
    label: "Povišen",
    status: "fail",
    color: "orange",
    hex: "#F97316",
  },
  {
    id: "high",
    min: 0.65,
    max: 0.85,
    label: "Visok",
    status: "fail",
    color: "orange",
    hex: "#EA580C",
  },
  {
    id: "critical",
    min: 0.85,
    max: 1.01, // upper bound exclusive — 1.01 ensures 1.0 lands here
    label: "Kritičan",
    status: "fail",
    color: "red",
    hex: "#EF4444",
  },
];

/**
 * Look up the risk band for a given score in [0, 1].
 */
export function getRiskBand(score: number): RiskBand {
  // Clamp negatives / NaNs to 0; values >1 fall into the critical band naturally.
  const s = Number.isFinite(score) ? Math.max(0, score) : 0;
  for (const band of RISK_BANDS) {
    if (s >= band.min && s < band.max) return band;
  }
  return RISK_BANDS[RISK_BANDS.length - 1];
}

/**
 * Look up the risk band for a percentage in [0, 100].
 */
export function getRiskBandPct(percent: number): RiskBand {
  return getRiskBand((percent ?? 0) / 100);
}

/**
 * Returns "pass" / "warning" / "fail" for a score in [0, 1] — used by pillar
 * status indicators and badge color logic.
 */
export function getRiskStatus(score: number): "pass" | "warning" | "fail" {
  return getRiskBand(score).status;
}

/**
 * Returns the Croatian label for a score in [0, 1].
 */
export function getRiskLabel(score: number): string {
  return getRiskBand(score).label;
}

/**
 * Returns a hex color string for use in SVG (e.g., gauge stroke).
 */
export function getRiskHex(score: number): string {
  return getRiskBand(score).hex;
}

/**
 * Threshold used for the "elevated module" count in the consensus summary.
 * Matches backend Medium boundary.
 */
export const ELEVATED_MODULE_THRESHOLD = 0.30;

/**
 * Threshold used for the "low risk" module count in the consensus summary.
 */
export const LOW_MODULE_THRESHOLD = 0.20;
