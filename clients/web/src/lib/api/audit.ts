import { API_BASE, authFetch } from "./client";

export interface AuditStats {
  period: number;
  // KPI strip
  activeSessions: number;
  failedLogins24h: number;
  apiErrors24h: number;
  avgResponseMs: number;
  totalInspections: number;
  totalUsers: number;
  activeUsers: number;
  // Historical activity (from Inspections)
  inspectionsPerDay: { date: string; count: number }[];
  inspectionsPerHour: { hour: number; count: number }[];
  userActivity: { fullName: string; email: string; lastLoginAt: string | null; inspectionCount: number }[];
  // Security
  failedLoginsByDay: { date: string; count: number }[];
  suspiciousIps: { ip: string; count: number; last: string }[];
  recentFailedLogins: { timestamp: string; ipAddress: string | null; metadataJson: string | null }[];
  // Engagement
  topPages: { path: string; count: number }[];
  heatmap: { day: number; hour: number; count: number }[];
  // API Health
  slowEndpoints: { method: string; path: string; avg: number; count: number; errors: number }[];
  statusCodes: Record<string, number>;
}

export async function getAuditStats(days = 30): Promise<AuditStats> {
  const res = await authFetch(`${API_BASE}/audit/stats?days=${days}`);
  if (!res.ok) throw new Error(`Failed to fetch audit stats: ${res.status}`);
  return res.json();
}
