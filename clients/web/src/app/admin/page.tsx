"use client";

import { useEffect, useState, useCallback } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { motion } from "framer-motion";
import {
  AreaChart, Area, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid,
  PieChart, Pie, Cell,
} from "recharts";
import { useAuth } from "@/lib/auth";
import { cn } from "@/lib/cn";
import {
  getAdminUsers, getAdminStats, deactivateUser, activateUser, changeUserRole,
  getInspections, formatDate,
  type AdminUser, type AdminStats, type Inspection,
} from "@/lib/api";

/* ------------------------------------------------------------------ */
/*  Hooks                                                              */
/* ------------------------------------------------------------------ */
function useCountUp(target: number, on: boolean, dur = 900) {
  const [v, setV] = useState(0);
  useEffect(() => {
    if (!on) { setV(0); return; }
    const t0 = performance.now();
    let id: number;
    const tick = (now: number) => {
      const p = Math.min((now - t0) / dur, 1);
      setV((1 - (1 - p) ** 3) * target);
      if (p < 1) id = requestAnimationFrame(tick);
    };
    id = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(id);
  }, [target, on, dur]);
  return v;
}

/* ------------------------------------------------------------------ */
/*  Nav config                                                         */
/* ------------------------------------------------------------------ */
const navItems = [
  { id: "pregled", label: "Pregled",
    icon: "M3.75 6A2.25 2.25 0 016 3.75h2.25A2.25 2.25 0 0110.5 6v2.25a2.25 2.25 0 01-2.25 2.25H6a2.25 2.25 0 01-2.25-2.25V6zM3.75 15.75A2.25 2.25 0 016 13.5h2.25a2.25 2.25 0 012.25 2.25V18a2.25 2.25 0 01-2.25 2.25H6A2.25 2.25 0 013.75 18v-2.25zM13.5 6a2.25 2.25 0 012.25-2.25H18A2.25 2.25 0 0120.25 6v2.25A2.25 2.25 0 0118 10.5h-2.25a2.25 2.25 0 01-2.25-2.25V6zM13.5 15.75a2.25 2.25 0 012.25-2.25H18a2.25 2.25 0 012.25 2.25V18A2.25 2.25 0 0118 20.25h-2.25A2.25 2.25 0 0113.5 18v-2.25z" },
  { id: "korisnici", label: "Korisnici",
    icon: "M15 19.128a9.38 9.38 0 002.625.372 9.337 9.337 0 004.121-.952 4.125 4.125 0 00-7.533-2.493M15 19.128v-.003c0-1.113-.285-2.16-.786-3.07M15 19.128v.106A12.318 12.318 0 018.624 21c-2.331 0-4.512-.645-6.374-1.766l-.001-.109a6.375 6.375 0 0111.964-1.997M12 6.375a3.375 3.375 0 11-6.75 0 3.375 3.375 0 016.75 0zm8.25 2.25a2.625 2.625 0 11-5.25 0 2.625 2.625 0 015.25 0z" },
  { id: "analize", label: "Analize",
    icon: "M19.5 14.25v-2.625a3.375 3.375 0 00-3.375-3.375h-1.5A1.125 1.125 0 0113.5 7.125v-1.5a3.375 3.375 0 00-3.375-3.375H8.25m0 12.75h7.5m-7.5 3H12M10.5 2.25H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 00-9-9z" },
  { id: "statistika", label: "Statistika",
    icon: "M3 13.125C3 12.504 3.504 12 4.125 12h2.25c.621 0 1.125.504 1.125 1.125v6.75C7.5 20.496 6.996 21 6.375 21h-2.25A1.125 1.125 0 013 19.875v-6.75zM9.75 8.625c0-.621.504-1.125 1.125-1.125h2.25c.621 0 1.125.504 1.125 1.125v11.25c0 .621-.504 1.125-1.125 1.125h-2.25a1.125 1.125 0 01-1.125-1.125V8.625zM16.5 4.125c0-.621.504-1.125 1.125-1.125h2.25C20.496 3 21 3.504 21 4.125v15.75c0 .621-.504 1.125-1.125 1.125h-2.25a1.125 1.125 0 01-1.125-1.125V4.125z" },
] as const;

const viewMeta: Record<string, { title: string; desc: string }> = {
  pregled: { title: "Pregled", desc: "Aktivnost i performanse sustava" },
  korisnici: { title: "Korisnici", desc: "Upravljanje korisnickim racunima" },
  analize: { title: "Analize", desc: "Sve analize u sustavu" },
  statistika: { title: "Statistika", desc: "Detaljni statisticki podaci" },
};

type View = (typeof navItems)[number]["id"] | "user";

