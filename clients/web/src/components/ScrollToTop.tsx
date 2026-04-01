"use client";

import { useEffect, useState, useCallback } from "react";

export function ScrollToTop() {
  const [visible, setVisible] = useState(false);

  const handleScroll = useCallback(() => {
    const osViewport = document.querySelector<HTMLElement>("[data-overlayscrollbars-viewport]");
    const scrollTop = osViewport ? osViewport.scrollTop : window.scrollY;
    setVisible(scrollTop > 400);
  }, []);

  useEffect(() => {
    const osViewport = document.querySelector<HTMLElement>("[data-overlayscrollbars-viewport]");

    window.addEventListener("scroll", handleScroll, { passive: true });
    if (osViewport) {
      osViewport.addEventListener("scroll", handleScroll, { passive: true });
    }

    return () => {
      window.removeEventListener("scroll", handleScroll);
      if (osViewport) {
        osViewport.removeEventListener("scroll", handleScroll);
      }
    };
  }, [handleScroll]);

  const scrollUp = () => {
    const osViewport = document.querySelector<HTMLElement>("[data-overlayscrollbars-viewport]");
    if (osViewport) {
      osViewport.scrollTo({ top: 0, behavior: "smooth" });
    } else {
      window.scrollTo({ top: 0, behavior: "smooth" });
    }
  };

  return (
    <button
      onClick={scrollUp}
      aria-label="Vrati se na vrh"
      style={{
        position: "fixed",
        bottom: "5rem",
        right: "1rem",
        zIndex: 50,
        width: "2.5rem",
        height: "2.5rem",
        borderRadius: "9999px",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        opacity: visible ? 1 : 0,
        transform: visible ? "translateY(0) scale(1)" : "translateY(12px) scale(0.85)",
        transition: "opacity 0.2s ease-out, transform 0.2s ease-out",
        pointerEvents: visible ? "auto" : "none",
      }}
      className="bg-accent text-white shadow-lg shadow-accent/25 hover:bg-accent-hover active:scale-95"
    >
      <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
        <path strokeLinecap="round" strokeLinejoin="round" d="M5 15l7-7 7 7" />
      </svg>
    </button>
  );
}
