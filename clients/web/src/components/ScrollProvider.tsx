"use client";

import { OverlayScrollbarsComponent } from "overlayscrollbars-react";
import { useEffect } from "react";

export function ScrollProvider({ children }: { children: React.ReactNode }) {
  useEffect(() => {
    // Inject styles at end of body to guarantee they come after all other stylesheets
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
  }, []);

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
      style={{ height: "100dvh" }}
    >
      {children}
    </OverlayScrollbarsComponent>
  );
}
