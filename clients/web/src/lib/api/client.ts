export const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8080/api";

/**
 * Check if the user has an auth cookie (non-httpOnly flag set by server).
 * Used only for UI hints (FOUC prevention). The actual JWT is in an httpOnly cookie.
 */
export function hasAuthCookie(): boolean {
  if (typeof document === "undefined") return false;
  return document.cookie.includes("dent_has_auth=1");
}

/** Clear the JS-readable auth flag cookie (httpOnly cookies cleared by server). */
export function clearAuthFlag() {
  if (typeof document === "undefined") return;
  document.cookie = "dent_has_auth=; path=/; expires=Thu, 01 Jan 1970 00:00:00 GMT";
}

/**
 * Fetch with automatic cookie auth and 401 refresh retry.
 * Cookies are sent automatically for same-origin requests (via nginx/Next.js proxy).
 */
export async function authFetch(url: string, init?: RequestInit): Promise<Response> {
  let res = await fetch(url, { ...init, credentials: "same-origin" });

  if (res.status === 401) {
    const refreshed = await tryRefreshToken();
    if (refreshed) {
      res = await fetch(url, { ...init, credentials: "same-origin" });
    }
  }

  return res;
}

async function tryRefreshToken(): Promise<boolean> {
  try {
    const res = await fetch(`${API_BASE}/auth/refresh`, {
      method: "POST",
      credentials: "same-origin",
    });
    if (!res.ok) {
      clearAuthFlag();
      return false;
    }
    // Server set new httpOnly cookies automatically
    return true;
  } catch {
    clearAuthFlag();
    return false;
  }
}

// ── Legacy exports for backward compatibility ──
// These are no-ops now that auth uses httpOnly cookies.
/** @deprecated Auth tokens are now in httpOnly cookies. */
export function getToken(): string | null { return null; }
/** @deprecated Auth tokens are now in httpOnly cookies. */
export function getRefreshToken(): string | null { return null; }
/** @deprecated Auth tokens are now in httpOnly cookies. */
export function setTokens(_token: string, _refreshToken: string) { /* no-op */ }
/** @deprecated Auth tokens are now in httpOnly cookies — use clearAuthFlag() instead. */
export function clearTokens() { clearAuthFlag(); }
/** @deprecated Auth is via httpOnly cookies — no manual headers needed. */
export function authHeaders(): Record<string, string> { return {}; }
