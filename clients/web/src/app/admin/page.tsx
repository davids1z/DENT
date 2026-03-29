"use client";

import { useEffect, useState, useCallback } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { motion, AnimatePresence } from "framer-motion";
import { AreaChart, Area, XAxis, YAxis, Tooltip, ResponsiveContainer, BarChart, Bar, Cell } from "recharts";
import { useAuth } from "@/lib/auth";
import { cn } from "@/lib/cn";
import {
  getAdminUsers, getAdminStats, deactivateUser, activateUser, changeUserRole,
  getInspections, formatDate,
  type AdminUser, type AdminStats, type Inspection,
} from "@/lib/api";

// ---------------------------------------------------------------------------
// Hooks
// ---------------------------------------------------------------------------
function useCountUp(target: number, on: boolean, dur = 900) {
  const [v, setV] = useState(0);
  useEffect(() => {
    if (!on) { setV(0); return; }
    const t0 = performance.now();
    let id: number;
    const tick = (now: number) => { const p = Math.min((now - t0) / dur, 1); setV((1 - (1 - p) ** 3) * target); if (p < 1) id = requestAnimationFrame(tick); };
    id = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(id);
  }, [target, on, dur]);
  return v;
}

// ---------------------------------------------------------------------------
// Views
// ---------------------------------------------------------------------------
const mainTabs = ["pregled", "korisnici", "analize", "statistika"] as const;
const tabLabel: Record<string, string> = { pregled: "Pregled", korisnici: "Korisnici", analize: "Analize", statistika: "Statistika" };
type View = (typeof mainTabs)[number] | "user";

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

  return (
    <div className="max-w-7xl mx-auto px-4 sm:px-6 py-8">
      <motion.h1 initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="font-heading text-3xl font-extrabold tracking-tight mb-6">Admin panel</motion.h1>

      {/* Tabs or breadcrumb */}
      {view === "user" && selUser ? (
        <button onClick={closeUser} className="flex items-center gap-2 text-sm text-accent hover:underline mb-6 group">
          <svg className="w-4 h-4 transition-transform group-hover:-translate-x-0.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M15.75 19.5L8.25 12l7.5-7.5" />
          </svg>
          Natrag na korisnike
        </button>
      ) : (
        <div className="flex gap-1 mb-8 border-b border-border overflow-x-auto">
          {mainTabs.map((t) => (
            <button key={t} onClick={() => setView(t)}
              className={cn("relative px-5 py-2.5 text-sm font-medium transition-colors whitespace-nowrap", view === t ? "text-foreground" : "text-muted hover:text-foreground")}>
              {tabLabel[t]}
              {view === t && <motion.div className="absolute bottom-0 left-2 right-2 h-0.5 bg-accent rounded-full" layoutId="atab" transition={{ type: "spring", stiffness: 500, damping: 35 }} />}
            </button>
          ))}
        </div>
      )}

      <AnimatePresence mode="wait">
        <motion.div key={view} initial={{ opacity: 0, y: 4 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }} transition={{ duration: 0.1 }}>
          {view === "pregled" && <OverviewTab stats={stats} loading={statsLoading} />}
          {view === "korisnici" && <UsersTab onSelect={openUser} />}
          {view === "analize" && <AnalysesTab />}
          {view === "statistika" && <StatisticsTab stats={stats} loading={statsLoading} />}
          {view === "user" && selUser && <UserDetail user={selUser} onBack={closeUser} />}
        </motion.div>
      </AnimatePresence>
    </div>
  );
}

