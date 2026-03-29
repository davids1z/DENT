"use client";

import { useEffect, useState, useCallback } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { motion, AnimatePresence } from "framer-motion";
import { useAuth } from "@/lib/auth";
import { cn } from "@/lib/cn";
import {
  getAdminUsers,
  getAdminStats,
  deactivateUser,
  activateUser,
  getInspections,
  formatDate,
  type AdminUser,
  type AdminStats,
  type Inspection,
} from "@/lib/api";

// ---------------------------------------------------------------------------
// Hooks
// ---------------------------------------------------------------------------
function useCountUp(target: number, enabled: boolean, dur = 900) {
  const [v, setV] = useState(0);
  useEffect(() => {
    if (!enabled) { setV(0); return; }
    const t0 = performance.now();
    let id: number;
    const tick = (now: number) => {
      const p = Math.min((now - t0) / dur, 1);
      setV((1 - Math.pow(1 - p, 3)) * target);
      if (p < 1) id = requestAnimationFrame(tick);
    };
    id = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(id);
  }, [target, enabled, dur]);
  return v;
}

// ---------------------------------------------------------------------------
// Tab system
// ---------------------------------------------------------------------------
const mainTabs = ["pregled", "korisnici", "analize", "statistika"] as const;
const tabLabels: Record<string, string> = { pregled: "Pregled", korisnici: "Korisnici", analize: "Analize", statistika: "Statistika" };
type View = (typeof mainTabs)[number] | "user-detail";

export default function AdminPage() {
  const { user, isLoading: authLoading } = useAuth();
  const router = useRouter();
  const [view, setView] = useState<View>("pregled");
  const [stats, setStats] = useState<AdminStats | null>(null);
  const [statsLoading, setStatsLoading] = useState(true);
  const [selectedUser, setSelectedUser] = useState<AdminUser | null>(null);

  useEffect(() => {
    if (authLoading) return;
    if (!user || user.role !== "Admin") { router.replace("/"); return; }
    loadStats();
  }, [user, authLoading, router]);

  async function loadStats() {
    try { setStatsLoading(true); setStats(await getAdminStats()); }
    catch {} finally { setStatsLoading(false); }
  }

  function openUser(u: AdminUser) { setSelectedUser(u); setView("user-detail"); }
  function closeUser() { setView("korisnici"); setSelectedUser(null); }

  if (authLoading || !user || user.role !== "Admin") {
    return <div className="min-h-[60dvh] flex items-center justify-center"><div className="w-7 h-7 border-2 border-accent border-t-transparent rounded-full animate-spin" /></div>;
  }

  return (
    <div className="max-w-7xl mx-auto px-4 sm:px-6 py-8">
      <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="mb-8">
        <h1 className="font-heading text-3xl font-extrabold tracking-tight">Admin panel</h1>
      </motion.div>

      {/* Tab bar */}
      {view !== "user-detail" && (
        <div className="flex gap-1 mb-8 border-b border-border overflow-x-auto">
          {mainTabs.map((t) => (
            <button key={t} onClick={() => setView(t)}
              className={cn("relative px-5 py-2.5 text-sm font-medium transition-colors whitespace-nowrap", view === t ? "text-foreground" : "text-muted hover:text-foreground")}>
              {tabLabels[t]}
              {view === t && <motion.div className="absolute bottom-0 left-2 right-2 h-0.5 bg-accent rounded-full" layoutId="atab" transition={{ type: "spring", stiffness: 500, damping: 35 }} />}
            </button>
          ))}
        </div>
      )}

      {/* Breadcrumb for user detail */}
      {view === "user-detail" && selectedUser && (
        <div className="flex items-center gap-2 mb-6 text-sm">
          <button onClick={closeUser} className="text-accent hover:underline">Korisnici</button>
          <span className="text-muted">/</span>
          <span className="text-foreground font-medium">{selectedUser.fullName}</span>
        </div>
      )}

      <AnimatePresence mode="wait">
        <motion.div key={view} initial={{ opacity: 0, y: 4 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }} transition={{ duration: 0.1 }}>
          {view === "pregled" && <OverviewTab stats={stats} loading={statsLoading} />}
          {view === "korisnici" && <UsersTab onSelectUser={openUser} />}
          {view === "analize" && <AnalysesTab />}
          {view === "statistika" && <StatisticsTab stats={stats} loading={statsLoading} />}
          {view === "user-detail" && selectedUser && <UserDetailView user={selectedUser} onBack={closeUser} onReload={loadStats} />}
        </motion.div>
      </AnimatePresence>
    </div>
  );
}

