"use client";

import { useEffect, useState, useCallback, useRef } from "react";

export function ScrollHint() {
  const [mounted, setMounted] = useState(false);
  const [scrolled, setScrolled] = useState(false);
  const [centerX, setCenterX] = useState(0);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const timer = setTimeout(() => setMounted(true), 1200);
    return () => clearTimeout(timer);
  }, []);

  // Calculate true visual center (excluding scrollbar)
  useEffect(() => {
    const update = () => setCenterX(document.documentElement.clientWidth / 2);
    update();
    window.addEventListener("resize", update);
    return () => window.removeEventListener("resize", update);
  }, []);

  const handleScroll = useCallback(() => {
    const osViewport = document.querySelector<HTMLElement>("[data-overlayscrollbars-viewport]");
    const scrollTop = osViewport ? osViewport.scrollTop : window.scrollY;
    setScrolled(scrollTop > 5);
  }, []);

  useEffect(() => {
    const osViewport = document.querySelector<HTMLElement>("[data-overlayscrollbars-viewport]");
    window.addEventListener("scroll", handleScroll, { passive: true });
    if (osViewport) osViewport.addEventListener("scroll", handleScroll, { passive: true });
    return () => {
      window.removeEventListener("scroll", handleScroll);
      if (osViewport) osViewport.removeEventListener("scroll", handleScroll);
    };
  }, [handleScroll]);

  const show = mounted && !scrolled;
  const width = ref.current?.offsetWidth ?? 0;

  return (
    <div
      ref={ref}
      style={{
        position: "fixed",
        bottom: "7rem",
        left: centerX > 0 ? `${centerX - width / 2 + 3}px` : "calc(50% + 3px)",
        transform: centerX > 0
          ? (show ? "none" : "translateY(10px)")
          : (show ? "translateX(-50%)" : "translateX(-50%) translateY(10px)"),
        zIndex: 30,
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        gap: "0.4rem",
        opacity: show ? 0.5 : 0,
        transition: "opacity 0.15s ease-out, transform 0.15s ease-out",
        pointerEvents: "none",
        willChange: "opacity, transform",
      }}
    >
      <span style={{ fontSize: "9px", textTransform: "uppercase", letterSpacing: "0.3em", fontWeight: 500 }} className="text-muted">
        {"Saznaj vi\u0161e"}
      </span>
      <div className="flex flex-col items-center animate-scroll-arrows">
        <svg className="w-3.5 h-3.5 text-muted/50 -mb-1" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M19 9l-7 7-7-7" />
        </svg>
        <svg className="w-3.5 h-3.5 text-muted/25" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M19 9l-7 7-7-7" />
        </svg>
      </div>
    </div>
  );
}