// =========================================================================
// OVERVIEW
// =========================================================================
function OverviewTab({ stats, loading }: { stats: AdminStats | null; loading: boolean }) {
  if (loading || !stats) return <Spin />;

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <KPI i={0} label="Korisnici" val={stats.totalUsers} sub={`${stats.activeUsers} aktivnih`} />
        <KPI i={1} label="Analiza" val={stats.totalInspections} spark={stats.analysesPerDay.map((d) => d.count)} />
        <KPI i={2} label="Dovrseno" val={stats.completedInspections} accent="text-emerald-400" />
        <KPI i={3} label="Neuspjelo" val={stats.failedInspections} accent={stats.failedInspections > 0 ? "text-red-400" : undefined} />
      </div>

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <KPI i={0} label="Novi danas" val={stats.usersRegisteredToday} />
        <KPI i={1} label="Novi tjedan" val={stats.usersRegisteredThisWeek} />
        <KPI i={2} label="Vrijeme obrade" val={stats.averageProcessingTimeMs / 1000} dec={1} suf="s" />
        <KPI i={3} label="Red cekanja" val={stats.queuePending} live={stats.queuePending > 0} />
      </div>

      {/* Recharts area chart */}
      {stats.analysesPerDay.length > 0 && (
        <Card title="Aktivnost — zadnjih 30 dana" delay={0.15}>
          <div className="h-[220px] -mx-2">
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={stats.analysesPerDay} margin={{ top: 4, right: 4, bottom: 0, left: -20 }}>
                <defs>
                  <linearGradient id="aGrad" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor="var(--color-accent-solid)" stopOpacity={0.3} />
                    <stop offset="95%" stopColor="var(--color-accent-solid)" stopOpacity={0} />
                  </linearGradient>
                </defs>
                <XAxis dataKey="date" tickFormatter={(v: string) => v.slice(5)} tick={{ fill: "var(--color-muted)", fontSize: 10 }} axisLine={false} tickLine={false} />
                <YAxis tick={{ fill: "var(--color-muted)", fontSize: 10 }} axisLine={false} tickLine={false} allowDecimals={false} />
                <Tooltip content={<ChartTip />} />
                <Area type="monotone" dataKey="count" stroke="var(--color-accent-solid)" strokeWidth={2} fill="url(#aGrad)" dot={false} activeDot={{ r: 4, strokeWidth: 0, fill: "var(--color-accent-solid)" }} />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        </Card>
      )}

      {stats.recentFailures.length > 0 && (
        <Card title="Nedavni neuspjesi" delay={0.2}>
          {stats.recentFailures.slice(0, 5).map((f) => (
            <Link key={f.id} href={`/inspections/${f.id}`} className="flex items-center justify-between py-2.5 hover:bg-card-hover -mx-2 px-2 rounded-lg transition-colors">
              <div className="flex items-center gap-2.5 min-w-0">
                <div className="w-1.5 h-1.5 rounded-full bg-red-400 shrink-0" />
                <span className="text-sm truncate">{f.originalFileName}</span>
                <span className="text-xs text-muted hidden sm:inline">— {f.userFullName || "?"}</span>
              </div>
              <span className="text-xs text-muted shrink-0 ml-3">{shortDate(f.createdAt)}</span>
            </Link>
          ))}
        </Card>
      )}
    </div>
  );
}

function ChartTip({ active, payload, label }: { active?: boolean; payload?: Array<{ value: number }>; label?: string }) {
  if (!active || !payload?.length) return null;
  return (
    <div className="bg-foreground text-background text-xs px-3 py-1.5 rounded-lg shadow-lg">
      <span className="text-muted-light">{label?.slice(5)}</span>: <strong>{payload[0].value}</strong>
    </div>
  );
}

// =========================================================================
// USERS TABLE
// =========================================================================
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
      <input type="text" placeholder="Pretrazi korisnike..." value={search} onChange={(e) => setSearch(e.target.value)}
        className="w-full max-w-sm px-4 py-2.5 rounded-xl border border-border bg-card text-sm placeholder:text-muted focus:outline-none focus:ring-2 focus:ring-accent/20 mb-4" />
      <div className="border border-border rounded-2xl overflow-hidden">
        <table className="w-full text-sm">
          <thead><tr className="bg-card/60 border-b border-border text-muted text-[11px] uppercase tracking-wider">
            <th className="text-left px-4 py-3 font-medium">Korisnik</th>
            <th className="text-left px-4 py-3 font-medium hidden sm:table-cell">Uloga</th>
            <th className="text-left px-4 py-3 font-medium hidden md:table-cell">Registriran</th>
            <th className="text-left px-4 py-3 font-medium hidden lg:table-cell">Zadnja prijava</th>
            <th className="text-center px-4 py-3 font-medium">Analiza</th>
            <th className="text-center px-4 py-3 font-medium">Status</th>
            <th className="text-right px-4 py-3 font-medium" />
          </tr></thead>
          <tbody>
            {filtered.map((u) => (
              <tr key={u.id} onClick={() => onSelect(u)} className="border-b border-border last:border-0 hover:bg-card/80 transition-colors cursor-pointer">
                <td className="px-4 py-3.5">
                  <div className="flex items-center gap-3">
                    <div className={cn("w-8 h-8 rounded-full flex items-center justify-center text-xs font-bold shrink-0", u.role === "Admin" ? "bg-purple-500/15 text-purple-400" : "bg-accent/10 text-accent")}>
                      {u.fullName.charAt(0).toUpperCase()}
                    </div>
                    <div className="min-w-0"><div className="font-medium truncate">{u.fullName}</div><div className="text-xs text-muted truncate">{u.email}</div></div>
                  </div>
                </td>
                <td className="px-4 py-3.5 hidden sm:table-cell"><Pill c={u.role === "Admin" ? "purple" : "gray"}>{u.role}</Pill></td>
                <td className="px-4 py-3.5 text-muted hidden md:table-cell">{shortDate(u.createdAt)}</td>
                <td className="px-4 py-3.5 text-muted hidden lg:table-cell">{u.lastLoginAt ? shortDate(u.lastLoginAt) : "—"}</td>
                <td className="px-4 py-3.5 text-center font-stat font-bold">{u.inspectionCount}</td>
                <td className="px-4 py-3.5 text-center"><Pill c={u.isActive ? "green" : "red"}>{u.isActive ? "Aktivan" : "Neaktivan"}</Pill></td>
                <td className="px-4 py-3.5 text-right">
                  <svg className="w-4 h-4 text-muted inline" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}><path strokeLinecap="round" strokeLinejoin="round" d="M8.25 4.5l7.5 7.5-7.5 7.5" /></svg>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {filtered.length === 0 && <div className="py-12 text-center text-sm text-muted">Nema rezultata</div>}
      </div>
    </div>
  );
}

