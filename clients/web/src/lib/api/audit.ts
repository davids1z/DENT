import { API_BASE, authFetch } from "./client";

export interface AuditEvent {
  id: number;
  timestamp: string;
  eventType: string;
  category: string;
  method: string | null;
  path: string | null;
  statusCode: number | null;
  durationMs: number | null;
  userId: string | null;
  sessionId: string | null;
  ipAddress: string | null;
  userAgent: string | null;
  metadataJson: string | null;
  resourceId: string | null;
  resourceType: string | null;
}

export interface AuditEventsResponse {
  total: number;
  page: number;
  pageSize: number;
  events: AuditEvent[];
}

export interface AuditStats {
  period: number;
  eventCounts: Record<string, number>;
  uniqueSessions: number;
  uniqueUsers: number;
  failedLogins: number;
  pageViews: number;
  apiCalls: number;
  logins: number;
  topPages: { path: string; count: number }[];
  dailyEvents: { date: string; count: number }[];
  hourlyEvents: { hour: number; count: number }[];
  recentFailedLogins: { timestamp: string; ipAddress: string | null; metadataJson: string | null }[];
}

export async function getAuditEvents(params: {
  eventType?: string;
  category?: string;
  userId?: string;
  from?: string;
  to?: string;
  path?: string;
  page?: number;
  pageSize?: number;
}): Promise<AuditEventsResponse> {
  const qs = new URLSearchParams();
  if (params.eventType) qs.set("eventType", params.eventType);
  if (params.category) qs.set("category", params.category);
  if (params.userId) qs.set("userId", params.userId);
  if (params.from) qs.set("from", params.from);
  if (params.to) qs.set("to", params.to);
  if (params.path) qs.set("path", params.path);
  if (params.page) qs.set("page", String(params.page));
  if (params.pageSize) qs.set("pageSize", String(params.pageSize));

  const res = await authFetch(`${API_BASE}/audit/events?${qs}`);
  if (!res.ok) throw new Error(`Failed to fetch audit events: ${res.status}`);
  return res.json();
}

export async function getAuditStats(days = 7): Promise<AuditStats> {
  const res = await authFetch(`${API_BASE}/audit/stats?days=${days}`);
  if (!res.ok) throw new Error(`Failed to fetch audit stats: ${res.status}`);
  return res.json();
}
