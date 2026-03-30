import { API_BASE, authFetch, clearAuthFlag } from "./client";
import type { AdminStats, AdminUser, AuthResponse, AuthUser } from "./types";

export async function loginApi(email: string, password: string): Promise<AuthResponse> {
  const res = await fetch(`${API_BASE}/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password }),
    credentials: "same-origin",
  });
  if (res.status === 429) {
    throw new Error("Previše pokušaja prijave. Pričekajte nekoliko minuta pa pokušajte ponovo.");
  }
  if (!res.ok) {
    const err = await res.json().catch(() => ({ error: "Prijava nije uspjela." }));
    throw new Error(err.error || `Login failed: ${res.status}`);
  }
  // Server sets httpOnly cookies (dent_auth, dent_refresh, dent_has_auth)
  return res.json();
}

export async function registerApi(email: string, password: string, fullName: string): Promise<AuthResponse> {
  const res = await fetch(`${API_BASE}/auth/register`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password, fullName }),
    credentials: "same-origin",
  });
  if (res.status === 429) {
    throw new Error("Previše pokušaja registracije. Pričekajte nekoliko minuta pa pokušajte ponovo.");
  }
  if (!res.ok) {
    const err = await res.json().catch(() => ({ error: "Registracija nije uspjela." }));
    throw new Error(err.error || `Register failed: ${res.status}`);
  }
  // Server sets httpOnly cookies
  return res.json();
}

export async function logoutApi(): Promise<void> {
  try {
    await fetch(`${API_BASE}/auth/logout`, {
      method: "POST",
      credentials: "same-origin",
    });
  } catch { /* ignore network errors during logout */ }
  clearAuthFlag();
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

export async function changeUserRole(id: string, role: "Admin" | "User"): Promise<void> {
  const res = await authFetch(`${API_BASE}/admin/users/${id}/role`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ role }),
  });
  if (!res.ok) throw new Error("Failed to change role");
}
