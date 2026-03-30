"use client";

import { useEffect } from "react";
import { usePathname } from "next/navigation";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "/api";

function getSessionId(): string {
  if (typeof window === "undefined") return "";
  let sid = sessionStorage.getItem("dent_sid");
  if (!sid) {
    sid = crypto.randomUUID();
    sessionStorage.setItem("dent_sid", sid);
  }
  return sid;
}

export function usePageTrack() {
  const pathname = usePathname();

  useEffect(() => {
    const body = JSON.stringify({
      eventType: "PageView",
      path: pathname,
      sessionId: getSessionId(),
      referrer: document.referrer || null,
    });

    if (navigator.sendBeacon) {
      navigator.sendBeacon(
        `${API_BASE}/audit/track`,
        new Blob([body], { type: "application/json" })
      );
    } else {
      fetch(`${API_BASE}/audit/track`, {
        method: "POST",
        body,
        headers: { "Content-Type": "application/json" },
        keepalive: true,
        credentials: "same-origin",
      }).catch(() => {});
    }
  }, [pathname]);
}
