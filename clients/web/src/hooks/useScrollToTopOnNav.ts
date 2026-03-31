"use client";

import { useEffect, useRef } from "react";
import { usePathname } from "next/navigation";

/**
 * Scrolls to top on route change, EXCEPT on browser back/forward navigation.
 * Works with both native scroll and OverlayScrollbars.
 */
export function useScrollToTopOnNav() {
  const pathname = usePathname();
  const isPopState = useRef(false);

  // Track browser back/forward
  useEffect(() => {
    const onPopState = () => {
      isPopState.current = true;
    };
    window.addEventListener("popstate", onPopState);
    return () => window.removeEventListener("popstate", onPopState);
  }, []);

  // Scroll to top on pathname change (unless it was back/forward)
  useEffect(() => {
    if (isPopState.current) {
      // Back/forward — don't scroll, let browser restore position
      isPopState.current = false;
      return;
    }

    // Forward navigation — scroll to top
    const osViewport = document.querySelector<HTMLElement>("[data-overlayscrollbars-viewport]");
    if (osViewport) {
      osViewport.scrollTo({ top: 0 });
    }
    window.scrollTo({ top: 0 });
  }, [pathname]);
}
