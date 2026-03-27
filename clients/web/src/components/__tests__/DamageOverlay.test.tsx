import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { DamageOverlay } from "@/components/DamageOverlay";
import type { DamageDetection } from "@/lib/api";

// Mock child components to isolate DamageOverlay logic
vi.mock("@/components/DocumentPreview", () => ({
  DocumentPreview: (props: Record<string, unknown>) => (
    <div data-testid="document-preview" data-image-url={props.imageUrl} data-file-name={props.fileName}>
      DocumentPreview
    </div>
  ),
}));

vi.mock("@/components/ImageOverlay", () => ({
  ImageOverlay: (props: Record<string, unknown>) => (
    <div data-testid="image-overlay" data-image-url={props.imageUrl}>
      ImageOverlay
    </div>
  ),
}));

const sampleDamages: DamageDetection[] = [
  {
    id: "1",
    damageType: "Dent",
    carPart: "Hood",
    severity: "Moderate",
    description: "Test damage",
    confidence: 0.9,
    repairMethod: null,
    estimatedCostMin: null,
    estimatedCostMax: null,
    laborHours: null,
    partsNeeded: null,
    boundingBox: null,
    damageCause: null,
    safetyRating: null,
    materialType: null,
    repairOperations: null,
    repairCategory: null,
    repairLineItems: [],
  },
];

describe("DamageOverlay", () => {
  it("renders DocumentPreview for PDF files", () => {
    render(
      <DamageOverlay
        imageUrl="http://example.com/file.pdf"
        damages={sampleDamages}
        fileName="report.pdf"
      />
    );

    expect(screen.getByTestId("document-preview")).toBeDefined();
    expect(screen.queryByTestId("image-overlay")).toBeNull();
  });

  it("renders DocumentPreview for DOCX files", () => {
    render(
      <DamageOverlay
        imageUrl="http://example.com/file.docx"
        damages={sampleDamages}
        fileName="report.docx"
      />
    );

    expect(screen.getByTestId("document-preview")).toBeDefined();
  });

  it("renders ImageOverlay for image files", () => {
    render(
      <DamageOverlay
        imageUrl="http://example.com/photo.jpg"
        damages={sampleDamages}
        fileName="photo.jpg"
      />
    );

    expect(screen.getByTestId("image-overlay")).toBeDefined();
    expect(screen.queryByTestId("document-preview")).toBeNull();
  });

  it("renders ImageOverlay for PNG files", () => {
    render(
      <DamageOverlay
        imageUrl="http://example.com/image.png"
        damages={sampleDamages}
        fileName="image.png"
      />
    );

    expect(screen.getByTestId("image-overlay")).toBeDefined();
  });

  it("passes correct props to DocumentPreview", () => {
    const pageUrls = ["page1.jpg", "page2.jpg"];

    render(
      <DamageOverlay
        imageUrl="http://example.com/file.pdf"
        damages={sampleDamages}
        fileName="report.pdf"
        pagePreviewUrls={pageUrls}
      />
    );

    const docPreview = screen.getByTestId("document-preview");
    expect(docPreview.getAttribute("data-image-url")).toBe(
      "http://example.com/file.pdf"
    );
    expect(docPreview.getAttribute("data-file-name")).toBe("report.pdf");
  });

  it("passes correct props to ImageOverlay", () => {
    render(
      <DamageOverlay
        imageUrl="http://example.com/photo.jpg"
        damages={sampleDamages}
        fileName="photo.jpg"
      />
    );

    const imgOverlay = screen.getByTestId("image-overlay");
    expect(imgOverlay.getAttribute("data-image-url")).toBe(
      "http://example.com/photo.jpg"
    );
  });

  it("uses URL extension when fileName is not provided", () => {
    render(
      <DamageOverlay
        imageUrl="http://example.com/document.xlsx"
        damages={sampleDamages}
      />
    );

    expect(screen.getByTestId("document-preview")).toBeDefined();
  });
});
