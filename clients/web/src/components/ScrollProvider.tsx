"use client";

import { OverlayScrollbarsComponent } from "overlayscrollbars-react";
import { useEffect, useState } from "react";

function useIsMobile() {
  const [isMobile, setIsMobile] = useState(false);
  useEffect(() => {
    // All mobile devices have native overlay scrollbars — no need for OverlayScrollbars
    setIsMobile("ontouchstart" in window || navigator.maxTouchPoints > 0);
  }, []);
  return isMobile;
}

export function ScrollProvider({ children }: { children: React.ReactNode }) {
  const isMobile = useIsMobile();

  useEffect(() => {
    if (isMobile) return;
    const style = document.createElement("style");
    style.setAttribute("data-scrollbar-theme", "");
    style.textContent = `
      .os-scrollbar.os-theme-dent { --os-size: 8px; --os-padding-perpendicular: 2px; --os-padding-axis: 2px; }
      .os-theme-dent .os-scrollbar-handle { background: rgba(100,116,139,0.65) !important; border-radius: 8px !important; }
      .os-theme-dent .os-scrollbar-handle:hover { background: rgba(100,116,139,0.8) !important; }
      .dark .os-theme-dent .os-scrollbar-handle { background: rgba(148,163,184,0.55) !important; }
      .dark .os-theme-dent .os-scrollbar-handle:hover { background: rgba(148,163,184,0.75) !important; }
    `;
    document.body.appendChild(style);
    return () => { style.remove(); };
  }, [isMobile]);

  // Mobile: render children directly — no wrapper div that blocks browser chrome color detection
  if (isMobile) {
    return <>{children}</>;
  }

  return (
    <OverlayScrollbarsComponent
      element="div"
      options={{
        scrollbars: {
          theme: "os-theme-dent",
          autoHide: "scroll",
          autoHideDelay: 400,
        },
        overflow: { x: "hidden" },
      }}
      style={{ height: "100dvh", background: "var(--background)", transition: "background-color 0.2s ease" }}
    >
      {children}
    </OverlayScrollbarsComponent>
  );
}
