"use client";

import { OverlayScrollbarsComponent } from "overlayscrollbars-react";
import { useEffect, useState } from "react";

function useIsIOS() {
  const [isIOS, setIsIOS] = useState(false);
  useEffect(() => {
    setIsIOS(/iPad|iPhone|iPod/.test(navigator.userAgent) || (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1));
  }, []);
  return isIOS;
}

export function ScrollProvider({ children }: { children: React.ReactNode }) {
  const isIOS = useIsIOS();

  useEffect(() => {
    if (isIOS) return; // iOS has native overlay scrollbars
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
  }, [isIOS]);

  // iOS: render children directly — no wrapper div that blocks Safari chrome color detection
  if (isIOS) {
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