/* ------------------------------------------------------------------ */
/*  Page                                                               */
/* ------------------------------------------------------------------ */
export default function AdminPage() {
  const { user, isLoading: authLoading } = useAuth();
  const router = useRouter();
  const [view, setView] = useState<View>("pregled");
  const [stats, setStats] = useState<AdminStats | null>(null);
  const [statsLoading, setStatsLoading] = useState(true);
  const [selUser, setSelUser] = useState<AdminUser | null>(null);

  useEffect(() => {
    if (authLoading) return;
    if (!user || user.role !== "Admin") { router.replace("/"); return; }
    loadStats();
  }, [user, authLoading, router]);

  async function loadStats() {
    try { setStatsLoading(true); setStats(await getAdminStats()); } catch {} finally { setStatsLoading(false); }
  }

  function openUser(u: AdminUser) { setSelUser(u); setView("user"); }
  function closeUser() { setView("korisnici"); setSelUser(null); }

  if (authLoading || !user || user.role !== "Admin") {
    return <div className="min-h-[60dvh] flex items-center justify-center"><div className="w-7 h-7 border-2 border-accent border-t-transparent rounded-full animate-spin" /></div>;
  }

  const activeNavId = view === "user" ? "korisnici" : view;

  return (
    <div className="flex min-h-[calc(100dvh-4rem)]">
      {/* ── Sidebar (desktop) ── */}
      <aside className="hidden lg:flex w-[240px] shrink-0 flex-col border-r border-border/40">
        <div className="sticky top-16">
          <div className="px-5 pt-8 pb-6">
            <h1 className="font-heading text-xl font-extrabold tracking-tight">Admin</h1>
            <p className="text-xs text-muted mt-0.5">Upravljacka ploca</p>
          </div>
          <nav className="px-3 space-y-0.5">
            {navItems.map((item) => {
              const active = activeNavId === item.id;
              return (
                <button key={item.id} onClick={() => { setView(item.id as View); setSelUser(null); }}
                  className={cn(
                    "w-full flex items-center gap-3 px-3 py-2.5 rounded-xl text-[13px] font-medium transition-all",
                    active ? "bg-accent/10 text-accent" : "text-muted hover:text-foreground hover:bg-card-hover"
                  )}>
                  <svg className={cn("w-[18px] h-[18px] shrink-0", active ? "text-accent" : "text-muted")} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
                    <path strokeLinecap="round" strokeLinejoin="round" d={item.icon} />
                  </svg>
                  {item.label}
                  {active && <motion.div className="ml-auto w-1.5 h-1.5 rounded-full bg-accent" layoutId="sidebar-dot" transition={{ type: "spring", stiffness: 500, damping: 35 }} />}
                </button>
              );
            })}
          </nav>
        </div>
      </aside>

      {/* ── Main content ── */}
      <main className="flex-1 min-w-0 overflow-x-hidden">
        {/* Mobile nav */}
        <div className="lg:hidden flex items-center gap-1.5 px-4 pt-5 pb-2 overflow-x-auto">
          {navItems.map((item) => {
            const active = activeNavId === item.id;
            return (
              <button key={item.id} onClick={() => { setView(item.id as View); setSelUser(null); }}
                className={cn(
                  "flex items-center gap-2 px-3.5 py-2 rounded-xl text-xs font-semibold whitespace-nowrap transition-all",
                  active ? "bg-accent text-white shadow-sm" : "text-muted hover:text-foreground hover:bg-card"
                )}>
                <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
                  <path strokeLinecap="round" strokeLinejoin="round" d={item.icon} />
                </svg>
                {item.label}
              </button>
            );
          })}
        </div>

        <div className="p-4 sm:p-6 lg:p-8 max-w-6xl">
          {/* Page header */}
          {view !== "user" && (
            <motion.div key={`hdr-${view}`} initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="mb-8">
              <h2 className="font-heading text-2xl font-bold tracking-tight">{viewMeta[view]?.title}</h2>
              <p className="text-sm text-muted mt-1">{viewMeta[view]?.desc}</p>
            </motion.div>
          )}
          {view === "user" && selUser && (
            <button onClick={closeUser} className="flex items-center gap-2 text-sm text-accent hover:underline mb-6 group">
              <svg className="w-4 h-4 transition-transform group-hover:-translate-x-0.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M15.75 19.5L8.25 12l7.5-7.5" />
              </svg>
              Natrag na korisnike
            </button>
          )}

          {/* Content */}
          <div key={view} className="fade-up">
            {view === "pregled" && <OverviewTab stats={stats} loading={statsLoading} />}
            {view === "korisnici" && <UsersTab onSelect={openUser} />}
            {view === "analize" && <AnalysesTab />}
            {view === "statistika" && <StatisticsTab stats={stats} loading={statsLoading} />}
            {view === "user" && selUser && <UserDetail user={selUser} onBack={closeUser} />}
          </div>
        </div>
      </main>
    </div>
  );
}

