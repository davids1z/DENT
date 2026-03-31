"use client";

import { useState, useEffect, useCallback } from "react";

export function ThemeToggle() {
  const [dark, setDark] = useState(false);

  useEffect(() => {
    setDark(document.documentElement.classList.contains("dark"));
  }, []);

  const toggle = useCallback(() => {
    const next = !dark;
    setDark(next);
    if (next) {
      document.documentElement.classList.add("dark");
      localStorage.setItem("dent_theme", "dark");
    } else {
      document.documentElement.classList.remove("dark");
      localStorage.setItem("dent_theme", "light");
    }
    // Update Safari status bar color — must remove/recreate for Safari to pick it up
    const color = next ? "#0f172a" : "#ffffff";
    document.querySelectorAll('meta[name="theme-color"]').forEach((m) => m.remove());
    const fresh = document.createElement("meta");
    fresh.name = "theme-color";
    fresh.id = "theme-color-meta";
    fresh.content = color;
    document.head.appendChild(fresh);
  }, [dark]);

  return (
    <button
      onClick={toggle}
      className="w-8 h-8 rounded-lg flex items-center justify-center text-muted hover:text-foreground hover:bg-card transition-colors"
      title={dark ? "Svijetla tema" : "Tamna tema"}
    >
      {dark ? (
        <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M12 3v2.25m6.364.386l-1.591 1.591M21 12h-2.25m-.386 6.364l-1.591-1.591M12 18.75V21m-4.773-4.227l-1.591 1.591M5.25 12H3m4.227-4.773L5.636 5.636M15.75 12a3.75 3.75 0 11-7.5 0 3.75 3.75 0 017.5 0z" />
        </svg>
      ) : (
        <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M21.752 15.002A9.718 9.718 0 0118 15.75c-5.385 0-9.75-4.365-9.75-9.75 0-1.33.266-2.597.748-3.752A9.753 9.753 0 003 11.25C3 16.635 7.365 21 12.75 21a9.753 9.753 0 009.002-5.998z" />
        </svg>
      )}
    </button>
  );
}
