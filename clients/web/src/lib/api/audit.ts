import { API_BASE, authFetch } from "./client";

export interface AuditStats {
  period: number;
  // KPI strip
  totalVisits: number;
  uniqueVisitors: number;
  activeNow: number;
  loggedInVisits: number;
  anonVisits: number;
  todayVisits: number;
  // Charts
  visitsPerDay: { date: string; count: number }[];
  uniquePerDay: { date: string; count: number }[];
  visitsPerHour: { hour: number; count: number }[];
  authPerDay: { date: string; isAuth: boolean; count: number }[];
  // Engagement
  topPages: { path: string; count: number }[];
  heatmap: { day: number; hour: number; count: number }[];
  topReferrers: { source: string; count: number }[];
  // Recent visitors
  recentVisitors: {
    sessionId: string;
    userName: string | null;
    ip: string | null;
    lastPage: string | null;
    lastSeen: string;
    pageCount: number;
  }[];
}

export async function getAuditStats(days = 30): Promise<AuditStats> {
  const res = await authFetch(`${API_BASE}/audit/stats?days=${days}`);
  if (!res.ok) throw new Error(`Failed to fetch audit stats: ${res.status}`);
  return res.json();
}