// =========================================================================
// USER DETAIL
// =========================================================================
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
      {/* Header */}
      <div className="flex items-start gap-4 flex-wrap">
        <div className={cn("w-14 h-14 rounded-2xl flex items-center justify-center text-xl font-bold shrink-0",
          localUser.role === "Admin" ? "bg-purple-500/15 text-purple-400" : "bg-accent/10 text-accent")}>
          {u.fullName.charAt(0).toUpperCase()}
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <h2 className="font-heading text-xl font-bold">{u.fullName}</h2>
            <Pill c={localUser.role === "Admin" ? "purple" : "gray"}>{localUser.role}</Pill>
            <Pill c={localUser.isActive ? "green" : "red"}>{localUser.isActive ? "Aktivan" : "Neaktivan"}</Pill>
          </div>
          <div className="text-muted mt-0.5">{u.email}</div>
        </div>
      </div>

      {/* Info row */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        <MiniInfo label="Registriran" value={shortDate(u.createdAt)} />
        <MiniInfo label="Zadnja prijava" value={u.lastLoginAt ? formatDate(u.lastLoginAt) : "Nikad"} />
        <MiniInfo label="Ukupno analiza" value={String(u.inspectionCount)} bold />
        <MiniInfo label="Dovrseno / Neuspjelo" value={`${completed} / ${failed}`} bold />
      </div>

      {/* Actions */}
      <Card title="Upravljanje">
        <div className="flex flex-wrap items-center gap-3">
          {/* Role switcher */}
          <div className="flex items-center gap-2">
            <span className="text-xs text-muted">Uloga:</span>
            <div className="flex bg-background border border-border rounded-lg p-0.5">
              <button onClick={() => switchRole("User")} disabled={busy}
                className={cn("px-3 py-1.5 rounded-md text-xs font-medium transition-all", localUser.role === "User" ? "bg-accent text-white shadow-sm" : "text-muted hover:text-foreground")}>
                User
              </button>
              <button onClick={() => switchRole("Admin")} disabled={busy}
                className={cn("px-3 py-1.5 rounded-md text-xs font-medium transition-all", localUser.role === "Admin" ? "bg-purple-500 text-white shadow-sm" : "text-muted hover:text-foreground")}>
                Admin
              </button>
            </div>
          </div>

          <div className="w-px h-6 bg-border hidden sm:block" />

          {/* Activate/deactivate */}
          <button onClick={toggle} disabled={busy}
            className={cn("px-4 py-2 rounded-lg text-xs font-medium border transition-colors disabled:opacity-50",
              localUser.isActive ? "border-red-500/20 text-red-400 hover:bg-red-500/10" : "border-green-500/20 text-green-400 hover:bg-green-500/10")}>
            {localUser.isActive ? "Deaktiviraj" : "Aktiviraj"}
          </button>
        </div>
      </Card>

      {/* Inspections */}
      <Card title={`Analize (${inspections.length})`}>
        {loading ? <Spin /> : inspections.length === 0 ? (
          <p className="text-sm text-muted py-4 text-center">Nema analiza</p>
        ) : (
          <div className="divide-y divide-border -mx-1">
            {inspections.map((ins) => (
              <Link key={ins.id} href={`/inspections/${ins.id}`}
                className="flex items-center gap-3 py-3 px-1 hover:bg-card-hover rounded-lg transition-colors">
                <StatusDot s={ins.status} />
                <span className="text-sm truncate flex-1">{ins.originalFileName}</span>
                {ins.forensicResult && <RiskLabel level={ins.forensicResult.overallRiskLevel} />}
                <span className="text-xs text-muted shrink-0">{shortDate(ins.createdAt)}</span>
                <svg className="w-3.5 h-3.5 text-muted shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}><path strokeLinecap="round" strokeLinejoin="round" d="M8.25 4.5l7.5 7.5-7.5 7.5" /></svg>
              </Link>
            ))}
          </div>
        )}
      </Card>
    </div>
  );
}