// =========================================================================
// OVERVIEW
// =========================================================================
function OverviewTab({ stats, loading }: { stats: AdminStats | null; loading: boolean }) {
  if (loading || !stats) return <Spinner />;
  const sec = stats.averageProcessingTimeMs / 1000;

  return (
    <div className="space-y-6">
      {/* KPI row */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <Metric i={0} label="Korisnici" value={stats.totalUsers} sub={`${stats.activeUsers} aktivnih`} />
        <Metric i={1} label="Analiza" value={stats.totalInspections} sparkline={stats.analysesPerDay.map((d) => d.count)} />
        <Metric i={2} label="Dovrseno" value={stats.completedInspections} accent="text-emerald-400" pct={stats.totalInspections > 0 ? Math.round((stats.completedInspections / stats.totalInspections) * 100) : 0} />
        <Metric i={3} label="Neuspjelo" value={stats.failedInspections} accent={stats.failedInspections > 0 ? "text-red-400" : undefined} />
      </div>

      {/* Secondary row */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <Metric i={0} label="Novi danas" value={stats.usersRegisteredToday} />
        <Metric i={1} label="Novi tjedan" value={stats.usersRegisteredThisWeek} />
        <Metric i={2} label="Vrijeme obrade" value={sec} decimals={1} suffix="s" />
        <Metric i={3} label="Red cekanja" value={stats.queuePending} live={stats.queuePending > 0} sub={stats.queuePending > 0 ? `${stats.queueActiveUsers} korisnika` : "prazno"} />
      </div>

      {/* Area chart */}
      {stats.analysesPerDay.length > 0 && (
        <Card title="Aktivnost — zadnjih 30 dana" delay={0.2}>
          <AreaChart data={stats.analysesPerDay} />
        </Card>
      )}

      {/* Recent failures */}
      {stats.recentFailures.length > 0 && (
        <Card title="Nedavni neuspjesi" delay={0.25}>
          {stats.recentFailures.slice(0, 5).map((f) => (
            <Link key={f.id} href={`/inspections/${f.id}`}
              className="flex items-center justify-between py-2.5 hover:bg-card-hover -mx-2 px-2 rounded-lg transition-colors">
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

// =========================================================================
// USERS TABLE (original style)
// =========================================================================
function UsersTab({ onSelectUser }: { onSelectUser: (u: AdminUser) => void }) {
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");

  useEffect(() => { load(); }, []);
  async function load() { try { setUsers(await getAdminUsers()); } catch {} finally { setLoading(false); } }

  const filtered = users.filter((u) => {
    if (!search) return true;
    const q = search.toLowerCase();
    return u.fullName.toLowerCase().includes(q) || u.email.toLowerCase().includes(q);
  });

  if (loading) return <Spinner />;

  return (
    <div>
      <input type="text" placeholder="Pretrazi korisnike..." value={search} onChange={(e) => setSearch(e.target.value)}
        className="w-full max-w-sm px-4 py-2.5 rounded-xl border border-border bg-card text-sm placeholder:text-muted focus:outline-none focus:ring-2 focus:ring-accent/20 mb-4" />

      <div className="border border-border rounded-2xl overflow-hidden">
        <table className="w-full text-sm">
          <thead>
            <tr className="bg-card/60 border-b border-border text-muted text-xs uppercase tracking-wider">
              <th className="text-left px-4 py-3 font-medium">Korisnik</th>
              <th className="text-left px-4 py-3 font-medium hidden sm:table-cell">Uloga</th>
              <th className="text-left px-4 py-3 font-medium hidden md:table-cell">Registriran</th>
              <th className="text-left px-4 py-3 font-medium hidden lg:table-cell">Zadnja prijava</th>
              <th className="text-center px-4 py-3 font-medium">Analiza</th>
              <th className="text-center px-4 py-3 font-medium">Status</th>
              <th className="text-right px-4 py-3 font-medium" />
            </tr>
          </thead>
          <tbody>
            {filtered.map((u) => (
              <tr key={u.id} onClick={() => onSelectUser(u)}
                className="border-b border-border last:border-0 hover:bg-card/80 transition-colors cursor-pointer">
                <td className="px-4 py-3.5">
                  <div className="flex items-center gap-3">
                    <div className={cn("w-8 h-8 rounded-full flex items-center justify-center text-xs font-bold shrink-0",
                      u.role === "Admin" ? "bg-purple-500/15 text-purple-400" : "bg-accent/10 text-accent")}>
                      {u.fullName.charAt(0).toUpperCase()}
                    </div>
                    <div className="min-w-0">
                      <div className="font-medium truncate">{u.fullName}</div>
                      <div className="text-xs text-muted truncate">{u.email}</div>
                    </div>
                  </div>
                </td>
                <td className="px-4 py-3.5 hidden sm:table-cell">
                  <Pill color={u.role === "Admin" ? "purple" : "default"}>{u.role}</Pill>
                </td>
                <td className="px-4 py-3.5 text-muted hidden md:table-cell">{shortDate(u.createdAt)}</td>
                <td className="px-4 py-3.5 text-muted hidden lg:table-cell">{u.lastLoginAt ? shortDate(u.lastLoginAt) : "—"}</td>
                <td className="px-4 py-3.5 text-center font-stat font-bold">{u.inspectionCount}</td>
                <td className="px-4 py-3.5 text-center">
                  <Pill color={u.isActive ? "green" : "red"}>{u.isActive ? "Aktivan" : "Neaktivan"}</Pill>
                </td>
                <td className="px-4 py-3.5 text-right">
                  <svg className="w-4 h-4 text-muted inline-block" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M8.25 4.5l7.5 7.5-7.5 7.5" />
                  </svg>
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
// USER DETAIL (full page)
// =========================================================================
function UserDetailView({ user: u, onBack, onReload }: { user: AdminUser; onBack: () => void; onReload: () => void }) {
  const [inspections, setInspections] = useState<Inspection[]>([]);
  const [loading, setLoading] = useState(true);
  const [toggling, setToggling] = useState(false);

  useEffect(() => {
    getInspections(1, 50).then((data) => {
      setInspections(data.filter((i) => i.ownerEmail === u.email));
    }).catch(() => {}).finally(() => setLoading(false));
  }, [u.email]);

  async function handleToggle() {
    setToggling(true);
    try {
      u.isActive ? await deactivateUser(u.id) : await activateUser(u.id);
      onReload();
      onBack();
    } catch {} finally { setToggling(false); }
  }

  const completed = inspections.filter((i) => i.status === "Completed").length;
  const failed = inspections.filter((i) => i.status === "Failed").length;

  return (
    <div className="space-y-6">
      {/* User header */}
      <div className="flex items-start gap-4">
        <div className={cn("w-14 h-14 rounded-2xl flex items-center justify-center text-xl font-bold shrink-0",
          u.role === "Admin" ? "bg-purple-500/15 text-purple-400" : "bg-accent/10 text-accent")}>
          {u.fullName.charAt(0).toUpperCase()}
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <h2 className="font-heading text-xl font-bold">{u.fullName}</h2>
            <Pill color={u.role === "Admin" ? "purple" : "default"}>{u.role}</Pill>
            <Pill color={u.isActive ? "green" : "red"}>{u.isActive ? "Aktivan" : "Neaktivan"}</Pill>
          </div>
          <div className="text-muted mt-0.5">{u.email}</div>
        </div>
        {u.role !== "Admin" && (
          <button onClick={handleToggle} disabled={toggling}
            className={cn("px-4 py-2 rounded-xl text-xs font-medium border transition-colors shrink-0 disabled:opacity-50",
              u.isActive ? "border-red-500/20 text-red-400 hover:bg-red-500/10" : "border-green-500/20 text-green-400 hover:bg-green-500/10")}>
            {u.isActive ? "Deaktiviraj" : "Aktiviraj"}
          </button>
        )}
      </div>

      {/* Info cards */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        <MiniCard label="Registriran" value={shortDate(u.createdAt)} />
        <MiniCard label="Zadnja prijava" value={u.lastLoginAt ? formatDate(u.lastLoginAt) : "Nikad"} />
        <MiniCard label="Ukupno analiza" value={String(u.inspectionCount)} bold />
        <MiniCard label="Dovrseno / Neuspjelo" value={`${completed} / ${failed}`} bold />
      </div>

      {/* Inspections list */}
      <Card title={`Analize korisnika (${inspections.length})`}>
        {loading ? <Spinner /> : inspections.length === 0 ? (
          <div className="text-sm text-muted py-4 text-center">Nema analiza</div>
        ) : (
          <div className="space-y-1">
            {inspections.map((ins) => (
              <Link key={ins.id} href={`/inspections/${ins.id}`}
                className="flex items-center gap-3 py-2.5 px-2 -mx-2 rounded-lg hover:bg-card-hover transition-colors">
                <StatusDot status={ins.status} />
                <span className="text-sm truncate flex-1">{ins.originalFileName}</span>
                {ins.forensicResult && <RiskPill level={ins.forensicResult.overallRiskLevel} />}
                <span className="text-xs text-muted shrink-0">{shortDate(ins.createdAt)}</span>
                <svg className="w-3.5 h-3.5 text-muted shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
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

// =========================================================================
// ANALYSES
// =========================================================================
const statusFilters = [
  { v: "", l: "Sve" }, { v: "Completed", l: "Zavrseno" }, { v: "Analyzing", l: "U analizi" }, { v: "Pending", l: "Cekanje" }, { v: "Failed", l: "Neuspjelo" },
] as const;

function AnalysesTab() {
  const [inspections, setInspections] = useState<Inspection[]>([]);
  const [loading, setLoading] = useState(true);
  const [status, setStatus] = useState("");
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(1);
  const ps = 20;

  const load = useCallback(async () => {
    try { setLoading(true); setInspections(await getInspections(page, ps, status || undefined)); }
    catch {} finally { setLoading(false); }
  }, [page, status]);

  useEffect(() => { load(); }, [load]);
  useEffect(() => { setPage(1); }, [status]);

  const filtered = inspections.filter((i) => {
    if (!search) return true;
    const q = search.toLowerCase();
    return i.originalFileName.toLowerCase().includes(q) || (i.ownerFullName?.toLowerCase().includes(q) ?? false);
  });

  return (
    <div>
      <div className="flex flex-wrap items-center gap-3 mb-4">
        <div className="flex bg-card border border-border rounded-xl p-0.5">
          {statusFilters.map((f) => (
            <button key={f.v} onClick={() => setStatus(f.v)}
              className={cn("px-3 py-1.5 rounded-lg text-xs font-medium transition-all", status === f.v ? "bg-accent text-white shadow-sm" : "text-muted hover:text-foreground")}>
              {f.l}
            </button>
          ))}
        </div>
        <input type="text" placeholder="Pretrazi..." value={search} onChange={(e) => setSearch(e.target.value)}
          className="px-3 py-2 rounded-xl border border-border bg-card text-sm placeholder:text-muted focus:outline-none focus:ring-2 focus:ring-accent/20 w-48" />
      </div>

      {loading ? <Spinner /> : (
        <>
          <div className="border border-border rounded-2xl overflow-hidden">
            <table className="w-full text-sm">
              <thead>
                <tr className="bg-card/60 border-b border-border text-muted text-xs uppercase tracking-wider">
                  <th className="text-left px-4 py-3 font-medium">Datoteka</th>
                  <th className="text-left px-4 py-3 font-medium hidden sm:table-cell">Korisnik</th>
                  <th className="text-center px-4 py-3 font-medium">Status</th>
                  <th className="text-center px-4 py-3 font-medium hidden md:table-cell">Rizik</th>
                  <th className="text-right px-4 py-3 font-medium hidden md:table-cell">Vrijeme</th>
                  <th className="text-right px-4 py-3 font-medium">Datum</th>
                </tr>
              </thead>
              <tbody>
                {filtered.map((i) => (
                  <tr key={i.id} className="border-b border-border last:border-0 hover:bg-card/80 transition-colors">
                    <td className="px-4 py-3">
                      <Link href={`/inspections/${i.id}`} className="text-accent hover:underline truncate block max-w-[220px]">{i.originalFileName}</Link>
                    </td>
                    <td className="px-4 py-3 text-muted hidden sm:table-cell truncate max-w-[150px]">{i.ownerFullName || "—"}</td>
                    <td className="px-4 py-3 text-center"><StatusPill status={i.status} /></td>
                    <td className="px-4 py-3 text-center hidden md:table-cell">{i.forensicResult ? <RiskPill level={i.forensicResult.overallRiskLevel} /> : <span className="text-muted">—</span>}</td>
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
              <PgBtn disabled={inspections.length < ps} onClick={() => setPage(page + 1)}>Sljedeca</PgBtn>
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
  if (loading || !stats) return <Spinner />;
  return (
    <div className="space-y-6">
      {stats.analysesPerDay.length > 0 && (
        <Card title="Analize po danu — 30 dana"><AreaChart data={stats.analysesPerDay} tall /></Card>
      )}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <Dist title="Razina rizika" data={stats.riskLevelDistribution} colorFn={riskColor} labelFn={riskLabel} />
        <Dist title="Verdikt" data={stats.verdictDistribution} colorFn={verdictColor} labelFn={verdictLabel} />
        <Dist title="Odluke sustava" data={stats.decisionOutcomeDistribution} colorFn={decisionColor} labelFn={decisionLabel} />
        <Dist title="Tipovi datoteka" data={stats.fileTypeDistribution} colorFn={() => "var(--color-accent-solid)"} labelFn={(k) => k.toUpperCase()} />
      </div>
    </div>
  );
}

// =========================================================================
// SHARED COMPONENTS
// =========================================================================

function Metric({ i, label, value, sub, accent, sparkline, pct, live, decimals, suffix }: {
  i: number; label: string; value: number; sub?: string; accent?: string; sparkline?: number[];
  pct?: number; live?: boolean; decimals?: number; suffix?: string;
}) {
  const d = useCountUp(value, true);
  return (
    <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.3, delay: i * 0.04 }}>
      <div className="bg-card border border-border rounded-2xl p-4 h-full relative overflow-hidden group hover:border-border/80 transition-colors">
        <div className="text-[11px] text-muted uppercase tracking-wider font-medium">{label}</div>
        <div className="flex items-end justify-between mt-1.5">
          <div>
            <span className={cn("text-2xl font-stat font-bold tabular-nums leading-none", accent)}>
              {decimals !== undefined ? d.toFixed(decimals) : Math.round(d)}{suffix || ""}
            </span>
            {pct !== undefined && pct > 0 && <span className="text-xs text-muted ml-1.5">{pct}%</span>}
          </div>
          {sparkline && sparkline.length > 2 && <Sparkline data={sparkline} />}
          {live && (
            <span className="relative flex h-2.5 w-2.5 mb-1">
              <span className="animate-ping absolute h-full w-full rounded-full bg-blue-400 opacity-50" />
              <span className="relative rounded-full h-2.5 w-2.5 bg-blue-500" />
            </span>
          )}
        </div>
        {sub && <div className="text-xs text-muted mt-1">{sub}</div>}
      </div>
    </motion.div>
  );
}

function Sparkline({ data }: { data: number[] }) {
  const w = 64, h = 24;
  const max = Math.max(...data, 1);
  const pts = data.map((v, i) => `${(i / (data.length - 1)) * w},${h - (v / max) * h}`).join(" ");
  const area = `0,${h} ${pts} ${w},${h}`;
  return (
    <svg width={w} height={h} className="shrink-0 opacity-60 group-hover:opacity-100 transition-opacity">
      <defs>
        <linearGradient id="spark-fill" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="var(--color-accent-solid)" stopOpacity="0.3" />
          <stop offset="100%" stopColor="var(--color-accent-solid)" stopOpacity="0" />
        </linearGradient>
      </defs>
      <polygon points={area} fill="url(#spark-fill)" />
      <polyline points={pts} fill="none" stroke="var(--color-accent-solid)" strokeWidth="1.5" strokeLinejoin="round" strokeLinecap="round" />
    </svg>
  );
}

function AreaChart({ data, tall }: { data: { date: string; count: number }[]; tall?: boolean }) {
  const h = tall ? 200 : 140;
  const w = 600;
  const max = Math.max(...data.map((d) => d.count), 1);
  const pts = data.map((d, i) => ({ x: (i / (data.length - 1)) * w, y: h - (d.count / max) * (h - 16) - 8 }));
  const line = pts.map((p) => `${p.x},${p.y}`).join(" ");
  const area = `0,${h} ${line} ${w},${h}`;
  const [show, setShow] = useState(false);
  useEffect(() => { const t = setTimeout(() => setShow(true), 100); return () => clearTimeout(t); }, []);

  return (
    <div>
      <svg viewBox={`0 0 ${w} ${h}`} className="w-full" style={{ height: tall ? 200 : 140 }} preserveAspectRatio="none">
        <defs>
          <linearGradient id="area-g" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="var(--color-accent-solid)" stopOpacity="0.25" />
            <stop offset="100%" stopColor="var(--color-accent-solid)" stopOpacity="0" />
          </linearGradient>
        </defs>
        {show && (
          <>
            <polygon points={area} fill="url(#area-g)" className="animate-[fadeIn_0.6s_ease-out]" />
            <polyline points={line} fill="none" stroke="var(--color-accent-solid)" strokeWidth="2" strokeLinejoin="round" strokeLinecap="round"
              className="animate-[fadeIn_0.6s_ease-out]" />
          </>
        )}
        {/* Grid lines */}
        {[0.25, 0.5, 0.75].map((p) => (
          <line key={p} x1={0} y1={h - p * (h - 16) - 8} x2={w} y2={h - p * (h - 16) - 8} stroke="currentColor" strokeOpacity="0.06" />
        ))}
      </svg>
      <div className="flex justify-between text-[10px] text-muted mt-1">
        {data.length > 0 && <span>{data[0].date.slice(5)}</span>}
        {data.length > 14 && <span>{data[Math.floor(data.length / 2)].date.slice(5)}</span>}
        {data.length > 1 && <span>{data[data.length - 1].date.slice(5)}</span>}
      </div>
    </div>
  );
}

function Dist({ title, data, colorFn, labelFn }: {
  title: string; data: Record<string, number>; colorFn: (k: string) => string; labelFn: (k: string) => string;
}) {
  const entries = Object.entries(data).sort((a, b) => b[1] - a[1]);
  const total = entries.reduce((s, [, c]) => s + c, 0);
  return (
    <Card title={title}>
      {entries.length === 0 ? <p className="text-sm text-muted py-4 text-center">Nema podataka</p> : (
        <div className="space-y-3.5">
          {entries.map(([key, count], i) => {
            const pct = total > 0 ? (count / total) * 100 : 0;
            return (
              <div key={key}>
                <div className="flex items-center justify-between text-sm mb-1">
                  <span>{labelFn(key)}</span>
                  <span className="text-muted font-mono tabular-nums text-xs">{count} <span className="text-muted/60">({pct.toFixed(0)}%)</span></span>
                </div>
                <div className="h-1.5 bg-border/20 rounded-full overflow-hidden">
                  <motion.div className="h-full rounded-full"
                    initial={{ width: 0 }} animate={{ width: `${pct}%` }}
                    transition={{ duration: 0.6, delay: 0.05 + i * 0.06 }}
                    style={{ backgroundColor: colorFn(key) }} />
                </div>
              </div>
            );
          })}
        </div>
      )}
    </Card>
  );
}

function Card({ title, children, delay = 0 }: { title?: string; children: React.ReactNode; delay?: number }) {
  return (
    <motion.div initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} transition={{ delay, duration: 0.25 }}>
      <div className="bg-card border border-border rounded-2xl p-5">
        {title && <h3 className="text-[11px] text-muted uppercase tracking-wider font-medium mb-4">{title}</h3>}
        {children}
      </div>
    </motion.div>
  );
}

function MiniCard({ label, value, bold }: { label: string; value: string; bold?: boolean }) {
  return (
    <div className="bg-card border border-border rounded-xl p-3">
      <div className="text-[10px] text-muted uppercase tracking-wider">{label}</div>
      <div className={cn("text-sm mt-0.5 truncate", bold ? "font-stat font-bold" : "font-medium")}>{value}</div>
    </div>
  );
}

function Pill({ color, children }: { color: "purple" | "green" | "red" | "default"; children: React.ReactNode }) {
  const styles = {
    purple: "bg-purple-500/10 text-purple-400 border-purple-500/20",
    green: "bg-emerald-500/10 text-emerald-400 border-emerald-500/20",
    red: "bg-red-500/10 text-red-400 border-red-500/20",
    default: "bg-card text-muted border-border",
  };
  return <span className={cn("inline-flex px-2 py-0.5 rounded-md text-[11px] font-medium border", styles[color])}>{children}</span>;
}

function StatusPill({ status }: { status: string }) {
  const m: Record<string, "green" | "red" | "purple" | "default"> = { Completed: "green", Failed: "red", Analyzing: "purple", Pending: "default" };
  const l: Record<string, string> = { Completed: "Zavrseno", Analyzing: "U analizi", Pending: "Cekanje", Failed: "Neuspjelo" };
  return <Pill color={m[status] || "default"}>{l[status] || status}</Pill>;
}

function StatusDot({ status }: { status: string }) {
  const c: Record<string, string> = { Completed: "bg-emerald-500", Analyzing: "bg-blue-500", Pending: "bg-amber-500", Failed: "bg-red-500" };
  return <div className={cn("w-2 h-2 rounded-full shrink-0", c[status] || "bg-muted")} />;
}

function RiskPill({ level }: { level: string }) {
  const c: Record<string, string> = { Low: "text-emerald-400", Medium: "text-amber-400", High: "text-orange-400", Critical: "text-red-400" };
  const l: Record<string, string> = { Low: "Nizak", Medium: "Srednji", High: "Visok", Critical: "Kritican" };
  return <span className={cn("text-[11px] font-medium", c[level] || "text-muted")}>{l[level] || level}</span>;
}

function PgBtn({ children, ...p }: React.ButtonHTMLAttributes<HTMLButtonElement>) {
  return <button {...p} className="px-3 py-1.5 rounded-lg text-xs font-medium border border-border text-muted hover:text-foreground hover:bg-card disabled:opacity-25 disabled:cursor-not-allowed transition-colors">{children}</button>;
}

function Spinner() {
  return <div className="flex justify-center py-16"><div className="w-6 h-6 border-2 border-accent border-t-transparent rounded-full animate-spin" /></div>;
}

// =========================================================================
// HELPERS
// =========================================================================
function shortDate(d: string) { return formatDate(d).split(" ")[0]; }
function riskColor(l: string) { return ({ Low: "#22c55e", Medium: "#f59e0b", High: "#f97316", Critical: "#ef4444" })[l] || "#71717a"; }
function riskLabel(l: string) { return ({ Low: "Nizak", Medium: "Srednji", High: "Visok", Critical: "Kritican" })[l] || l; }
function verdictColor(v: string) { return ({ authentic: "#22c55e", ai_generated: "#a855f7", tampered: "#ef4444" })[v] || "#71717a"; }
function verdictLabel(v: string) { return ({ authentic: "Autenticno", ai_generated: "AI generirano", tampered: "Manipulirano" })[v] || v; }
function decisionColor(o: string) { return ({ AutoApprove: "#22c55e", HumanReview: "#f59e0b", Escalate: "#ef4444" })[o] || "#71717a"; }
function decisionLabel(o: string) { return ({ AutoApprove: "Autenticno", HumanReview: "Pregled", Escalate: "Eskalacija" })[o] || o; }
