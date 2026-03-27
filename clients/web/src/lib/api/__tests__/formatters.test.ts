import { describe, it, expect } from "vitest";
import {
  formatCurrency,
  formatDate,
  severityColor,
  severityBg,
  damageTypeLabel,
  carPartLabel,
  severityLabel,
  urgencyLabel,
  safetyRatingLabel,
  safetyRatingColor,
  decisionOutcomeLabel,
  decisionOutcomeColor,
  fraudRiskLabel,
  fraudRiskColor,
  forensicModuleLabel,
  parseBoundingBox,
  repairCategoryLabel,
  laborTypeLabel,
  custodyEventLabel,
} from "../formatters";

describe("formatCurrency", () => {
  it("formats EUR amounts in Croatian locale", () => {
    const result = formatCurrency(1234.5);
    expect(result).toContain("1.234");
  });

  it("returns N/A for null", () => {
    expect(formatCurrency(null)).toBe("N/A");
  });
});

describe("formatDate", () => {
  it("formats ISO date to Croatian format", () => {
    const result = formatDate("2026-03-27T12:30:00Z");
    expect(result).toMatch(/27/);
    expect(result).toMatch(/03/);
    expect(result).toMatch(/2026/);
  });
});

describe("severityColor", () => {
  it("returns green for minor", () => {
    expect(severityColor("minor")).toBe("text-green-600");
    expect(severityColor("Minor")).toBe("text-green-600");
  });

  it("returns red for critical", () => {
    expect(severityColor("critical")).toBe("text-red-600");
  });

  it("returns gray for unknown", () => {
    expect(severityColor("unknown")).toBe("text-gray-500");
  });
});

describe("severityBg", () => {
  it("returns correct bg for each severity", () => {
    expect(severityBg("minor")).toContain("bg-green-50");
    expect(severityBg("moderate")).toContain("bg-amber-50");
    expect(severityBg("severe")).toContain("bg-orange-50");
    expect(severityBg("critical")).toContain("bg-red-50");
  });
});

describe("damageTypeLabel", () => {
  it("translates known types", () => {
    expect(damageTypeLabel("Scratch")).toBe("Ogrebotina");
    expect(damageTypeLabel("Dent")).toBe("Udubljenje");
    expect(damageTypeLabel("Crack")).toBe("Pukotina");
  });

  it("returns raw value for unknown types", () => {
    expect(damageTypeLabel("Unknown")).toBe("Unknown");
  });
});

describe("carPartLabel", () => {
  it("translates known parts", () => {
    expect(carPartLabel("FrontBumper")).toBe("Prednji branik");
    expect(carPartLabel("Hood")).toBe("Hauba");
    expect(carPartLabel("Windshield")).toBe("Vjetrobransko staklo");
  });
});

describe("severityLabel", () => {
  it("translates severity levels", () => {
    expect(severityLabel("Minor")).toBe("Niska sumnja");
    expect(severityLabel("Critical")).toBe("Kriticna sumnja");
  });
});

describe("urgencyLabel", () => {
  it("translates urgency levels", () => {
    expect(urgencyLabel("Low")).toBe("Niska");
    expect(urgencyLabel("Critical")).toBe("Kritična");
  });
});

describe("safetyRatingLabel", () => {
  it("translates ratings", () => {
    expect(safetyRatingLabel("Safe")).toBe("Autenticno");
    expect(safetyRatingLabel("Warning")).toBe("Sumnjivo");
    expect(safetyRatingLabel("Critical")).toBe("Krivotvoreno");
  });
});

describe("safetyRatingColor", () => {
  it("returns correct colors", () => {
    expect(safetyRatingColor("Safe")).toBe("text-green-600");
    expect(safetyRatingColor("Critical")).toBe("text-red-600");
  });
});

describe("decisionOutcomeLabel", () => {
  it("translates outcomes", () => {
    expect(decisionOutcomeLabel("AutoApprove")).toBe("Autenticno");
    expect(decisionOutcomeLabel("HumanReview")).toBe("Potreban pregled");
    expect(decisionOutcomeLabel("Escalate")).toBe("Sumnja na krivotvorinu");
  });
});

describe("decisionOutcomeColor", () => {
  it("returns correct colors", () => {
    expect(decisionOutcomeColor("AutoApprove")).toBe("text-green-600");
    expect(decisionOutcomeColor("Escalate")).toBe("text-red-600");
  });
});

describe("fraudRiskLabel", () => {
  it("translates risk levels", () => {
    expect(fraudRiskLabel("Low")).toBe("Nizak rizik");
    expect(fraudRiskLabel("Critical")).toBe("Kritican rizik");
  });
});

describe("fraudRiskColor", () => {
  it("returns correct colors", () => {
    expect(fraudRiskColor("Low")).toBe("text-green-600");
    expect(fraudRiskColor("High")).toBe("text-orange-600");
  });
});

describe("forensicModuleLabel", () => {
  it("translates module names", () => {
    expect(forensicModuleLabel("clip_ai_detection")).toBe("CLIP AI detekcija");
    expect(forensicModuleLabel("document_forensics")).toBe("Forenzika dokumenata");
  });

  it("returns raw name for unknown modules", () => {
    expect(forensicModuleLabel("unknown_module")).toBe("unknown_module");
  });
});

describe("parseBoundingBox", () => {
  it("parses valid JSON", () => {
    const box = parseBoundingBox('{"x":0.1,"y":0.2,"w":0.3,"h":0.4}');
    expect(box).toEqual({ x: 0.1, y: 0.2, w: 0.3, h: 0.4, imageIndex: 0 });
  });

  it("parses with imageIndex", () => {
    const box = parseBoundingBox('{"x":0,"y":0,"w":1,"h":1,"imageIndex":2}');
    expect(box?.imageIndex).toBe(2);
  });

  it("returns null for null input", () => {
    expect(parseBoundingBox(null)).toBeNull();
  });

  it("returns null for invalid JSON", () => {
    expect(parseBoundingBox("not json")).toBeNull();
  });

  it("returns null for missing fields", () => {
    expect(parseBoundingBox('{"x":0}')).toBeNull();
  });
});

describe("repairCategoryLabel", () => {
  it("translates categories", () => {
    expect(repairCategoryLabel("Replace")).toBe("Zamjena");
    expect(repairCategoryLabel("Repair")).toBe("Popravak");
  });
});

describe("laborTypeLabel", () => {
  it("translates labor types", () => {
    expect(laborTypeLabel("Body")).toBe("Limarija");
    expect(laborTypeLabel("Refinish")).toBe("Lakiranje");
  });
});

describe("custodyEventLabel", () => {
  it("translates events", () => {
    expect(custodyEventLabel("image_received")).toBe("Slika zaprimljena");
    expect(custodyEventLabel("evidence_sealed")).toBe("Dokazi zapečaćeni");
  });

  it("returns raw event for unknown", () => {
    expect(custodyEventLabel("custom_event")).toBe("custom_event");
  });
});
