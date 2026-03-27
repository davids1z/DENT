import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { ErrorBoundary } from "@/components/ErrorBoundary";

// Suppress console.error from ErrorBoundary's componentDidCatch
beforeEach(() => {
  vi.spyOn(console, "error").mockImplementation(() => {});
});

function ThrowingChild({ shouldThrow }: { shouldThrow: boolean }) {
  if (shouldThrow) {
    throw new Error("Test error");
  }
  return <div>Child content</div>;
}

describe("ErrorBoundary", () => {
  it("renders children normally when no error", () => {
    render(
      <ErrorBoundary>
        <div>Hello world</div>
      </ErrorBoundary>
    );

    expect(screen.getByText("Hello world")).toBeDefined();
  });

  it("catches render error and shows fallback UI", () => {
    render(
      <ErrorBoundary>
        <ThrowingChild shouldThrow={true} />
      </ErrorBoundary>
    );

    expect(screen.getByText("Nesto je poslo krivo")).toBeDefined();
    expect(
      screen.getByText(
        "Doslo je do neocekivane greske. Pokusajte osvjeziti stranicu."
      )
    ).toBeDefined();
    expect(screen.getByText("Pokusajte ponovo")).toBeDefined();
  });

  it('"Pokusajte ponovo" button resets error state', () => {
    // We need a component that can toggle between throwing and not.
    // After reset, React re-renders children. We use a ref-based approach:
    // first render throws, then after reset we need it to not throw.
    let shouldThrow = true;

    function ConditionalThrow() {
      if (shouldThrow) {
        throw new Error("Test error");
      }
      return <div>Recovered content</div>;
    }

    render(
      <ErrorBoundary>
        <ConditionalThrow />
      </ErrorBoundary>
    );

    // Should show fallback
    expect(screen.getByText("Pokusajte ponovo")).toBeDefined();

    // Fix the error condition before clicking retry
    shouldThrow = false;

    fireEvent.click(screen.getByText("Pokusajte ponovo"));

    // After reset, children re-render without error
    expect(screen.getByText("Recovered content")).toBeDefined();
  });
});
