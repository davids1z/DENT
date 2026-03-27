import type { AuthResponse } from "./types";

export const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8080/api";

export function getToken(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem("dent_token");
}

export function getRefreshToken(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem("dent_refresh_token");
}

export function setTokens(token: string, refreshToken: string) {
  localStorage.setItem("dent_token", token);
  localStorage.setItem("dent_refresh_token", refreshToken);
}

export function clearTokens() {
  localStorage.removeItem("dent_token");
  localStorage.removeItem("dent_refresh_token");
}

export function authHeaders(): Record<string, string> {
  const token = getToken();
  return token ? { Authorization: `Bearer ${token}` } : {};
}

export async function authFetch(url: string, init?: RequestInit): Promise<Response> {
  const headers = { ...authHeaders(), ...init?.headers };
  let res = await fetch(url, { ...init, headers });

  if (res.status === 401) {
    const refreshed = await tryRefreshToken();
    if (refreshed) {
      const retryHeaders = { ...authHeaders(), ...init?.headers };
      res = await fetch(url, { ...init, headers: retryHeaders });
    }
  }

  return res;
}

async function tryRefreshToken(): Promise<boolean> {
  const refreshToken = getRefreshToken();
  if (!refreshToken) return false;

  try {
    const res = await fetch(`${API_BASE}/auth/refresh`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ refreshToken }),
    });
    if (!res.ok) {
      clearTokens();
      return false;
    }
    const data: AuthResponse = await res.json();
    setTokens(data.token, data.refreshToken);
    return true;
  } catch {
    clearTokens();
    return false;
  }
}