/* ================================================================== */
/*  OVERVIEW                                                           */
/* ================================================================== */
function OverviewTab({ stats, loading }: { stats: AdminStats | null; loading: boolean }) {
  if (loading || !stats) return <Spin />;
  const avgSec = (stats.averageProcessingTimeMs / 1000).toFixed(1);

  return (
    <div className="space-y-6">
      {/* KPI cards */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <KpiCard i={0} label="Korisnici" value={stats.totalUsers} sub={`${stats.activeUsers} aktivnih`} color="#3b82f6"
          icon="M15 19.128a9.38 9.38 0 002.625.372 9.337 9.337 0 004.121-.952 4.125 4.125 0 00-7.533-2.493M15 19.128v-.003c0-1.113-.285-2.16-.786-3.07M15 19.128v.106A12.318 12.318 0 018.624 21c-2.331 0-4.512-.645-6.374-1.766l-.001-.109a6.375 6.375 0 0111.964-1.997M12 6.375a3.375 3.375 0 11-6.75 0 3.375 3.375 0 016.75 0zm8.25 2.25a2.625 2.625 0 11-5.25 0 2.625 2.625 0 015.25 0z" />
        <KpiCard i={1} label="Ukupno analiza" value={stats.totalInspections} color="#8b5cf6"
          icon="M19.5 14.25v-2.625a3.375 3.375 0 00-3.375-3.375h-1.5A1.125 1.125 0 0113.5 7.125v-1.5a3.375 3.375 0 00-3.375-3.375H8.25m0 12.75h7.5m-7.5 3H12M10.5 2.25H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 00-9-9z" />
        <KpiCard i={2} label="Dovrseno" value={stats.completedInspections} color="#10b981"
          icon="M9 12.75L11.25 15 15 9.75M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
        <KpiCard i={3} label="Neuspjelo" value={stats.failedInspections} color="#ef4444"
          icon="M12 9v3.75m9-.75a9 9 0 11-18 0 9 9 0 0118 0zm-9 3.75h.008v.008H12v-.008z" />
      </div>

      {/* Quick stats */}
      <div className="grid grid-cols-2 sm:grid-cols-5 gap-3">
        <QuickStat label="Novi danas" value={stats.usersRegisteredToday} />
        <QuickStat label="Novi tjedan" value={stats.usersRegisteredThisWeek} />
        <QuickStat label="Obrada" value={`${avgSec}s`} />
        <QuickStat label="U analizi" value={stats.analyzingInspections} live={stats.analyzingInspections > 0} />
        <QuickStat label="Red cekanja" value={stats.queuePending} live={stats.queuePending > 0} />
      </div>

      {/* Activity chart */}
      {stats.analysesPerDay.length > 0 && (
        <Card title="Aktivnost — zadnjih 30 dana" delay={0.15}>
          <div className="h-[220px] -mx-2">
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={stats.analysesPerDay} margin={{ top: 8, right: 16, bottom: 0, left: -12 }}>
                <defs>
                  <linearGradient id="aGrad" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="var(--color-accent)" stopOpacity={0.25} />
                    <stop offset="95%" stopColor="var(--color-accent)" stopOpacity={0.02} />
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" stroke="var(--color-border)" strokeOpacity={0.3} vertical={false} />
                <XAxis dataKey="date" tickFormatter={(v: string) => v.slice(5).replace("-", "/")} tick={{ fill: "var(--color-muted)", fontSize: 10 }} axisLine={false} tickLine={false} interval={6} />
                <YAxis tick={{ fill: "var(--color-muted)", fontSize: 10 }} axisLine={false} tickLine={false} allowDecimals={false} width={28} domain={[0, "auto"]} />
                <Tooltip content={<ChartTip />} cursor={{ stroke: "var(--color-accent)", strokeOpacity: 0.15 }} />
                <Area type="monotone" dataKey="count" stroke="var(--color-accent)" strokeWidth={2.5} fill="url(#aGrad)" dot={false} activeDot={{ r: 5, strokeWidth: 2, stroke: "var(--color-card)", fill: "var(--color-accent)" }} />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        </Card>
      )}

      {/* Recent failures */}
      {stats.recentFailures.length > 0 && (
        <Card title="Nedavni neuspjesi" delay={0.2}>
          <div className="space-y-1">
            {stats.recentFailures.slice(0, 5).map((f) => (
              <Link key={f.id} href={`/inspections/${f.id}`}
                className="flex items-center gap-3 p-3 -mx-2 hover:bg-red-500/[0.04] rounded-xl transition-colors group">
                <div className="w-9 h-9 rounded-lg bg-red-500/10 flex items-center justify-center shrink-0">
                  <svg className="w-4 h-4 text-red-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v3.75m-9.303 3.376c-.866 1.5.217 3.374 1.948 3.374h14.71c1.73 0 2.813-1.874 1.948-3.374L13.949 3.378c-.866-1.5-3.032-1.5-3.898 0L2.697 16.126zM12 15.75h.007v.008H12v-.008z" />
                  </svg>
                </div>
                <div className="flex-1 min-w-0">
                  <div className="text-sm font-medium truncate">{f.originalFileName}</div>
                  <div className="text-xs text-muted truncate">{f.userFullName || "Nepoznat"}</div>
                </div>
                <span className="text-xs text-muted shrink-0">{shortDate(f.createdAt)}</span>
                <svg className="w-4 h-4 text-muted opacity-0 group-hover:opacity-100 transition-opacity shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M8.25 4.5l7.5 7.5-7.5 7.5" />
                </svg>
              </Link>
            ))}
          </div>
        </Card>
      )}
    </div>
  );
}

/* ================================================================== */
/*  USERS TABLE                                                        */
/* ================================================================== */
function UsersTab({ onSelect }: { onSelect: (u: AdminUser) => void }) {
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");

  useEffect(() => { load(); }, []);
  async function load() { try { setUsers(await getAdminUsers()); } catch {} finally { setLoading(false); } }

  const filtered = users.filter((u) => !search || u.fullName.toLowerCase().includes(search.toLowerCase()) || u.email.toLowerCase().includes(search.toLowerCase()));
  if (loading) return <Spin />;

  return (
    <div>
      <div className="relative max-w-sm mb-5">
        <svg className="absolute left-3.5 top-1/2 -translate-y-1/2 w-4 h-4 text-muted pointer-events-none" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M21 21l-5.197-5.197m0 0A7.5 7.5 0 105.196 5.196a7.5 7.5 0 0010.607 10.607z" />
        </svg>
        <input type="text" placeholder="Pretrazi korisnike..." value={search} onChange={(e) => setSearch(e.target.value)}
          className="w-full pl-10 pr-4 py-2.5 rounded-xl border border-border/60 bg-card/50 text-sm placeholder:text-muted focus:outline-none focus:ring-2 focus:ring-accent/20 focus:border-accent/30" />
      </div>

      <div className="bg-card border border-border/50 rounded-2xl shadow-sm overflow-hidden">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-border/50">
              <th className="text-left px-5 py-3.5 text-[11px] text-muted uppercase tracking-wider font-medium">Korisnik</th>
              <th className="text-left px-5 py-3.5 text-[11px] text-muted uppercase tracking-wider font-medium hidden sm:table-cell">Uloga</th>
              <th className="text-left px-5 py-3.5 text-[11px] text-muted uppercase tracking-wider font-medium hidden md:table-cell">Registriran</th>
              <th className="text-left px-5 py-3.5 text-[11px] text-muted uppercase tracking-wider font-medium hidden lg:table-cell">Zadnja prijava</th>
              <th className="text-center px-5 py-3.5 text-[11px] text-muted uppercase tracking-wider font-medium">Analiza</th>
              <th className="text-center px-5 py-3.5 text-[11px] text-muted uppercase tracking-wider font-medium">Status</th>
              <th className="w-10" />
            </tr>
          </thead>
          <tbody className="divide-y divide-border/30">
            {filtered.map((u) => (
              <tr key={u.id} onClick={() => onSelect(u)} className="hover:bg-accent/[0.03] transition-colors cursor-pointer">
                <td className="px-5 py-4">
                  <div className="flex items-center gap-3">
                    <div className={cn("w-9 h-9 rounded-xl flex items-center justify-center text-xs font-bold shrink-0",
                      u.role === "Admin" ? "bg-purple-500/10 text-purple-400" : "bg-accent/10 text-accent")}>
                      {u.fullName.charAt(0).toUpperCase()}
                    </div>
                    <div className="min-w-0">
                      <div className="font-medium truncate">{u.fullName}</div>
                      <div className="text-xs text-muted truncate">{u.email}</div>
                    </div>
                  </div>
                </td>
                <td className="px-5 py-4 hidden sm:table-cell"><Pill c={u.role === "Admin" ? "purple" : "gray"}>{u.role}</Pill></td>
                <td className="px-5 py-4 text-muted text-xs hidden md:table-cell">{shortDate(u.createdAt)}</td>
                <td className="px-5 py-4 text-muted text-xs hidden lg:table-cell">{u.lastLoginAt ? shortDate(u.lastLoginAt) : "—"}</td>
                <td className="px-5 py-4 text-center font-stat font-bold">{u.inspectionCount}</td>
                <td className="px-5 py-4 text-center"><Pill c={u.isActive ? "green" : "red"}>{u.isActive ? "Aktivan" : "Neaktivan"}</Pill></td>
                <td className="px-5 py-4 text-right">
                  <svg className="w-4 h-4 text-muted/50 inline" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}><path strokeLinecap="round" strokeLinejoin="round" d="M8.25 4.5l7.5 7.5-7.5 7.5" /></svg>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {filtered.length === 0 && <div className="py-16 text-center text-sm text-muted">Nema rezultata</div>}
      </div>
    </div>
  );
}

/* ================================================================== */
/*  USER DETAIL                                                        */
/* ================================================================== */
function UserDetail({ user: u, onBack }: { user: AdminUser; onBack: () => void }) {
  const [inspections, setInspections] = useState<Inspection[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [localUser, setLocalUser] = useState(u);

  useEffect(() => {
    getInspections(1, 50).then((data) => setInspections(data.filter((i) => i.ownerEmail === u.email))).catch(() => {}).finally(() => setLoading(false));
  }, [u.email]);

  async function toggle() {
    setBusy(true);
    try {
      localUser.isActive ? await deactivateUser(u.id) : await activateUser(u.id);
      setLocalUser({ ...localUser, isActive: !localUser.isActive });
    } catch {} finally { setBusy(false); }
  }

  async function switchRole(role: "Admin" | "User") {
    if (role === localUser.role) return;
    setBusy(true);
    try {
      await changeUserRole(u.id, role);
      setLocalUser({ ...localUser, role });
    } catch {} finally { setBusy(false); }
  }

  const completed = inspections.filter((i) => i.status === "Completed").length;
  const failed = inspections.filter((i) => i.status === "Failed").length;

  return (
    <div className="space-y-6">
      {/* Profile header */}
      <div className="bg-card border border-border/50 rounded-2xl shadow-sm p-6 relative overflow-hidden">
        <div className="absolute -top-16 -right-16 w-40 h-40 rounded-full blur-3xl opacity-[0.07]"
          style={{ backgroundColor: localUser.role === "Admin" ? "#8b5cf6" : "#3b82f6" }} />
        <div className="flex items-start gap-4 flex-wrap relative">
          <div className={cn("w-16 h-16 rounded-2xl flex items-center justify-center text-xl font-bold shrink-0",
            localUser.role === "Admin" ? "bg-purple-500/10 text-purple-400" : "bg-accent/10 text-accent")}>
            {u.fullName.charAt(0).toUpperCase()}
          </div>
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2.5 flex-wrap">
              <h2 className="font-heading text-xl font-bold">{u.fullName}</h2>
              <Pill c={localUser.role === "Admin" ? "purple" : "gray"}>{localUser.role}</Pill>
              <Pill c={localUser.isActive ? "green" : "red"}>{localUser.isActive ? "Aktivan" : "Neaktivan"}</Pill>
            </div>
            <div className="text-muted text-sm mt-1">{u.email}</div>
          </div>
        </div>
      </div>

      {/* Stats grid */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        <MiniInfo label="Registriran" value={shortDate(u.createdAt)} />
        <MiniInfo label="Zadnja prijava" value={u.lastLoginAt ? formatDate(u.lastLoginAt) : "Nikad"} />
        <MiniInfo label="Ukupno analiza" value={String(u.inspectionCount)} bold />
        <MiniInfo label="Dovrseno / Neuspjelo" value={`${completed} / ${failed}`} bold />
      </div>

      {/* Management */}
      <Card title="Upravljanje">
        <div className="flex flex-wrap items-center gap-4">
          <div className="flex items-center gap-2.5">
            <span className="text-xs text-muted font-medium">Uloga:</span>
            <div className="flex bg-background border border-border/50 rounded-xl p-1">
              <button onClick={() => switchRole("User")} disabled={busy}
                className={cn("px-4 py-1.5 rounded-lg text-xs font-semibold transition-all",
                  localUser.role === "User" ? "bg-accent text-white shadow-sm" : "text-muted hover:text-foreground")}>
                User
              </button>
              <button onClick={() => switchRole("Admin")} disabled={busy}
                className={cn("px-4 py-1.5 rounded-lg text-xs font-semibold transition-all",
                  localUser.role === "Admin" ? "bg-purple-500 text-white shadow-sm" : "text-muted hover:text-foreground")}>
                Admin
              </button>
            </div>
          </div>

          <div className="w-px h-7 bg-border/40 hidden sm:block" />

          <button onClick={toggle} disabled={busy}
            className={cn("px-4 py-2 rounded-xl text-xs font-semibold transition-all disabled:opacity-50",
              localUser.isActive
                ? "bg-red-500/10 text-red-400 hover:bg-red-500/15 ring-1 ring-inset ring-red-500/20"
                : "bg-emerald-500/10 text-emerald-400 hover:bg-emerald-500/15 ring-1 ring-inset ring-emerald-500/20")}>
            {localUser.isActive ? "Deaktiviraj" : "Aktiviraj"}
          </button>
        </div>
      </Card>

      {/* User inspections */}
      <Card title={`Analize (${inspections.length})`}>
        {loading ? <Spin /> : inspections.length === 0 ? (
          <p className="text-sm text-muted py-6 text-center">Nema analiza</p>
        ) : (
          <div className="space-y-0.5">
            {inspections.map((ins) => (
              <Link key={ins.id} href={`/inspections/${ins.id}`}
                className="flex items-center gap-3 py-3 px-3 -mx-2 hover:bg-accent/[0.03] rounded-xl transition-colors group">
                <StatusDot s={ins.status} />
                <span className="text-sm truncate flex-1">{ins.originalFileName}</span>
                {ins.forensicResult && <RiskLabel level={ins.forensicResult.overallRiskLevel} />}
                <span className="text-xs text-muted shrink-0">{shortDate(ins.createdAt)}</span>
                <svg className="w-3.5 h-3.5 text-muted/50 shrink-0 opacity-0 group-hover:opacity-100 transition-opacity" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M8.25 4.5l7.5 7.5-7.5 7.5" />
                </svg>
              </Link>
            ))}
          </div>
        )}
      </Card>
    </div>
  );
}

/* ================================================================== */
/*  ANALYSES                                                           */
/* ================================================================== */
const sFilters = [{ v: "", l: "Sve" }, { v: "Completed", l: "Zavrseno" }, { v: "Analyzing", l: "U analizi" }, { v: "Pending", l: "Cekanje" }, { v: "Failed", l: "Neuspjelo" }] as const;

function AnalysesTab() {
  const [ins, setIns] = useState<Inspection[]>([]);
  const [loading, setLoading] = useState(true);
  const [status, setStatus] = useState("");
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(1);
  const ps = 20;

  const load = useCallback(async () => { try { setLoading(true); setIns(await getInspections(page, ps, status || undefined)); } catch {} finally { setLoading(false); } }, [page, status]);
  useEffect(() => { load(); }, [load]);
  useEffect(() => { setPage(1); }, [status]);

  const filtered = ins.filter((i) => !search || i.originalFileName.toLowerCase().includes(search.toLowerCase()) || (i.ownerFullName?.toLowerCase().includes(search.toLowerCase()) ?? false));

  return (
    <div>
      <div className="flex flex-wrap items-center gap-3 mb-5">
        <div className="flex bg-card border border-border/50 rounded-xl p-1 shadow-sm">
          {sFilters.map((f) => (
            <button key={f.v} onClick={() => setStatus(f.v)}
              className={cn("px-3.5 py-1.5 rounded-lg text-xs font-semibold transition-all",
                status === f.v ? "bg-accent text-white shadow-sm" : "text-muted hover:text-foreground")}>
              {f.l}
            </button>
          ))}
        </div>
        <div className="relative">
          <svg className="absolute left-3 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-muted pointer-events-none" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M21 21l-5.197-5.197m0 0A7.5 7.5 0 105.196 5.196a7.5 7.5 0 0010.607 10.607z" />
          </svg>
          <input type="text" placeholder="Pretrazi..." value={search} onChange={(e) => setSearch(e.target.value)}
            className="pl-9 pr-3 py-2 rounded-xl border border-border/60 bg-card/50 text-sm placeholder:text-muted focus:outline-none focus:ring-2 focus:ring-accent/20 focus:border-accent/30 w-44" />
        </div>
      </div>

      {loading ? <Spin /> : (
        <>
          <div className="bg-card border border-border/50 rounded-2xl shadow-sm overflow-hidden">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border/50">
                  <th className="text-left px-5 py-3.5 text-[11px] text-muted uppercase tracking-wider font-medium">Datoteka</th>
                  <th className="text-left px-5 py-3.5 text-[11px] text-muted uppercase tracking-wider font-medium hidden sm:table-cell">Korisnik</th>
                  <th className="text-center px-5 py-3.5 text-[11px] text-muted uppercase tracking-wider font-medium">Status</th>
                  <th className="text-center px-5 py-3.5 text-[11px] text-muted uppercase tracking-wider font-medium hidden md:table-cell">Rizik</th>
                  <th className="text-right px-5 py-3.5 text-[11px] text-muted uppercase tracking-wider font-medium hidden md:table-cell">Vrijeme</th>
                  <th className="text-right px-5 py-3.5 text-[11px] text-muted uppercase tracking-wider font-medium">Datum</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border/30">
                {filtered.map((i) => (
                  <tr key={i.id} className="hover:bg-accent/[0.03] transition-colors">
                    <td className="px-5 py-4">
                      <Link href={`/inspections/${i.id}`} className="text-accent hover:underline truncate block max-w-[220px] font-medium">{i.originalFileName}</Link>
                    </td>
                    <td className="px-5 py-4 text-muted text-xs hidden sm:table-cell truncate max-w-[150px]">{i.ownerFullName || "—"}</td>
                    <td className="px-5 py-4 text-center"><StatusPill s={i.status} /></td>
                    <td className="px-5 py-4 text-center hidden md:table-cell">{i.forensicResult ? <RiskLabel level={i.forensicResult.overallRiskLevel} /> : <span className="text-muted">—</span>}</td>
                    <td className="px-5 py-4 text-right text-muted text-xs hidden md:table-cell font-mono">
                      {i.completedAt ? `${((new Date(i.completedAt).getTime() - new Date(i.createdAt).getTime()) / 1000).toFixed(1)}s` : "—"}
                    </td>
                    <td className="px-5 py-4 text-right text-muted text-xs">{shortDate(i.createdAt)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            {filtered.length === 0 && <div className="py-16 text-center text-sm text-muted">Nema rezultata</div>}
          </div>
          <div className="flex items-center justify-between mt-5">
            <span className="text-xs text-muted">Stranica {page}</span>
            <div className="flex gap-2">
              <PgBtn disabled={page === 1} onClick={() => setPage(page - 1)}>Prethodna</PgBtn>
              <PgBtn disabled={ins.length < ps} onClick={() => setPage(page + 1)}>Sljedeca</PgBtn>
            </div>
          </div>
        </>
      )}
    </div>
  );
}

/* ================================================================== */
/*  STATISTICS                                                         */
/* ================================================================== */
function StatisticsTab({ stats, loading }: { stats: AdminStats | null; loading: boolean }) {
  if (loading || !stats) return <Spin />;

  return (
    <div className="space-y-6">
      {stats.analysesPerDay.length > 0 && (
        <Card title="Analize po danu — 30 dana">
          <div className="h-[260px] -mx-2">
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={stats.analysesPerDay} margin={{ top: 8, right: 12, bottom: 0, left: -16 }}>
                <defs>
                  <linearGradient id="sGrad" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="var(--color-accent)" stopOpacity={0.2} />
                    <stop offset="95%" stopColor="var(--color-accent)" stopOpacity={0} />
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" stroke="var(--color-border)" strokeOpacity={0.3} vertical={false} />
                <XAxis dataKey="date" tickFormatter={(v: string) => v.slice(8)} tick={{ fill: "var(--color-muted)", fontSize: 10 }} axisLine={false} tickLine={false} interval={4} />
                <YAxis tick={{ fill: "var(--color-muted)", fontSize: 10 }} axisLine={false} tickLine={false} allowDecimals={false} width={30} />
                <Tooltip content={<ChartTip />} cursor={{ stroke: "var(--color-border)", strokeDasharray: "3 3" }} />
                <Area type="monotone" dataKey="count" stroke="var(--color-accent)" strokeWidth={2} fill="url(#sGrad)" dot={false} activeDot={{ r: 5, strokeWidth: 2, stroke: "var(--color-card)", fill: "var(--color-accent)" }} />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        </Card>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <DistPanel title="Razina rizika" data={stats.riskLevelDistribution} colorFn={riskColor} labelFn={riskLabel} />
        <DistPanel title="Verdikt" data={stats.verdictDistribution} colorFn={verdictColor} labelFn={verdictLabel} />
        <DistPanel title="Odluke sustava" data={stats.decisionOutcomeDistribution} colorFn={decisionColor} labelFn={decisionLabel} />
        <DistPanel title="Tipovi datoteka" data={stats.fileTypeDistribution} colorFn={fileTypeColor} labelFn={(k) => k.toUpperCase()} />
      </div>
    </div>
  );
}

function DistPanel({ title, data, colorFn, labelFn }: { title: string; data: Record<string, number>; colorFn: (k: string) => string; labelFn: (k: string) => string }) {
  const entries = Object.entries(data).sort((a, b) => b[1] - a[1]);
  const total = entries.reduce((s, [, c]) => s + c, 0);
  const chartData = entries.map(([key, count]) => ({ name: labelFn(key), value: count }));
  const chartColors = entries.map(([key]) => colorFn(key));

  return (
    <Card title={title}>
      {entries.length === 0 ? <p className="text-sm text-muted py-6 text-center">Nema podataka</p> : (
        <div className="flex items-center gap-6">
          {/* Donut chart */}
          <div className="relative w-[130px] h-[130px] shrink-0">
            <ResponsiveContainer>
              <PieChart>
                <Pie data={chartData} cx="50%" cy="50%" innerRadius={38} outerRadius={56} paddingAngle={3} dataKey="value" stroke="none" animationDuration={800}>
                  {chartData.map((_, i) => <Cell key={i} fill={chartColors[i]} />)}
                </Pie>
              </PieChart>
            </ResponsiveContainer>
            <div className="absolute inset-0 flex items-center justify-center pointer-events-none">
              <div className="text-center">
                <div className="text-lg font-stat font-bold leading-none">{total}</div>
                <div className="text-[9px] text-muted uppercase tracking-wider mt-0.5">ukupno</div>
              </div>
            </div>
          </div>

          {/* Legend */}
          <div className="flex-1 space-y-2.5 min-w-0">
            {entries.map(([key, count]) => {
              const pct = total > 0 ? (count / total * 100).toFixed(0) : "0";
              return (
                <div key={key} className="flex items-center gap-2.5">
                  <div className="w-2.5 h-2.5 rounded-full shrink-0" style={{ backgroundColor: colorFn(key) }} />
                  <span className="text-sm truncate flex-1">{labelFn(key)}</span>
                  <span className="text-sm font-stat font-bold tabular-nums">{count}</span>
                  <span className="text-[11px] text-muted tabular-nums w-9 text-right">{pct}%</span>
                </div>
              );
            })}
          </div>
        </div>
      )}
    </Card>
  );
}

/* ================================================================== */
/*  SHARED COMPONENTS                                                  */
/* ================================================================== */
function KpiCard({ i, label, value, sub, color, icon }: {
  i: number; label: string; value: number; sub?: string; color: string; icon: string;
}) {
  const d = useCountUp(value, true);
  return (
    <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.3, delay: i * 0.06 }}>
      <div className="relative bg-card border border-border/50 rounded-2xl p-5 shadow-sm overflow-hidden group hover:shadow-md transition-shadow h-full">
        {/* Decorative gradient orb */}
        <div className="absolute -top-10 -right-10 w-28 h-28 rounded-full blur-3xl opacity-[0.12] transition-opacity group-hover:opacity-[0.2]"
          style={{ backgroundColor: color }} />

        <div className="relative">
          <div className="w-10 h-10 rounded-xl flex items-center justify-center mb-3"
            style={{ backgroundColor: `${color}15` }}>
            <svg className="w-5 h-5" style={{ color }} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
              <path strokeLinecap="round" strokeLinejoin="round" d={icon} />
            </svg>
          </div>
          <div className="text-[11px] text-muted uppercase tracking-wider font-medium">{label}</div>
          <div className="text-3xl font-stat font-bold tabular-nums leading-none tracking-tight mt-1.5" style={{ color: value > 0 && color === "#ef4444" ? color : undefined }}>
            {Math.round(d)}
          </div>
          {sub && <div className="text-xs text-muted mt-2">{sub}</div>}
        </div>
      </div>
    </motion.div>
  );
}

function QuickStat({ label, value, live }: { label: string; value: string | number; live?: boolean }) {
  return (
    <motion.div initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.12 }}>
      <div className="bg-card/60 border border-border/40 rounded-xl px-4 py-3">
        <div className="text-[10px] text-muted uppercase tracking-wider font-medium">{label}</div>
        <div className="flex items-center gap-1.5 mt-1">
          <span className="text-lg font-stat font-bold leading-none">{value}</span>
          {live && (
            <span className="relative flex h-1.5 w-1.5">
              <span className="animate-ping absolute h-full w-full rounded-full bg-blue-400 opacity-60" />
              <span className="relative rounded-full h-1.5 w-1.5 bg-blue-500" />
            </span>
          )}
        </div>
      </div>
    </motion.div>
  );
}

function Card({ title, children, delay = 0 }: { title?: string; children: React.ReactNode; delay?: number }) {
  return (
    <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ delay, duration: 0.2 }}>
      <div className="bg-card border border-border/50 rounded-2xl p-6 shadow-sm">
        {title && <h3 className="text-sm font-medium mb-5">{title}</h3>}
        {children}
      </div>
    </motion.div>
  );
}

function MiniInfo({ label, value, bold }: { label: string; value: string; bold?: boolean }) {
  return (
    <div className="bg-card/60 border border-border/40 rounded-xl p-3.5">
      <div className="text-[10px] text-muted uppercase tracking-wider font-medium">{label}</div>
      <div className={cn("text-sm mt-1 truncate", bold ? "font-stat font-bold" : "font-medium")}>{value}</div>
    </div>
  );
}

function ChartTip({ active, payload, label }: { active?: boolean; payload?: Array<{ value: number }>; label?: string }) {
  if (!active || !payload?.length) return null;
  return (
    <div className="rounded-xl border border-border/50 bg-card px-4 py-2.5 shadow-lg">
      <p className="text-[10px] text-muted mb-0.5">{label}</p>
      <p className="text-sm font-stat font-bold">{payload[0].value} <span className="text-xs text-muted font-normal">analiza</span></p>
    </div>
  );
}

function Pill({ c, children }: { c: "purple" | "green" | "red" | "gray"; children: React.ReactNode }) {
  const s: Record<string, string> = {
    purple: "bg-purple-500/10 text-purple-400 ring-purple-500/20",
    green: "bg-emerald-500/10 text-emerald-400 ring-emerald-500/20",
    red: "bg-red-500/10 text-red-400 ring-red-500/20",
    gray: "bg-card-hover/50 text-muted ring-border/50",
  };
  return <span className={cn("inline-flex px-2.5 py-0.5 rounded-lg text-[11px] font-semibold ring-1 ring-inset", s[c])}>{children}</span>;
}

function StatusPill({ s }: { s: string }) {
  const m: Record<string, "green" | "red" | "purple" | "gray"> = { Completed: "green", Failed: "red", Analyzing: "purple" };
  const l: Record<string, string> = { Completed: "Zavrseno", Analyzing: "U analizi", Pending: "Cekanje", Failed: "Neuspjelo" };
  return <Pill c={m[s] || "gray"}>{l[s] || s}</Pill>;
}

function StatusDot({ s }: { s: string }) {
  const c: Record<string, string> = { Completed: "bg-emerald-500", Analyzing: "bg-blue-500", Pending: "bg-amber-500", Failed: "bg-red-500" };
  return <div className={cn("w-2 h-2 rounded-full shrink-0", c[s] || "bg-muted")} />;
}

function RiskLabel({ level }: { level: string }) {
  const c: Record<string, string> = { Low: "text-emerald-400", Medium: "text-amber-400", High: "text-orange-400", Critical: "text-red-400" };
  const l: Record<string, string> = { Low: "Nizak", Medium: "Srednji", High: "Visok", Critical: "Kritican" };
  return <span className={cn("text-[11px] font-semibold", c[level] || "text-muted")}>{l[level] || level}</span>;
}

function PgBtn({ children, ...p }: React.ButtonHTMLAttributes<HTMLButtonElement>) {
  return (
    <button {...p} className="px-4 py-2 rounded-xl text-xs font-semibold border border-border/50 text-muted hover:text-foreground hover:bg-card shadow-sm disabled:opacity-25 disabled:cursor-not-allowed transition-all">
      {children}
    </button>
  );
}

function Spin() {
  return <div className="flex justify-center py-20"><div className="w-7 h-7 border-2 border-accent border-t-transparent rounded-full animate-spin" /></div>;
}

/* ------------------------------------------------------------------ */
/*  Helpers                                                            */
/* ------------------------------------------------------------------ */
function shortDate(d: string) { return formatDate(d).split(" ")[0]; }
function riskColor(l: string) { return ({ Low: "#22c55e", Medium: "#f59e0b", High: "#f97316", Critical: "#ef4444" })[l] || "#71717a"; }
function riskLabel(l: string) { return ({ Low: "Nizak", Medium: "Srednji", High: "Visok", Critical: "Kritican" })[l] || l; }
function verdictColor(v: string) { return ({ authentic: "#22c55e", ai_generated: "#a855f7", tampered: "#ef4444" })[v] || "#71717a"; }
function verdictLabel(v: string) { return ({ authentic: "Autenticno", ai_generated: "AI generirano", tampered: "Manipulirano" })[v] || v; }
function decisionColor(o: string) { return ({ AutoApprove: "#22c55e", HumanReview: "#f59e0b", Escalate: "#ef4444" })[o] || "#71717a"; }
function decisionLabel(o: string) { return ({ AutoApprove: "Autenticno", HumanReview: "Pregled", Escalate: "Eskalacija" })[o] || o; }
function fileTypeColor(t: string) { return ({ jpeg: "#3b82f6", jpg: "#3b82f6", png: "#8b5cf6", webp: "#f59e0b", pdf: "#ef4444", tiff: "#06b6d4", gif: "#10b981" })[t.toLowerCase()] || "#71717a"; }