// =========================================================================
// ANALYSES
// =========================================================================
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
      <div className="flex flex-wrap items-center gap-3 mb-4">
        <div className="flex bg-card border border-border rounded-xl p-0.5">
          {sFilters.map((f) => (
            <button key={f.v} onClick={() => setStatus(f.v)}
              className={cn("px-3 py-1.5 rounded-lg text-xs font-medium transition-all", status === f.v ? "bg-accent text-white shadow-sm" : "text-muted hover:text-foreground")}>
              {f.l}
            </button>
          ))}
        </div>
        <input type="text" placeholder="Pretrazi..." value={search} onChange={(e) => setSearch(e.target.value)}
          className="px-3 py-2 rounded-xl border border-border bg-card text-sm placeholder:text-muted focus:outline-none focus:ring-2 focus:ring-accent/20 w-48" />
      </div>

      {loading ? <Spin /> : (
        <>
          <div className="border border-border rounded-2xl overflow-hidden">
            <table className="w-full text-sm">
              <thead><tr className="bg-card/60 border-b border-border text-muted text-[11px] uppercase tracking-wider">
                <th className="text-left px-4 py-3 font-medium">Datoteka</th>
                <th className="text-left px-4 py-3 font-medium hidden sm:table-cell">Korisnik</th>
                <th className="text-center px-4 py-3 font-medium">Status</th>
                <th className="text-center px-4 py-3 font-medium hidden md:table-cell">Rizik</th>
                <th className="text-right px-4 py-3 font-medium hidden md:table-cell">Vrijeme</th>
                <th className="text-right px-4 py-3 font-medium">Datum</th>
              </tr></thead>
              <tbody>
                {filtered.map((i) => (
                  <tr key={i.id} className="border-b border-border last:border-0 hover:bg-card/80 transition-colors">
                    <td className="px-4 py-3"><Link href={`/inspections/${i.id}`} className="text-accent hover:underline truncate block max-w-[220px]">{i.originalFileName}</Link></td>
                    <td className="px-4 py-3 text-muted hidden sm:table-cell truncate max-w-[150px]">{i.ownerFullName || "—"}</td>
                    <td className="px-4 py-3 text-center"><StatusPill s={i.status} /></td>
                    <td className="px-4 py-3 text-center hidden md:table-cell">{i.forensicResult ? <RiskLabel level={i.forensicResult.overallRiskLevel} /> : <span className="text-muted">—</span>}</td>
                    <td className="px-4 py-3 text-right text-muted text-xs hidden md:table-cell font-mono">
                      {i.completedAt ? `${((new Date(i.completedAt).getTime() - new Date(i.createdAt).getTime()) / 1000).toFixed(1)}s` : "—"}
                    </td>
                    <td className="px-4 py-3 text-right text-muted text-xs">{shortDate(i.createdAt)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            {filtered.length === 0 && <div className="py-12 text-center text-sm text-muted">Nema rezultata</div>}
          </div>
          <div className="flex items-center justify-between mt-4">
            <span className="text-xs text-muted">Str. {page}</span>
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

// =========================================================================
// STATISTICS
// =========================================================================
function StatisticsTab({ stats, loading }: { stats: AdminStats | null; loading: boolean }) {
  if (loading || !stats) return <Spin />;

  const distColors: Record<string, string> = { ...Object.fromEntries(Object.keys(stats.riskLevelDistribution).map((k) => [k, riskColor(k)])) };

  return (
    <div className="space-y-6">
      {/* Recharts area chart */}
      {stats.analysesPerDay.length > 0 && (
        <Card title="Analize po danu — 30 dana">
          <div className="h-[240px] -mx-2">
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={stats.analysesPerDay} margin={{ top: 4, right: 4, bottom: 0, left: -20 }}>
                <defs>
                  <linearGradient id="sGrad" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor="var(--color-accent-solid)" stopOpacity={0.35} />
                    <stop offset="95%" stopColor="var(--color-accent-solid)" stopOpacity={0} />
                  </linearGradient>
                </defs>
                <XAxis dataKey="date" tickFormatter={(v: string) => v.slice(5)} tick={{ fill: "var(--color-muted)", fontSize: 10 }} axisLine={false} tickLine={false} />
                <YAxis tick={{ fill: "var(--color-muted)", fontSize: 10 }} axisLine={false} tickLine={false} allowDecimals={false} />
                <Tooltip content={<ChartTip />} />
                <Area type="monotone" dataKey="count" stroke="var(--color-accent-solid)" strokeWidth={2} fill="url(#sGrad)" dot={false} activeDot={{ r: 4, strokeWidth: 0, fill: "var(--color-accent-solid)" }} />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        </Card>
      )}

      {/* Recharts bar charts for distributions */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <DistChart title="Razina rizika" data={stats.riskLevelDistribution} colorFn={riskColor} labelFn={riskLabel} />
        <DistChart title="Verdikt" data={stats.verdictDistribution} colorFn={verdictColor} labelFn={verdictLabel} />
        <DistChart title="Odluke sustava" data={stats.decisionOutcomeDistribution} colorFn={decisionColor} labelFn={decisionLabel} />
        <DistChart title="Tipovi datoteka" data={stats.fileTypeDistribution} colorFn={() => "var(--color-accent-solid)"} labelFn={(k) => k.toUpperCase()} />
      </div>
    </div>
  );
}

function DistChart({ title, data, colorFn, labelFn }: { title: string; data: Record<string, number>; colorFn: (k: string) => string; labelFn: (k: string) => string }) {
  const entries = Object.entries(data).sort((a, b) => b[1] - a[1]);
  const total = entries.reduce((s, [, c]) => s + c, 0);
  const chartData = entries.map(([key, count]) => ({ name: labelFn(key), value: count, key, pct: total > 0 ? Math.round((count / total) * 100) : 0 }));

  return (
    <Card title={title}>
      {chartData.length === 0 ? <p className="text-sm text-muted py-4 text-center">Nema podataka</p> : (
        <div className="h-[160px] -mx-2">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={chartData} layout="vertical" margin={{ top: 0, right: 8, bottom: 0, left: 0 }}>
              <XAxis type="number" hide />
              <YAxis type="category" dataKey="name" tick={{ fill: "var(--color-foreground)", fontSize: 12 }} axisLine={false} tickLine={false} width={90} />
              <Tooltip content={<DistTip />} />
              <Bar dataKey="value" radius={[0, 4, 4, 0]} barSize={14}>
                {chartData.map((d) => <Cell key={d.key} fill={colorFn(d.key)} fillOpacity={0.8} />)}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}
    </Card>
  );
}

function DistTip({ active, payload }: { active?: boolean; payload?: Array<{ payload: { name: string; value: number; pct: number } }> }) {
  if (!active || !payload?.length) return null;
  const d = payload[0].payload;
  return (
    <div className="bg-foreground text-background text-xs px-3 py-1.5 rounded-lg shadow-lg">
      {d.name}: <strong>{d.value}</strong> ({d.pct}%)
    </div>
  );
}

// =========================================================================
// SHARED
// =========================================================================
function KPI({ i, label, val, sub, accent, spark, live, dec, suf }: {
  i: number; label: string; val: number; sub?: string; accent?: string; spark?: number[]; live?: boolean; dec?: number; suf?: string;
}) {
  const d = useCountUp(val, true);
  return (
    <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.3, delay: i * 0.04 }}>
      <div className="bg-card border border-border rounded-2xl p-4 h-full relative overflow-hidden">
        <div className="text-[11px] text-muted uppercase tracking-wider font-medium">{label}</div>
        <div className="flex items-end justify-between mt-1.5">
          <span className={cn("text-2xl font-stat font-bold tabular-nums leading-none", accent)}>
            {dec !== undefined ? d.toFixed(dec) : Math.round(d)}{suf || ""}
          </span>
          {spark && spark.length > 2 && <Sparkline data={spark} />}
          {live && <span className="relative flex h-2.5 w-2.5 mb-1"><span className="animate-ping absolute h-full w-full rounded-full bg-blue-400 opacity-50" /><span className="relative rounded-full h-2.5 w-2.5 bg-blue-500" /></span>}
        </div>
        {sub && <div className="text-xs text-muted mt-1">{sub}</div>}
      </div>
    </motion.div>
  );
}

function Sparkline({ data }: { data: number[] }) {
  const w = 56, h = 20, max = Math.max(...data, 1);
  const pts = data.map((v, i) => `${(i / (data.length - 1)) * w},${h - (v / max) * h}`).join(" ");
  return (
    <svg width={w} height={h} className="shrink-0 opacity-50">
      <defs><linearGradient id="spk" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="var(--color-accent-solid)" stopOpacity="0.3" /><stop offset="100%" stopColor="var(--color-accent-solid)" stopOpacity="0" /></linearGradient></defs>
      <polygon points={`0,${h} ${pts} ${w},${h}`} fill="url(#spk)" />
      <polyline points={pts} fill="none" stroke="var(--color-accent-solid)" strokeWidth="1.5" strokeLinejoin="round" />
    </svg>
  );
}

function Card({ title, children, delay = 0 }: { title?: string; children: React.ReactNode; delay?: number }) {
  return (
    <motion.div initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} transition={{ delay, duration: 0.2 }}>
      <div className="bg-card border border-border rounded-2xl p-5">
        {title && <h3 className="text-[11px] text-muted uppercase tracking-wider font-medium mb-4">{title}</h3>}
        {children}
      </div>
    </motion.div>
  );
}

function MiniInfo({ label, value, bold }: { label: string; value: string; bold?: boolean }) {
  return <div className="bg-card border border-border rounded-xl p-3"><div className="text-[10px] text-muted uppercase tracking-wider">{label}</div><div className={cn("text-sm mt-0.5 truncate", bold ? "font-stat font-bold" : "font-medium")}>{value}</div></div>;
}

function Pill({ c, children }: { c: "purple" | "green" | "red" | "gray"; children: React.ReactNode }) {
  const s = { purple: "bg-purple-500/10 text-purple-400 border-purple-500/20", green: "bg-emerald-500/10 text-emerald-400 border-emerald-500/20", red: "bg-red-500/10 text-red-400 border-red-500/20", gray: "bg-card text-muted border-border" };
  return <span className={cn("inline-flex px-2 py-0.5 rounded-md text-[11px] font-medium border", s[c])}>{children}</span>;
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
  return <span className={cn("text-[11px] font-medium", c[level] || "text-muted")}>{l[level] || level}</span>;
}

function PgBtn({ children, ...p }: React.ButtonHTMLAttributes<HTMLButtonElement>) {
  return <button {...p} className="px-3 py-1.5 rounded-lg text-xs font-medium border border-border text-muted hover:text-foreground hover:bg-card disabled:opacity-25 disabled:cursor-not-allowed transition-colors">{children}</button>;
}

function Spin() { return <div className="flex justify-center py-16"><div className="w-6 h-6 border-2 border-accent border-t-transparent rounded-full animate-spin" /></div>; }

// Helpers
function shortDate(d: string) { return formatDate(d).split(" ")[0]; }
function riskColor(l: string) { return ({ Low: "#22c55e", Medium: "#f59e0b", High: "#f97316", Critical: "#ef4444" })[l] || "#71717a"; }
function riskLabel(l: string) { return ({ Low: "Nizak", Medium: "Srednji", High: "Visok", Critical: "Kritican" })[l] || l; }
function verdictColor(v: string) { return ({ authentic: "#22c55e", ai_generated: "#a855f7", tampered: "#ef4444" })[v] || "#71717a"; }
function verdictLabel(v: string) { return ({ authentic: "Autenticno", ai_generated: "AI generirano", tampered: "Manipulirano" })[v] || v; }
function decisionColor(o: string) { return ({ AutoApprove: "#22c55e", HumanReview: "#f59e0b", Escalate: "#ef4444" })[o] || "#71717a"; }
function decisionLabel(o: string) { return ({ AutoApprove: "Autenticno", HumanReview: "Pregled", Escalate: "Eskalacija" })[o] || o; }
