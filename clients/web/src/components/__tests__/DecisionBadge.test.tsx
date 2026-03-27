import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { DecisionBadge } from "@/components/DecisionBadge";

describe("DecisionBadge", () => {
  it('renders correct label for AutoApprove outcome', () => {
    render(<DecisionBadge outcome="AutoApprove" />);
    expect(screen.getByText("Autenticno")).toBeDefined();
  });

  it('renders correct label for HumanReview outcome', () => {
    render(<DecisionBadge outcome="HumanReview" />);
    expect(screen.getByText("Potreban pregled")).toBeDefined();
  });

  it('renders correct label for Escalate outcome', () => {
    render(<DecisionBadge outcome="Escalate" />);
    expect(screen.getByText("Sumnja na krivotvorinu")).toBeDefined();
  });

  it("applies correct color classes for AutoApprove", () => {
    const { container } = render(<DecisionBadge outcome="AutoApprove" />);
    const badge = container.firstElementChild as HTMLElement;

    expect(badge.className).toContain("bg-green-500/10");
    expect(badge.className).toContain("border-green-500/20");
    expect(badge.className).toContain("text-green-600");
  });

  it("applies correct color classes for HumanReview", () => {
    const { container } = render(<DecisionBadge outcome="HumanReview" />);
    const badge = container.firstElementChild as HTMLElement;

    expect(badge.className).toContain("bg-amber-500/10");
    expect(badge.className).toContain("border-amber-500/20");
    expect(badge.className).toContain("text-amber-600");
  });

  it("applies correct color classes for Escalate", () => {
    const { container } = render(<DecisionBadge outcome="Escalate" />);
    const badge = container.firstElementChild as HTMLElement;

    expect(badge.className).toContain("bg-red-500/10");
    expect(badge.className).toContain("border-red-500/20");
    expect(badge.className).toContain("text-red-600");
  });

  it("renders reason when provided", () => {
    render(<DecisionBadge outcome="Escalate" reason="Detected manipulation" />);
    expect(screen.getByText("Detected manipulation")).toBeDefined();
  });

  it("does not render reason paragraph when reason is null", () => {
    const { container } = render(
      <DecisionBadge outcome="AutoApprove" reason={null} />
    );
    const paragraphs = container.querySelectorAll("p");
    expect(paragraphs.length).toBe(0);
  });
});
