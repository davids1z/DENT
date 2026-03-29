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
function useCountUp(target: number, enabled: boolean, duration = 1000) {
  const [current, setCurrent] = useState(0);
  useEffect(() => {
    if (!enabled) { setCurrent(0); return; }
    const start = performance.now();
    let raf: number;
    function tick(now: number) {
      const elapsed = now - start;
      const progress = Math.min(elapsed / duration, 1);
      setCurrent((1 - Math.pow(1 - progress, 3)) * target);
      if (progress < 1) raf = requestAnimationFrame(tick);
    }
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [target, enabled, duration]);
  return current;
}

// ---------------------------------------------------------------------------
// Tabs
// ---------------------------------------------------------------------------
const tabs = [
  { id: "pregled", label: "Pregled" },
  { id: "korisnici", label: "Korisnici" },
  { id: "analize", label: "Analize" },
  { id: "statistika", label: "Statistika" },
] as const;
type TabId = (typeof tabs)[number]["id"];

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------
export default function AdminPage() {
  const { user, isLoading: authLoading } = useAuth();
  const router = useRouter();
  const [activeTab, setActiveTab] = useState<TabId>("pregled");
  const [adminStats, setAdminStats] = useState<AdminStats | null>(null);
  const [statsLoading, setStatsLoading] = useState(true);

  useEffect(() => {
    if (authLoading) return;
    if (!user || user.role !== "Admin") { router.replace("/"); return; }
    loadStats();
  }, [user, authLoading, router]);

  async function loadStats() {
    try {
      setStatsLoading(true);
      setAdminStats(await getAdminStats());
    } catch { /* ignore */ } finally { setStatsLoading(false); }
  }

  if (authLoading || !user || user.role !== "Admin") {
    return (
      <div className="min-h-[60dvh] flex items-center justify-center">
        <div className="w-8 h-8 border-2 border-accent border-t-transparent rounded-full animate-spin" />
      </div>
    );
  }

  return (
    <div className="max-w-7xl mx-auto px-4 sm:px-6 py-8">
      <motion.div initial={{ opacity: 0, y: -6 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.25 }}>
        <h1 className="font-heading text-3xl font-extrabold tracking-tight">Admin panel</h1>
        <p className="text-muted mt-1">Upravljanje platformom, korisnicima i analizama</p>
      </motion.div>

      {/* Tabs */}
      <div className="flex gap-1 mt-6 mb-8 border-b border-border overflow-x-auto">
        {tabs.map((t) => (
          <button
            key={t.id}
            onClick={() => setActiveTab(t.id)}
            className={cn(
              "relative px-5 py-2.5 text-sm font-medium transition-colors whitespace-nowrap",
              activeTab === t.id ? "text-foreground" : "text-muted hover:text-foreground"
            )}
          >
            {t.label}
            {activeTab === t.id && (
              <motion.div
                className="absolute bottom-0 left-2 right-2 h-0.5 bg-accent rounded-full"
                layoutId="admin-tab"
                transition={{ type: "spring", stiffness: 500, damping: 35 }}
              />
            )}
          </button>
        ))}
      </div>

      <AnimatePresence mode="wait">
        <motion.div
          key={activeTab}
          initial={{ opacity: 0, y: 6 }}
          animate={{ opacity: 1, y: 0 }}
          exit={{ opacity: 0 }}
          transition={{ duration: 0.12 }}
        >
          {activeTab === "pregled" && <OverviewTab stats={adminStats} loading={statsLoading} />}
          {activeTab === "korisnici" && <UsersTab />}
          {activeTab === "analize" && <AnalysesTab />}
          {activeTab === "statistika" && <StatisticsTab stats={adminStats} loading={statsLoading} />}
        </motion.div>
      </AnimatePresence>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Overview
// ---------------------------------------------------------------------------
function OverviewTab({ stats, loading }: { stats: AdminStats | null; loading: boolean }) {
  if (loading || !stats) return <Loader />;

  const avgSec = stats.averageProcessingTimeMs / 1000;
  const timeColor = avgSec < 15 ? "#22c55e" : avgSec < 45 ? "#f59e0b" : "#ef4444";

  return (
    <div className="space-y-8">
      {/* KPI row */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <KPI i={0} label="Korisnici" value={stats.totalUsers} sub={`${stats.activeUsers} aktivnih`} accent="text-accent" />
        <KPI i={1} label="Ukupno analiza" value={stats.totalInspections} />
        <KPI i={2} label="Dovrseno" value={stats.completedInspections} accent="text-green-500" />
        <KPI i={3} label="Neuspjelo" value={stats.failedInspections} accent={stats.failedInspections > 0 ? "text-red-500" : undefined} />
      </div>

      {/* Secondary row */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <KPI i={0} label="Novi danas" value={stats.usersRegisteredToday} accent="text-blue-400" />
        <KPI i={1} label="Novi tjedan" value={stats.usersRegisteredThisWeek} accent="text-blue-400" />
        <KPI i={2} label="U analizi" value={stats.analyzingInspections} live={stats.analyzingInspections > 0} />
        <KPI i={3} label="Red cekanja" value={stats.queuePending} live={stats.queuePending > 0} sub={`${stats.queueActiveUsers} korisnika`} />
      </div>

      {/* Processing + Status */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.25 }}>
          <div className="bg-card border border-border rounded-2xl p-5 flex items-center gap-4">
            <Ring value={avgSec} max={60} color={timeColor} size={52} />
            <div>
              <div className="text-xs text-muted uppercase tracking-wider">Prosjecno vrijeme</div>
              <div className="text-xl font-stat font-bold mt-0.5"><Num value={avgSec} d={1} />s</div>
            </div>
          </div>
        </motion.div>
        <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.3 }}>
          <div className="bg-card border border-border rounded-2xl p-5 flex items-center gap-4">
            <div className="w-[52px] h-[52px] rounded-xl bg-green-500/10 flex items-center justify-center relative">
              <div className="w-3 h-3 rounded-full bg-green-400 z-10" />
              <div className="absolute w-3 h-3 rounded-full bg-green-400 animate-ping opacity-30" />
            </div>
            <div>
              <div className="text-xs text-muted uppercase tracking-wider">Sustav</div>
              <div className="text-xl font-stat font-bold text-green-500 mt-0.5">Aktivan</div>
            </div>
          </div>
        </motion.div>
      </div>

      {/* Chart */}
      {stats.analysesPerDay.length > 0 && (
        <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ delay: 0.35 }}>
          <Panel title="Analize — zadnjih 30 dana">
            <BarChart data={stats.analysesPerDay} />
          </Panel>
        </motion.div>
      )}

      {/* Recent failures */}
      {stats.recentFailures.length > 0 && (
        <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ delay: 0.4 }}>
          <Panel title="Nedavni neuspjesi">
            <div className="divide-y divide-border">
              {stats.recentFailures.slice(0, 5).map((f) => (
                <Link key={f.id} href={`/inspections/${f.id}`} className="flex items-center justify-between py-3 px-1 hover:bg-card-hover -mx-1 px-2 rounded-lg transition-colors">
                  <div className="flex items-center gap-3 min-w-0">
                    <div className="w-1.5 h-1.5 rounded-full bg-red-400 shrink-0" />
                    <div className="min-w-0">
                      <span className="text-sm font-medium truncate block">{f.originalFileName}</span>
                      <span className="text-xs text-muted">{f.userFullName || "—"}</span>
                    </div>
                  </div>
                  <span className="text-xs text-muted shrink-0 ml-3">{formatDate(f.createdAt)}</span>
                </Link>
              ))}
            </div>
          </Panel>
        </motion.div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Users (expandable cards)
// ---------------------------------------------------------------------------
function UsersTab() {
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");
  const [expanded, setExpanded] = useState<string | null>(null);

  useEffect(() => { loadUsers(); }, []);

  async function loadUsers() {
    try { setUsers(await getAdminUsers()); }
    catch { /* ignore */ }
    finally { setLoading(false); }
  }

  async function handleToggle(u: AdminUser) {
    try {
      u.isActive ? await deactivateUser(u.id) : await activateUser(u.id);
      await loadUsers();
    } catch { /* ignore */ }
  }

  const filtered = users.filter((u) => {
    if (!search) return true;
    const q = search.toLowerCase();
    return u.fullName.toLowerCase().includes(q) || u.email.toLowerCase().includes(q);
  });

  if (loading) return <Loader />;

  return (
    <div>
      <input
        type="text"
        placeholder="Pretrazi korisnike..."
        value={search}
        onChange={(e) => setSearch(e.target.value)}
        className="w-full max-w-sm px-4 py-2.5 rounded-xl border border-border bg-card text-sm placeholder:text-muted focus:outline-none focus:ring-2 focus:ring-accent/20 mb-5"
      />

      <div className="space-y-3">
        {filtered.map((u) => (
          <UserCard
            key={u.id}
            user={u}
            expanded={expanded === u.id}
            onToggleExpand={() => setExpanded(expanded === u.id ? null : u.id)}
            onToggleActive={() => handleToggle(u)}
          />
        ))}
        {filtered.length === 0 && <div className="py-12 text-center text-muted">Nema rezultata</div>}
      </div>
    </div>
  );
}

function UserCard({ user: u, expanded, onToggleExpand, onToggleActive }: {
  user: AdminUser; expanded: boolean; onToggleExpand: () => void; onToggleActive: () => void;
}) {
  const [inspections, setInspections] = useState<Inspection[] | null>(null);
  const [insLoading, setInsLoading] = useState(false);

  useEffect(() => {
    if (!expanded || inspections !== null) return;
    setInsLoading(true);
    // Fetch all inspections and filter by owner email client-side
    // (the API filters by UserId server-side for non-admins, but admin sees all)
    getInspections(1, 100).then((data) => {
      setInspections(data.filter((i) => i.ownerEmail === u.email));
    }).catch(() => setInspections([])).finally(() => setInsLoading(false));
  }, [expanded, inspections, u.email]);

  return (
    <div className="bg-card border border-border rounded-2xl overflow-hidden transition-colors">
      {/* Header row — clickable */}
      <button onClick={onToggleExpand} className="w-full flex items-center gap-4 p-4 text-left hover:bg-card-hover transition-colors">
        {/* Avatar */}
        <div className={cn(
          "w-10 h-10 rounded-full flex items-center justify-center text-sm font-bold shrink-0",
          u.role === "Admin" ? "bg-purple-500/15 text-purple-400" : "bg-accent/10 text-accent"
        )}>
          {u.fullName.charAt(0).toUpperCase()}
        </div>

        {/* Info */}
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <span className="font-medium truncate">{u.fullName}</span>
            {u.role === "Admin" && (
              <span className="px-1.5 py-0.5 rounded text-[10px] font-bold bg-purple-500/15 text-purple-400 uppercase">Admin</span>
            )}
            {!u.isActive && (
              <span className="px-1.5 py-0.5 rounded text-[10px] font-bold bg-red-500/15 text-red-400 uppercase">Neaktivan</span>
            )}
          </div>
          <div className="text-xs text-muted truncate">{u.email}</div>
        </div>

        {/* Stats */}
        <div className="hidden sm:flex items-center gap-6 text-xs text-muted shrink-0">
          <div className="text-center">
            <div className="font-stat font-bold text-lg text-foreground">{u.inspectionCount}</div>
            <div>analiza</div>
          </div>
          <div className="text-center hidden md:block">
            <div className="font-medium text-foreground">{formatDate(u.createdAt).split(" ")[0]}</div>
            <div>registriran</div>
          </div>
          <div className="text-center hidden lg:block">
            <div className="font-medium text-foreground">{u.lastLoginAt ? formatDate(u.lastLoginAt).split(" ")[0] : "—"}</div>
            <div>zadnja prijava</div>
          </div>
        </div>

        {/* Chevron */}
        <svg className={cn("w-4 h-4 text-muted transition-transform shrink-0", expanded && "rotate-180")}
          fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M19.5 8.25l-7.5 7.5-7.5-7.5" />
        </svg>
      </button>

      {/* Expanded detail */}
      <AnimatePresence>
        {expanded && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.2 }}
            className="overflow-hidden"
          >
            <div className="border-t border-border px-4 py-4 space-y-4">
              {/* Detail grid */}
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
                <DetailCell label="Email" value={u.email} />
                <DetailCell label="Uloga" value={u.role} />
                <DetailCell label="Registriran" value={formatDate(u.createdAt)} />
                <DetailCell label="Zadnja prijava" value={u.lastLoginAt ? formatDate(u.lastLoginAt) : "Nikad"} />
                <DetailCell label="Status" value={u.isActive ? "Aktivan" : "Neaktivan"} color={u.isActive ? "text-green-400" : "text-red-400"} />
                <DetailCell label="Ukupno analiza" value={String(u.inspectionCount)} />
              </div>

              {/* Action button */}
              {u.role !== "Admin" && (
                <button
                  onClick={(e) => { e.stopPropagation(); onToggleActive(); }}
                  className={cn(
                    "px-4 py-2 rounded-lg text-xs font-medium border transition-colors",
                    u.isActive
                      ? "border-red-500/20 text-red-400 hover:bg-red-500/10"
                      : "border-green-500/20 text-green-400 hover:bg-green-500/10"
                  )}
                >
                  {u.isActive ? "Deaktiviraj korisnika" : "Aktiviraj korisnika"}
                </button>
              )}

              {/* User's inspections */}
              {insLoading ? (
                <div className="flex items-center gap-2 text-xs text-muted py-2">
                  <div className="w-3 h-3 border border-accent border-t-transparent rounded-full animate-spin" />
                  Ucitavanje analiza...
                </div>
              ) : inspections && inspections.length > 0 ? (
                <div>
                  <div className="text-xs text-muted uppercase tracking-wider mb-2">Nedavne analize</div>
                  <div className="divide-y divide-border rounded-xl border border-border overflow-hidden">
                    {inspections.slice(0, 8).map((ins) => (
                      <Link key={ins.id} href={`/inspections/${ins.id}`}
                        className="flex items-center justify-between px-3 py-2.5 hover:bg-card-hover transition-colors text-sm">
                        <div className="flex items-center gap-3 min-w-0">
                          <Badge status={ins.status} />
                          <span className="truncate max-w-[200px]">{ins.originalFileName}</span>
                        </div>
                        <div className="flex items-center gap-3 shrink-0 ml-2">
                          {ins.forensicResult && (
                            <RiskDot level={ins.forensicResult.overallRiskLevel} />
                          )}
                          <span className="text-xs text-muted">{formatDate(ins.createdAt).split(" ")[0]}</span>
                        </div>
                      </Link>
                    ))}
                  </div>
                </div>
              ) : inspections ? (
                <div className="text-xs text-muted py-1">Nema analiza</div>
              ) : null}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

function DetailCell({ label, value, color }: { label: string; value: string; color?: string }) {
  return (
    <div>
      <div className="text-[10px] text-muted uppercase tracking-wider">{label}</div>
      <div className={cn("text-sm font-medium mt-0.5 truncate", color)}>{value}</div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Analyses
// ---------------------------------------------------------------------------
const statusFilters = [
  { value: "", label: "Sve" },
  { value: "Completed", label: "Zavrseno" },
  { value: "Analyzing", label: "U analizi" },
  { value: "Pending", label: "Cekanje" },
  { value: "Failed", label: "Neuspjelo" },
] as const;

function AnalysesTab() {
  const [inspections, setInspections] = useState<Inspection[]>([]);
  const [loading, setLoading] = useState(true);
  const [status, setStatus] = useState("");
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(1);
  const pageSize = 20;

  const load = useCallback(async () => {
    try { setLoading(true); setInspections(await getInspections(page, pageSize, status || undefined)); }
    catch { /* ignore */ }
    finally { setLoading(false); }
  }, [page, status]);

  useEffect(() => { load(); }, [load]);
  useEffect(() => { setPage(1); }, [status]);

  const filtered = inspections.filter((i) => {
    if (!search) return true;
    const q = search.toLowerCase();
    return i.originalFileName.toLowerCase().includes(q) || (i.ownerFullName?.toLowerCase().includes(q) ?? false) || (i.ownerEmail?.toLowerCase().includes(q) ?? false);
  });

  return (
    <div>
      <div className="flex flex-wrap items-center gap-3 mb-5">
        <div className="flex gap-1 bg-card border border-border rounded-xl p-1">
          {statusFilters.map((f) => (
            <button key={f.value} onClick={() => setStatus(f.value)}
              className={cn(
                "px-3 py-1.5 rounded-lg text-xs font-medium transition-colors",
                status === f.value ? "bg-accent text-white shadow-sm" : "text-muted hover:text-foreground"
              )}>
              {f.label}
            </button>
          ))}
        </div>
        <input type="text" placeholder="Pretrazi..." value={search} onChange={(e) => setSearch(e.target.value)}
          className="px-4 py-2 rounded-xl border border-border bg-card text-sm placeholder:text-muted focus:outline-none focus:ring-2 focus:ring-accent/20 w-52" />
      </div>

      {loading ? <Loader /> : (
        <>
          <div className="space-y-2">
            {filtered.map((i) => (
              <Link key={i.id} href={`/inspections/${i.id}`}
                className="flex items-center gap-4 bg-card border border-border rounded-xl px-4 py-3 hover:border-accent/30 transition-colors group">
                <Badge status={i.status} />
                <div className="flex-1 min-w-0">
                  <div className="text-sm font-medium truncate group-hover:text-accent transition-colors">{i.originalFileName}</div>
                  <div className="text-xs text-muted">{i.ownerFullName || "—"}</div>
                </div>
                {i.forensicResult && (
                  <div className="hidden sm:block"><RiskDot level={i.forensicResult.overallRiskLevel} withLabel /></div>
                )}
                <div className="hidden md:block text-xs text-muted font-mono shrink-0">
                  {i.completedAt ? `${((new Date(i.completedAt).getTime() - new Date(i.createdAt).getTime()) / 1000).toFixed(1)}s` : "—"}
                </div>
                <div className="text-xs text-muted shrink-0">{formatDate(i.createdAt).split(" ")[0]}</div>
              </Link>
            ))}
          </div>
          {filtered.length === 0 && <div className="py-12 text-center text-muted">Nema rezultata</div>}

          <div className="flex items-center justify-between mt-5">
            <span className="text-xs text-muted">Stranica {page}</span>
            <div className="flex gap-2">
              <PagBtn onClick={() => setPage(Math.max(1, page - 1))} disabled={page === 1}>Prethodna</PagBtn>
              <PagBtn onClick={() => setPage(page + 1)} disabled={inspections.length < pageSize}>Sljedeca</PagBtn>
            </div>
          </div>
        </>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Statistics
// ---------------------------------------------------------------------------
function StatisticsTab({ stats, loading }: { stats: AdminStats | null; loading: boolean }) {
  if (loading || !stats) return <Loader />;

  return (
    <div className="space-y-6">
      {stats.analysesPerDay.length > 0 && (
        <Panel title="Analize po danu — zadnjih 30 dana">
          <BarChart data={stats.analysesPerDay} tall />
        </Panel>
      )}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <DistPanel title="Razina rizika" data={stats.riskLevelDistribution} colorFn={riskColor} labelFn={riskLabel} />
        <DistPanel title="Verdikt" data={stats.verdictDistribution} colorFn={verdictColor} labelFn={verdictLabel} />
        <DistPanel title="Odluke sustava" data={stats.decisionOutcomeDistribution} colorFn={decisionColor} labelFn={decisionLabel} />
        <DistPanel title="Tipovi datoteka" data={stats.fileTypeDistribution} colorFn={() => "var(--color-accent-solid)"} labelFn={(k) => k.toUpperCase()} />
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Shared components
// ---------------------------------------------------------------------------

function KPI({ i, label, value, sub, accent, live }: {
  i: number; label: string; value: number; sub?: string; accent?: string; live?: boolean;
}) {
  const display = useCountUp(value, true);
  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.35, delay: i * 0.05 }}
    >
      <div className="bg-card border border-border rounded-2xl p-4 relative overflow-hidden">
        {live && (
          <div className="absolute top-3 right-3 flex items-center gap-1">
            <span className="relative flex h-2 w-2">
              <span className="animate-ping absolute h-full w-full rounded-full bg-blue-400 opacity-60" />
              <span className="relative rounded-full h-2 w-2 bg-blue-500" />
            </span>
          </div>
        )}
        <div className="text-[11px] text-muted uppercase tracking-wider">{label}</div>
        <div className={cn("text-3xl font-stat font-bold tabular-nums mt-1", accent)}>{Math.round(display)}</div>
        {sub && <div className="text-xs text-muted mt-1">{sub}</div>}
      </div>
    </motion.div>
  );
}

function Num({ value, d = 0 }: { value: number; d?: number }) {
  const display = useCountUp(value, true);
  return <>{display.toFixed(d)}</>;
}

function Ring({ value, max, color, size = 48 }: { value: number; max: number; color: string; size?: number }) {
  const s = 3;
  const r = (size - s) / 2;
  const c = 2 * Math.PI * r;
  return (
    <div className="shrink-0" style={{ width: size, height: size }}>
      <svg width={size} height={size} className="-rotate-90">
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="currentColor" strokeWidth={s} className="text-border opacity-20" />
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke={color} strokeWidth={s} strokeLinecap="round"
          strokeDasharray={c} strokeDashoffset={c * (1 - Math.min(value / max, 1))}
          style={{ transition: "stroke-dashoffset 1.2s cubic-bezier(.25,.46,.45,.94)", filter: `drop-shadow(0 0 3px ${color}50)` }}
        />
      </svg>
    </div>
  );
}

function BarChart({ data, tall }: { data: { date: string; count: number }[]; tall?: boolean }) {
  const max = Math.max(...data.map((d) => d.count), 1);
  const [go, setGo] = useState(false);
  useEffect(() => { const t = setTimeout(() => setGo(true), 80); return () => clearTimeout(t); }, []);

  return (
    <div>
      <div className={cn("flex items-end gap-px", tall ? "h-52" : "h-36")}>
        {data.map((d, i) => {
          const pct = Math.max((d.count / max) * 100, d.count > 0 ? 2 : 0);
          return (
            <div key={d.date} className="flex-1 group relative h-full">
              <motion.div
                className="absolute bottom-0 left-[1px] right-[1px] rounded-t-sm bg-accent/70 hover:bg-accent transition-colors"
                initial={{ height: 0 }}
                animate={go ? { height: `${pct}%` } : {}}
                transition={{ duration: 0.45, delay: i * 0.015 }}
              />
              <div className="absolute bottom-full left-1/2 -translate-x-1/2 mb-1 hidden group-hover:block z-10 pointer-events-none">
                <div className="bg-foreground text-background text-[10px] px-2 py-1 rounded shadow-lg whitespace-nowrap">
                  {d.date.slice(5)}: {d.count}
                </div>
              </div>
            </div>
          );
        })}
      </div>
      <div className="flex justify-between text-[10px] text-muted mt-2">
        {data.length > 0 && <span>{data[0].date.slice(5)}</span>}
        {data.length > 14 && <span>{data[Math.floor(data.length / 2)].date.slice(5)}</span>}
        {data.length > 1 && <span>{data[data.length - 1].date.slice(5)}</span>}
      </div>
    </div>
  );
}

function DistPanel({ title, data, colorFn, labelFn }: {
  title: string; data: Record<string, number>; colorFn: (k: string) => string; labelFn: (k: string) => string;
}) {
  const entries = Object.entries(data).sort((a, b) => b[1] - a[1]);
  const total = entries.reduce((s, [, c]) => s + c, 0);
  return (
    <Panel title={title}>
      {entries.length === 0 ? <div className="text-sm text-muted py-4 text-center">Nema podataka</div> : (
        <div className="space-y-3">
          {entries.map(([key, count], i) => {
            const pct = total > 0 ? (count / total) * 100 : 0;
            return (
              <div key={key} className="flex items-center gap-3">
                <div className="w-24 text-sm truncate">{labelFn(key)}</div>
                <div className="flex-1 h-1.5 bg-border/30 rounded-full overflow-hidden">
                  <motion.div className="h-full rounded-full"
                    initial={{ width: 0 }} animate={{ width: `${pct}%` }}
                    transition={{ duration: 0.6, delay: 0.1 + i * 0.06 }}
                    style={{ backgroundColor: colorFn(key) }}
                  />
                </div>
                <div className="text-xs text-muted w-8 text-right font-mono tabular-nums">{count}</div>
              </div>
            );
          })}
        </div>
      )}
    </Panel>
  );
}

function Panel({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="bg-card border border-border rounded-2xl p-5">
      <h3 className="text-[11px] text-muted uppercase tracking-wider font-medium mb-4">{title}</h3>
      {children}
    </div>
  );
}

function Badge({ status }: { status: string }) {
  const colors: Record<string, string> = {
    Completed: "bg-green-500", Analyzing: "bg-blue-500", Pending: "bg-amber-500", Failed: "bg-red-500",
  };
  return <div className={cn("w-2 h-2 rounded-full shrink-0", colors[status] || "bg-muted")} />;
}

function RiskDot({ level, withLabel }: { level: string; withLabel?: boolean }) {
  const colors: Record<string, string> = {
    Low: "bg-green-500", Medium: "bg-amber-500", High: "bg-orange-500", Critical: "bg-red-500",
  };
  const labels: Record<string, string> = { Low: "Nizak", Medium: "Srednji", High: "Visok", Critical: "Kritican" };
  return (
    <div className="flex items-center gap-1.5">
      <div className={cn("w-2 h-2 rounded-full", colors[level] || "bg-muted")} />
      {withLabel && <span className="text-xs text-muted">{labels[level] || level}</span>}
    </div>
  );
}

function PagBtn({ children, ...props }: React.ButtonHTMLAttributes<HTMLButtonElement>) {
  return (
    <button {...props}
      className="px-3 py-1.5 rounded-lg text-xs font-medium border border-border text-muted hover:text-foreground hover:bg-card disabled:opacity-30 disabled:cursor-not-allowed transition-colors">
      {children}
    </button>
  );
}

function Loader() {
  return (
    <div className="flex items-center justify-center py-16">
      <div className="w-6 h-6 border-2 border-accent border-t-transparent rounded-full animate-spin" />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------
function riskColor(l: string) { return ({ Low: "#22c55e", Medium: "#f59e0b", High: "#f97316", Critical: "#ef4444" })[l] || "#71717a"; }
function riskLabel(l: string) { return ({ Low: "Nizak", Medium: "Srednji", High: "Visok", Critical: "Kritican" })[l] || l; }
function verdictColor(v: string) { return ({ authentic: "#22c55e", ai_generated: "#a855f7", tampered: "#ef4444" })[v] || "#71717a"; }
function verdictLabel(v: string) { return ({ authentic: "Autenticno", ai_generated: "AI generirano", tampered: "Manipulirano" })[v] || v; }
function decisionColor(o: string) { return ({ AutoApprove: "#22c55e", HumanReview: "#f59e0b", Escalate: "#ef4444" })[o] || "#71717a"; }
function decisionLabel(o: string) { return ({ AutoApprove: "Autenticno", HumanReview: "Pregled", Escalate: "Eskalacija" })[o] || o; }
