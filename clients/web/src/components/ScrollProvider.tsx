"use client";

import { useOverlayScrollbars } from "overlayscrollbars-react";
import { useEffect, useRef } from "react";
import "overlayscrollbars/overlayscrollbars.css";

export function ScrollProvider({ children }: { children: React.ReactNode }) {
  const ref = useRef<HTMLDivElement>(null);
  const [initialize] = useOverlayScrollbars({
    options: {
      scrollbars: {
        theme: "os-theme-custom",
        autoHide: "move",
        autoHideDelay: 800,
      },
      overflow: { x: "hidden" },
    },
  });

  useEffect(() => {
    if (ref.current) {
      initialize(document.body);
    }
  }, [initialize]);

  return <div ref={ref}>{children}</div>;
}
