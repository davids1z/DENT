import { API_BASE, authFetch, setTokens } from "./client";
import type { AdminStats, AdminUser, AuthResponse, AuthUser } from "./types";

export async function loginApi(email: string, password: string): Promise<AuthResponse> {
  const res = await fetch(`${API_BASE}/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password }),
  });
  if (res.status === 429) {
    throw new Error("Previše pokušaja prijave. Pričekajte nekoliko minuta pa pokušajte ponovo.");
  }
  if (!res.ok) {
    const err = await res.json().catch(() => ({ error: "Prijava nije uspjela." }));
    throw new Error(err.error || `Login failed: ${res.status}`);
  }
  const data: AuthResponse = await res.json();
  setTokens(data.token, data.refreshToken);
  return data;
}

export async function registerApi(email: string, password: string, fullName: string): Promise<AuthResponse> {
  const res = await fetch(`${API_BASE}/auth/register`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password, fullName }),
  });
  if (res.status === 429) {
    throw new Error("Previše pokušaja registracije. Pričekajte nekoliko minuta pa pokušajte ponovo.");
  }
  if (!res.ok) {
    const err = await res.json().catch(() => ({ error: "Registracija nije uspjela." }));
    throw new Error(err.error || `Register failed: ${res.status}`);
  }
  const data: AuthResponse = await res.json();
  setTokens(data.token, data.refreshToken);
  return data;
}

export async function getMeApi(): Promise<AuthUser> {
  const res = await authFetch(`${API_BASE}/auth/me`);
  if (!res.ok) throw new Error("Not authenticated");
  return res.json();
}

export async function getAdminUsers(): Promise<AdminUser[]> {
  const res = await authFetch(`${API_BASE}/admin/users`);
  if (!res.ok) throw new Error(`Failed to fetch users: ${res.status}`);
  return res.json();
}

export async function deactivateUser(id: string): Promise<void> {
  const res = await authFetch(`${API_BASE}/admin/users/${id}`, { method: "DELETE" });
  if (!res.ok) throw new Error("Failed to deactivate user");
}

export async function activateUser(id: string): Promise<void> {
  const res = await authFetch(`${API_BASE}/admin/users/${id}/activate`, { method: "POST" });
  if (!res.ok) throw new Error("Failed to activate user");
}

export async function getAdminStats(): Promise<AdminStats> {
  const res = await authFetch(`${API_BASE}/admin/stats`);
  if (!res.ok) throw new Error(`Failed to fetch admin stats: ${res.status}`);
  return res.json();
}
