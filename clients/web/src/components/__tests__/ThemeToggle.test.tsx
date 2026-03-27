import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { ThemeToggle } from "@/components/ThemeToggle";

beforeEach(() => {
  // Reset document class list
  document.documentElement.classList.remove("dark");
  // Clear localStorage
  localStorage.clear();
});

describe("ThemeToggle", () => {
  it("renders moon icon by default (light mode)", () => {
    render(<ThemeToggle />);

    const button = screen.getByRole("button");
    expect(button.getAttribute("title")).toBe("Tamna tema");
  });

  it("clicking toggles to dark (adds .dark class to documentElement)", () => {
    render(<ThemeToggle />);

    const button = screen.getByRole("button");
    fireEvent.click(button);

    expect(document.documentElement.classList.contains("dark")).toBe(true);
    expect(button.getAttribute("title")).toBe("Svijetla tema");
  });

  it("clicking again toggles back to light", () => {
    render(<ThemeToggle />);

    const button = screen.getByRole("button");

    // Toggle to dark
    fireEvent.click(button);
    expect(document.documentElement.classList.contains("dark")).toBe(true);

    // Toggle back to light
    fireEvent.click(button);
    expect(document.documentElement.classList.contains("dark")).toBe(false);
    expect(button.getAttribute("title")).toBe("Tamna tema");
  });

  it("saves preference to localStorage", () => {
    render(<ThemeToggle />);

    const button = screen.getByRole("button");

    // Toggle to dark
    fireEvent.click(button);
    expect(localStorage.getItem("dent_theme")).toBe("dark");

    // Toggle back to light
    fireEvent.click(button);
    expect(localStorage.getItem("dent_theme")).toBe("light");
  });

  it("reads saved dark preference from localStorage on mount", () => {
    localStorage.setItem("dent_theme", "dark");

    render(<ThemeToggle />);

    const button = screen.getByRole("button");
    expect(document.documentElement.classList.contains("dark")).toBe(true);
    expect(button.getAttribute("title")).toBe("Svijetla tema");
  });
});
