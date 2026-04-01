/**
 * Extract page numbers and bounding box rectangles from document forensic findings.
 * Different finding types store bbox data in different evidence structures.
 */

import type { ForensicFinding } from "@/lib/api";

export interface BboxRect {
  x0: number;
  y0: number;
  x1: number;
  y1: number;
}

export interface PageBboxes {
  page: number;
  rects: BboxRect[];
  label?: string;
}

/**
 * Extract all page+bbox pairs from a forensic finding's evidence dict.
 * Returns empty array if finding has no spatial data.
 */
export function extractBboxes(finding: ForensicFinding): PageBboxes[] {
  const ev = finding.evidence;
  if (!ev) return [];

  const result: PageBboxes[] = [];

  // DOC_FAKE_REDACTION: evidence.fake_redactions[].{page, rect: [x0,y0,x1,y1]}
  if (finding.code === "DOC_FAKE_REDACTION" && Array.isArray(ev.fake_redactions)) {
    const byPage = groupByPage(ev.fake_redactions as BboxItem[], "rect");
    result.push(...byPage.map(g => ({ ...g, label: "Lažna redakcija" })));
  }

  // DOC_SHADOW_HIDE_ATTACK: evidence.overlays[].{page, overlay_rect: [x0,y0,x1,y1]}
  if (finding.code === "DOC_SHADOW_HIDE_ATTACK" && Array.isArray(ev.overlays)) {
    const byPage = groupByPage(ev.overlays as BboxItem[], "overlay_rect");
    result.push(...byPage.map(g => ({ ...g, label: "Shadow napad" })));
  }

  // DOC_FORM_OVERLAY_ATTACK / DOC_FORM_OVERLAY_SUSPICIOUS: evidence.suspicious_fields[].{page, rect}
  if ((finding.code === "DOC_FORM_OVERLAY_ATTACK" || finding.code === "DOC_FORM_OVERLAY_SUSPICIOUS")
      && Array.isArray(ev.suspicious_fields)) {
    const byPage = groupByPage(ev.suspicious_fields as BboxItem[], "rect");
    result.push(...byPage.map(g => ({ ...g, label: "Form overlay" })));
  }

  // DOC_EVIL_ANNOTATION_ATTACK / DOC_SUSPICIOUS_ANNOTATION_OVERLAY: evidence.evil_annotations[].{page, rect}
  if ((finding.code === "DOC_EVIL_ANNOTATION_ATTACK" || finding.code === "DOC_SUSPICIOUS_ANNOTATION_OVERLAY")
      && Array.isArray(ev.evil_annotations)) {
    const byPage = groupByPage(ev.evil_annotations as BboxItem[], "rect");
    result.push(...byPage.map(g => ({ ...g, label: "Evil annotation" })));
  }

  // DOC_VERSION_MAJOR_CHANGE / DOC_VERSION_CHANGE: evidence.diffs[].{page, change_bbox: {top,left,bottom,right}}
  if ((finding.code === "DOC_VERSION_MAJOR_CHANGE" || finding.code === "DOC_VERSION_CHANGE"
       || finding.code === "DOC_VERSION_MINOR_CHANGE") && Array.isArray(ev.diffs)) {
    for (const diff of ev.diffs as VersionDiff[]) {
      if (diff.page && diff.change_bbox) {
        const bb = diff.change_bbox;
        result.push({
          page: diff.page,
          rects: [{ x0: bb.left, y0: bb.top, x1: bb.right, y1: bb.bottom }],
          label: "Promjena između verzija",
        });
      }
    }
  }

  return result;
}

/** Check if a finding has any bbox data worth showing */
export function hasBboxData(finding: ForensicFinding): boolean {
  return extractBboxes(finding).length > 0;
}

// ── Internal types ──

interface BboxItem {
  page?: number;
  rect?: number[];
  overlay_rect?: number[];
  [key: string]: unknown;
}

interface VersionDiff {
  page?: number;
  change_bbox?: { top: number; left: number; bottom: number; right: number };
  [key: string]: unknown;
}

function groupByPage(items: BboxItem[], rectKey: string): PageBboxes[] {
  const pageMap = new Map<number, BboxRect[]>();

  for (const item of items) {
    const page = item.page;
    const rectArr = item[rectKey] as number[] | undefined;
    if (!page || !rectArr || rectArr.length < 4) continue;

    const rect: BboxRect = { x0: rectArr[0], y0: rectArr[1], x1: rectArr[2], y1: rectArr[3] };
    const existing = pageMap.get(page);
    if (existing) existing.push(rect);
    else pageMap.set(page, [rect]);
  }

  return Array.from(pageMap.entries()).map(([page, rects]) => ({ page, rects }));
}
