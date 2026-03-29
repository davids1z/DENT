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
import { GlowCard } from "@/components/ui/GlowCard";
import { GlassPanel } from "@/components/ui/GlassPanel";

// ---------------------------------------------------------------------------
// Count-up hook (from VerdictDashboard pattern)
// ---------------------------------------------------------------------------
function useCountUp(target: number, enabled: boolean, duration = 1200) {
  const [current, setCurrent] = useState(0);
  useEffect(() => {
    if (!enabled) { setCurrent(0); return; }
    const start = performance.now();
    let raf: number;
    function tick(now: number) {
      const elapsed = now - start;
      const progress = Math.min(elapsed / duration, 1);
      const eased = 1 - Math.pow(1 - progress, 4);
      setCurrent(eased * target);
      if (progress < 1) raf = requestAnimationFrame(tick);
    }
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [target, enabled, duration]);
  return current;
}

// ---------------------------------------------------------------------------
// Tab system
// ---------------------------------------------------------------------------
const tabs = [
  { id: "pregled", label: "Pregled", icon: "M3 12l2-2m0 0l7-7 7 7M5 10v10a1 1 0 001 1h3m10-11l2 2m-2-2v10a1 1 0 01-1 1h-3m-4 0a1 1 0 01-1-1v-4a1 1 0 011-1h2a1 1 0 011 1v4a1 1 0 01-1 1" },
  { id: "korisnici", label: "Korisnici", icon: "M12 4.354a4 4 0 110 5.292M15 21H3v-1a6 6 0 0112 0v1zm0 0h6v-1a6 6 0 00-9-5.197m13.5-9a2.25 2.25 0 11-4.5 0 2.25 2.25 0 014.5 0z" },
  { id: "analize", label: "Analize", icon: "M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2" },
  { id: "statistika", label: "Statistika", icon: "M3 13.125C3 12.504 3.504 12 4.125 12h2.25c.621 0 1.125.504 1.125 1.125v6.75C7.5 20.496 6.996 21 6.375 21h-2.25A1.125 1.125 0 013 19.875v-6.75zM9.75 8.625c0-.621.504-1.125 1.125-1.125h2.25c.621 0 1.125.504 1.125 1.125v11.25c0 .621-.504 1.125-1.125 1.125h-2.25a1.125 1.125 0 01-1.125-1.125V8.625zM16.5 4.125c0-.621.504-1.125 1.125-1.125h2.25C20.496 3 21 3.504 21 4.125v15.75c0 .621-.504 1.125-1.125 1.125h-2.25a1.125 1.125 0 01-1.125-1.125V4.125z" },
] as const;

type TabId = (typeof tabs)[number]["id"];

// Motion variants
const cardEase = [0.25, 0.46, 0.45, 0.94] as const;
const cardVariants = {
  hidden: { opacity: 0, y: 16 },
  visible: (i: number) => ({
    opacity: 1,
    y: 0,
    transition: { duration: 0.4, delay: i * 0.06, ease: cardEase as unknown as [number, number, number, number] },
  }),
};

const tabContentVariants = {
  initial: { opacity: 0, y: 8 },
  animate: { opacity: 1, y: 0 },
  exit: { opacity: 0, y: -8 },
};

// ---------------------------------------------------------------------------
// Main page
// ---------------------------------------------------------------------------
export default function AdminPage() {
  const { user, isLoading: authLoading } = useAuth();
  const router = useRouter();
  const [activeTab, setActiveTab] = useState<TabId>("pregled");

  const [adminStats, setAdminStats] = useState<AdminStats | null>(null);
  const [statsLoading, setStatsLoading] = useState(true);

  useEffect(() => {
    if (authLoading) return;
    if (!user || user.role !== "Admin") {
      router.replace("/");
      return;
    }
    loadStats();
  }, [user, authLoading, router]);

  async function loadStats() {
    try {
      setStatsLoading(true);
      const data = await getAdminStats();
      setAdminStats(data);
    } catch {
      // ignore
    } finally {
      setStatsLoading(false);
    }
  }

  if (authLoading || !user || user.role !== "Admin") {
    return (
      <div className="min-h-[60dvh] flex items-center justify-center">
        <div className="w-8 h-8 border-2 border-accent border-t-transparent rounded-full animate-spin" />
      </div>
    );
  }

  return (
    <div className="max-w-7xl mx-auto px-4 sm:px-6 py-6">
      {/* Header */}
      <motion.div
        className="mb-6"
        initial={{ opacity: 0, y: -8 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.3 }}
      >
        <h1 className="font-heading text-2xl font-bold">Admin panel</h1>
        <p className="text-sm text-muted mt-1">
          Upravljanje platformom, korisnicima i analizama
        </p>
      </motion.div>

      {/* Tab navigation with sliding indicator */}
      <div className="flex gap-1 mb-6 border-b border-border pb-0 overflow-x-auto">
        {tabs.map((t) => (
          <button
            key={t.id}
            onClick={() => setActiveTab(t.id)}
            className={cn(
              "relative flex items-center gap-2 px-4 py-2.5 text-sm font-medium transition-colors -mb-px whitespace-nowrap",
              activeTab === t.id
                ? "text-accent"
                : "text-muted hover:text-foreground"
            )}
          >
            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
              <path strokeLinecap="round" strokeLinejoin="round" d={t.icon} />
            </svg>
            {t.label}
            {activeTab === t.id && (
              <motion.div
                className="absolute bottom-0 left-0 right-0 h-0.5 bg-accent"
                layoutId="admin-tab-indicator"
                transition={{ type: "spring", stiffness: 400, damping: 30 }}
              />
            )}
          </button>
        ))}
      </div>

      {/* Tab content with crossfade */}
      <AnimatePresence mode="wait">
        <motion.div
          key={activeTab}
          variants={tabContentVariants}
          initial="initial"
          animate="animate"
          exit="exit"
          transition={{ duration: 0.15 }}
        >
          {activeTab === "pregled" && (
            <OverviewTab stats={adminStats} loading={statsLoading} />
          )}
          {activeTab === "korisnici" && <UsersTab />}
          {activeTab === "analize" && <AnalysesTab />}
          {activeTab === "statistika" && (
            <StatisticsTab stats={adminStats} loading={statsLoading} />
          )}
        </motion.div>
      </AnimatePresence>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Overview Tab
// ---------------------------------------------------------------------------
function OverviewTab({ stats, loading }: { stats: AdminStats | null; loading: boolean }) {
  if (loading || !stats) {
    return <ShimmerGrid count={8} />;
  }

  const avgSeconds = stats.averageProcessingTimeMs / 1000;
  const timeColor = avgSeconds < 15 ? "#22c55e" : avgSeconds < 45 ? "#f59e0b" : "#ef4444";

  return (
    <div className="space-y-6">
      {/* Row 1: Primary metrics */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        {([
          { label: "Korisnici", value: stats.totalUsers, sub: `${stats.activeUsers} aktivnih`, icon: "M15 19.128a9.38 9.38 0 002.625.372 9.337 9.337 0 004.121-.952 4.125 4.125 0 00-7.533-2.493M15 19.128v-.003c0-1.113-.285-2.16-.786-3.07M15 19.128v.106A12.318 12.318 0 018.624 21c-2.331 0-4.512-.645-6.374-1.766l-.001-.109a6.375 6.375 0 0111.964-1.997M12 6.375a3.375 3.375 0 11-6.75 0 3.375 3.375 0 016.75 0zm8.25 2.25a2.625 2.625 0 11-5.25 0 2.625 2.625 0 015.25 0z" },
          { label: "Ukupno analiza", value: stats.totalInspections, icon: "M19.5 14.25v-2.625a3.375 3.375 0 00-3.375-3.375h-1.5A1.125 1.125 0 0113.5 7.125v-1.5a3.375 3.375 0 00-3.375-3.375H8.25m0 12.75h7.5m-7.5 3H12M10.5 2.25H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 00-9-9z" },
          { label: "Dovrseno", value: stats.completedInspections, color: "text-green-500" as const, icon: "M9 12.75L11.25 15 15 9.75M21 12a9 9 0 11-18 0 9 9 0 0118 0z" },
          { label: "U redu cekanja", value: stats.queuePending, sub: `${stats.queueActiveUsers} korisnika`, live: stats.queuePending > 0, icon: "M3.75 12h16.5m-16.5 3.75h16.5M3.75 19.5h16.5M5.625 4.5h12.75a1.875 1.875 0 010 3.75H5.625a1.875 1.875 0 010-3.75z" },
        ] as const).map((card, i) => (
          <motion.div key={card.label} custom={i} variants={cardVariants} initial="hidden" animate="visible">
            <StatCard {...card} />
          </motion.div>
        ))}
      </div>

      {/* Row 2: Secondary metrics */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        {([
          { label: "Novi danas", value: stats.usersRegisteredToday, color: "text-blue-500" as const },
          { label: "Novi tjedan", value: stats.usersRegisteredThisWeek, color: "text-blue-500" as const },
          { label: "U analizi", value: stats.analyzingInspections, dot: stats.analyzingInspections > 0 ? "bg-blue-400 animate-pulse" : undefined },
          { label: "Neuspjelo", value: stats.failedInspections, color: stats.failedInspections > 0 ? ("text-red-500" as const) : undefined },
        ]).map((card, i) => (
          <motion.div key={card.label} custom={i + 4} variants={cardVariants} initial="hidden" animate="visible">
            <StatCard {...card} />
          </motion.div>
        ))}
      </div>

      {/* Row 3: Processing ring + System status */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <motion.div custom={8} variants={cardVariants} initial="hidden" animate="visible">
          <GlowCard>
            <div className="flex items-center gap-4">
              <MiniRingGauge value={avgSeconds} maxValue={60} color={timeColor} />
              <div>
                <div className="text-xs text-muted uppercase tracking-wider">Prosjecno vrijeme obrade</div>
                <div className="text-lg font-stat font-bold mt-0.5">
                  <AnimatedNumber value={avgSeconds} decimals={1} suffix="s" />
                </div>
              </div>
            </div>
          </GlowCard>
        </motion.div>
        <motion.div custom={9} variants={cardVariants} initial="hidden" animate="visible">
          <GlowCard>
            <div className="flex items-center gap-4">
              <div className="w-12 h-12 rounded-xl bg-green-500/10 flex items-center justify-center relative">
                <div className="w-3 h-3 rounded-full bg-green-400 relative z-10" />
                <div className="absolute w-3 h-3 rounded-full bg-green-400 animate-ping opacity-40" />
              </div>
              <div>
                <div className="text-xs text-muted uppercase tracking-wider">Status sustava</div>
                <div className="text-lg font-stat font-bold text-green-500 mt-0.5">Aktivan</div>
              </div>
            </div>
          </GlowCard>
        </motion.div>
      </div>

      {/* Row 4: Recent failures */}
      {stats.recentFailures.length > 0 && (
        <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ delay: 0.5 }}>
          <GlassPanel>
            <h3 className="text-sm font-medium text-muted uppercase tracking-wider mb-3">
              Nedavni neuspjesi
            </h3>
            <div className="space-y-1">
              {stats.recentFailures.slice(0, 5).map((f, i) => (
                <motion.div
                  key={f.id}
                  initial={{ opacity: 0, x: -12 }}
                  animate={{ opacity: 1, x: 0 }}
                  transition={{ delay: 0.55 + i * 0.05, duration: 0.3 }}
                >
                  <Link
                    href={`/inspections/${f.id}`}
                    className="flex items-center justify-between p-2.5 rounded-lg hover:bg-card-hover transition-colors"
                  >
                    <div className="flex items-center gap-3 min-w-0">
                      <div className="w-2 h-2 rounded-full bg-red-400 shrink-0" />
                      <div className="min-w-0">
                        <div className="text-sm font-medium truncate">{f.originalFileName}</div>
                        <div className="text-xs text-muted truncate">
                          {f.userFullName || "Nepoznat"} &middot; {f.errorMessage?.slice(0, 60) || "Nepoznata greska"}
                        </div>
                      </div>
                    </div>
                    <div className="text-xs text-muted shrink-0 ml-3">
                      {formatDate(f.createdAt)}
                    </div>
                  </Link>
                </motion.div>
              ))}
            </div>
          </GlassPanel>
        </motion.div>
      )}

      {/* 30-day chart */}
      {stats.analysesPerDay.length > 0 && (
        <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ delay: 0.6 }}>
          <GlassPanel>
            <h3 className="text-sm font-medium text-muted uppercase tracking-wider mb-3">
              Analize zadnjih 30 dana
            </h3>
            <AnimatedBarChart data={stats.analysesPerDay} />
          </GlassPanel>
        </motion.div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Users Tab
// ---------------------------------------------------------------------------
function UsersTab() {
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");

  useEffect(() => {
    loadUsers();
  }, []);

  async function loadUsers() {
    try {
      const data = await getAdminUsers();
      setUsers(data);
    } catch {
      // ignore
    } finally {
      setLoading(false);
    }
  }

  async function handleToggle(u: AdminUser) {
    try {
      if (u.isActive) {
        await deactivateUser(u.id);
      } else {
        await activateUser(u.id);
      }
      await loadUsers();
    } catch {
      // ignore
    }
  }

  const filtered = users.filter((u) => {
    if (!search) return true;
    const q = search.toLowerCase();
    return u.fullName.toLowerCase().includes(q) || u.email.toLowerCase().includes(q);
  });

  if (loading) return <ShimmerGrid count={3} rows />;

  return (
    <div>
      <div className="mb-4">
        <input
          type="text"
          placeholder="Pretrazi korisnike..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="w-full max-w-sm px-3 py-2 rounded-lg border border-border bg-card text-sm placeholder:text-muted focus:outline-none focus:ring-2 focus:ring-accent/30"
        />
      </div>

      <div className="border border-border rounded-2xl overflow-hidden">
        <table className="w-full text-sm">
          <thead>
            <tr className="bg-card border-b border-border">
              <th className="text-left px-4 py-3 font-medium text-muted">Korisnik</th>
              <th className="text-left px-4 py-3 font-medium text-muted hidden sm:table-cell">Uloga</th>
              <th className="text-left px-4 py-3 font-medium text-muted hidden md:table-cell">Registriran</th>
              <th className="text-left px-4 py-3 font-medium text-muted hidden md:table-cell">Zadnja prijava</th>
              <th className="text-center px-4 py-3 font-medium text-muted">Analiza</th>
              <th className="text-center px-4 py-3 font-medium text-muted">Status</th>
              <th className="text-right px-4 py-3 font-medium text-muted">Akcija</th>
            </tr>
          </thead>
          <tbody>
            {filtered.map((u) => (
              <tr key={u.id} className="border-b border-border last:border-0 hover:bg-card/50 transition-colors">
                <td className="px-4 py-3">
                  <div className="font-medium">{u.fullName}</div>
                  <div className="text-xs text-muted">{u.email}</div>
                </td>
                <td className="px-4 py-3 hidden sm:table-cell">
                  <span className={cn(
                    "inline-flex px-2 py-0.5 rounded-md text-xs font-medium border",
                    u.role === "Admin"
                      ? "bg-purple-500/10 text-purple-400 border-purple-500/20"
                      : "bg-card text-muted border-border"
                  )}>
                    {u.role}
                  </span>
                </td>
                <td className="px-4 py-3 text-muted hidden md:table-cell">{formatDate(u.createdAt)}</td>
                <td className="px-4 py-3 text-muted hidden md:table-cell">{u.lastLoginAt ? formatDate(u.lastLoginAt) : "—"}</td>
                <td className="px-4 py-3 text-center">{u.inspectionCount}</td>
                <td className="px-4 py-3 text-center">
                  <span className={cn(
                    "inline-flex px-2 py-0.5 rounded-md text-xs font-medium border",
                    u.isActive
                      ? "bg-green-500/10 text-green-400 border-green-500/20"
                      : "bg-red-500/10 text-red-400 border-red-500/20"
                  )}>
                    {u.isActive ? "Aktivan" : "Neaktivan"}
                  </span>
                </td>
                <td className="px-4 py-3 text-right">
                  {u.role !== "Admin" && (
                    <button
                      onClick={() => handleToggle(u)}
                      className={cn(
                        "text-xs font-medium px-3 py-1.5 rounded-lg transition-colors",
                        u.isActive
                          ? "text-red-400 hover:bg-red-500/10"
                          : "text-green-400 hover:bg-green-500/10"
                      )}
                    >
                      {u.isActive ? "Deaktiviraj" : "Aktiviraj"}
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {filtered.length === 0 && (
          <div className="py-8 text-center text-sm text-muted">Nema rezultata</div>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Analyses Tab
// ---------------------------------------------------------------------------
const statusFilters = [
  { value: "", label: "Sve" },
  { value: "Completed", label: "Zavrseno" },
  { value: "Analyzing", label: "U analizi" },
  { value: "Pending", label: "Na cekanju" },
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
    try {
      setLoading(true);
      const data = await getInspections(page, pageSize, status || undefined);
      setInspections(data);
    } catch {
      // ignore
    } finally {
      setLoading(false);
    }
  }, [page, status]);

  useEffect(() => { load(); }, [load]);
  useEffect(() => { setPage(1); }, [status]);

  const filtered = inspections.filter((i) => {
    if (!search) return true;
    const q = search.toLowerCase();
    return (
      i.originalFileName.toLowerCase().includes(q) ||
      (i.ownerFullName?.toLowerCase().includes(q) ?? false) ||
      (i.ownerEmail?.toLowerCase().includes(q) ?? false)
    );
  });

  function getVerdict(i: Inspection): string {
    const probs = i.forensicResult?.verdictProbabilities;
    if (!probs) return "—";
    const entries = Object.entries(probs);
    if (entries.length === 0) return "—";
    const [winner] = entries.sort((a, b) => b[1] - a[1])[0];
    return verdictLabel(winner);
  }

  function getProcessingTime(i: Inspection): string {
    if (!i.completedAt) return "—";
    const ms = new Date(i.completedAt).getTime() - new Date(i.createdAt).getTime();
    return `${(ms / 1000).toFixed(1)}s`;
  }

  return (
    <div>
      <div className="flex flex-wrap items-center gap-3 mb-4">
        <div className="flex gap-1">
          {statusFilters.map((f) => (
            <button
              key={f.value}
              onClick={() => setStatus(f.value)}
              className={cn(
                "px-3 py-1.5 rounded-lg text-xs font-medium transition-colors",
                status === f.value
                  ? "bg-accent text-white"
                  : "text-muted hover:text-foreground hover:bg-card"
              )}
            >
              {f.label}
            </button>
          ))}
        </div>
        <input
          type="text"
          placeholder="Pretrazi..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="px-3 py-1.5 rounded-lg border border-border bg-card text-xs placeholder:text-muted focus:outline-none focus:ring-2 focus:ring-accent/30 w-48"
        />
      </div>

      {loading ? (
        <ShimmerGrid count={5} rows />
      ) : (
        <>
          <div className="border border-border rounded-2xl overflow-hidden overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="bg-card border-b border-border">
                  <th className="text-left px-4 py-3 font-medium text-muted">Korisnik</th>
                  <th className="text-left px-4 py-3 font-medium text-muted">Datoteka</th>
                  <th className="text-center px-4 py-3 font-medium text-muted">Status</th>
                  <th className="text-center px-4 py-3 font-medium text-muted hidden md:table-cell">Rizik</th>
                  <th className="text-center px-4 py-3 font-medium text-muted hidden lg:table-cell">Verdikt</th>
                  <th className="text-right px-4 py-3 font-medium text-muted hidden md:table-cell">Vrijeme</th>
                  <th className="text-right px-4 py-3 font-medium text-muted">Datum</th>
                </tr>
              </thead>
              <tbody>
                {filtered.map((i) => (
                  <tr key={i.id} className="border-b border-border last:border-0 hover:bg-card/50 transition-colors">
                    <td className="px-4 py-3">
                      <div className="text-sm">{i.ownerFullName || "—"}</div>
                      <div className="text-xs text-muted">{i.ownerEmail || ""}</div>
                    </td>
                    <td className="px-4 py-3">
                      <Link href={`/inspections/${i.id}`} className="text-accent hover:underline text-sm truncate block max-w-[200px]">
                        {i.originalFileName}
                      </Link>
                    </td>
                    <td className="px-4 py-3 text-center"><StatusBadge status={i.status} /></td>
                    <td className="px-4 py-3 text-center hidden md:table-cell"><RiskBadge level={i.forensicResult?.overallRiskLevel} /></td>
                    <td className="px-4 py-3 text-center hidden lg:table-cell text-xs">{getVerdict(i)}</td>
                    <td className="px-4 py-3 text-right text-muted text-xs hidden md:table-cell font-mono">{getProcessingTime(i)}</td>
                    <td className="px-4 py-3 text-right text-muted text-xs">{formatDate(i.createdAt)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            {filtered.length === 0 && (
              <div className="py-8 text-center text-sm text-muted">Nema rezultata</div>
            )}
          </div>

          <div className="flex items-center justify-between mt-4">
            <div className="text-xs text-muted">Stranica {page}</div>
            <div className="flex gap-2">
              <button onClick={() => setPage(Math.max(1, page - 1))} disabled={page === 1}
                className="px-3 py-1.5 rounded-lg text-xs font-medium border border-border text-muted hover:text-foreground hover:bg-card disabled:opacity-30 disabled:cursor-not-allowed transition-colors">
                Prethodna
              </button>
              <button onClick={() => setPage(page + 1)} disabled={inspections.length < pageSize}
                className="px-3 py-1.5 rounded-lg text-xs font-medium border border-border text-muted hover:text-foreground hover:bg-card disabled:opacity-30 disabled:cursor-not-allowed transition-colors">
                Sljedeca
              </button>
            </div>
          </div>
        </>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Statistics Tab
// ---------------------------------------------------------------------------
function StatisticsTab({ stats, loading }: { stats: AdminStats | null; loading: boolean }) {
  if (loading || !stats) {
    return <ShimmerGrid count={4} />;
  }

  return (
    <div className="space-y-6">
      {stats.analysesPerDay.length > 0 && (
        <GlassPanel>
          <h3 className="text-sm font-medium text-muted uppercase tracking-wider mb-4">
            Analize po danu (30 dana)
          </h3>
          <AnimatedBarChart data={stats.analysesPerDay} tall />
        </GlassPanel>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <AnimatedDistribution title="Razina rizika" data={stats.riskLevelDistribution} colorFn={riskColor} labelFn={riskLabel} />
        <AnimatedDistribution title="Verdikt" data={stats.verdictDistribution} colorFn={verdictColor} labelFn={verdictLabel} />
        <AnimatedDistribution title="Odluke sustava" data={stats.decisionOutcomeDistribution} colorFn={decisionColor} labelFn={decisionLabel} />
        <AnimatedDistribution title="Tipovi datoteka" data={stats.fileTypeDistribution} colorFn={() => "var(--color-accent-solid)"} labelFn={(k) => k.toUpperCase()} />
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Animated components
// ---------------------------------------------------------------------------

function AnimatedNumber({ value, decimals = 0, suffix = "" }: { value: number; decimals?: number; suffix?: string }) {
  const display = useCountUp(value, true, 1200);
  return <>{display.toFixed(decimals)}{suffix}</>;
}

function StatCard({
  label, value, sub, color, icon, dot, live,
}: {
  label: string; value: number; sub?: string; color?: string; icon?: string; dot?: string; live?: boolean;
}) {
  const display = useCountUp(value, true, 1200);

  return (
    <GlowCard>
      <div className="flex items-start justify-between">
        <div>
          <div className="text-xs text-muted uppercase tracking-wider mb-1.5">{label}</div>
          <div className={cn("text-2xl font-stat font-bold tabular-nums", color)}>
            {Math.round(display)}
          </div>
          {sub && <div className="text-xs text-muted mt-0.5">{sub}</div>}
        </div>
        <div className="flex items-center gap-2">
          {live && (
            <span className="flex items-center gap-1 px-1.5 py-0.5 rounded-full bg-red-500/10 border border-red-500/20">
              <span className="relative flex h-1.5 w-1.5">
                <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-red-400 opacity-75" />
                <span className="relative inline-flex rounded-full h-1.5 w-1.5 bg-red-500" />
              </span>
              <span className="text-[9px] font-bold text-red-400 uppercase tracking-wider">Live</span>
            </span>
          )}
          {dot && !live && <div className={cn("w-2 h-2 rounded-full", dot)} />}
          {icon && (
            <div className="w-8 h-8 rounded-lg bg-card-hover flex items-center justify-center">
              <svg className="w-4 h-4 text-muted" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
                <path strokeLinecap="round" strokeLinejoin="round" d={icon} />
              </svg>
            </div>
          )}
        </div>
      </div>
    </GlowCard>
  );
}

function MiniRingGauge({ value, maxValue, color }: { value: number; maxValue: number; color: string }) {
  const size = 48;
  const stroke = 3;
  const r = (size - stroke) / 2;
  const circumference = 2 * Math.PI * r;
  const pct = Math.min(value / maxValue, 1);
  const offset = circumference * (1 - pct);

  return (
    <div className="relative shrink-0" style={{ width: size, height: size }}>
      <svg width={size} height={size} className="-rotate-90" style={{ overflow: "visible" }}>
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="currentColor" strokeWidth={stroke} className="text-border opacity-30" />
        <circle
          cx={size / 2} cy={size / 2} r={r}
          fill="none" stroke={color} strokeWidth={stroke} strokeLinecap="round"
          strokeDasharray={circumference}
          strokeDashoffset={offset}
          style={{
            transition: "stroke-dashoffset 1.5s cubic-bezier(0.25, 0.46, 0.45, 0.94)",
            filter: `drop-shadow(0 0 4px ${color}40)`,
          }}
        />
      </svg>
    </div>
  );
}

function AnimatedBarChart({ data, tall }: { data: { date: string; count: number }[]; tall?: boolean }) {
  const maxCount = Math.max(...data.map((d) => d.count), 1);
  const [animate, setAnimate] = useState(false);

  useEffect(() => {
    const timer = setTimeout(() => setAnimate(true), 100);
    return () => clearTimeout(timer);
  }, []);

  return (
    <div>
      <div className={cn("flex items-end gap-[2px]", tall ? "h-48" : "h-32")}>
        {data.map((d, i) => {
          const heightPct = (d.count / maxCount) * 100;
          const targetH = Math.max(heightPct, d.count > 0 ? 3 : 0);
          return (
            <div key={d.date} className="flex-1 group relative" style={{ height: "100%" }}>
              <motion.div
                className="absolute bottom-0 left-0 right-0 rounded-t"
                initial={{ height: 0 }}
                animate={animate ? { height: `${targetH}%` } : {}}
                transition={{ duration: 0.5, delay: 0.2 + i * 0.018, ease: [0.25, 0.46, 0.45, 0.94] }}
                style={{
                  background: `linear-gradient(to top, var(--color-accent-solid) 0%, color-mix(in srgb, var(--color-accent-solid) 70%, white) 100%)`,
                }}
                whileHover={{ filter: "brightness(1.2)", transition: { duration: 0.15 } }}
              />
              <div className="absolute bottom-full left-1/2 -translate-x-1/2 mb-1 hidden group-hover:block z-10 pointer-events-none">
                <div className="bg-foreground text-background text-[10px] px-2 py-1 rounded whitespace-nowrap shadow-lg">
                  {d.date.slice(5)}: {d.count}
                </div>
              </div>
            </div>
          );
        })}
      </div>
      <div className="flex justify-between text-[10px] text-muted mt-2 px-0.5">
        {data.length > 0 && <span>{data[0].date.slice(5)}</span>}
        {data.length > 14 && <span>{data[Math.floor(data.length / 2)].date.slice(5)}</span>}
        {data.length > 1 && <span>{data[data.length - 1].date.slice(5)}</span>}
      </div>
    </div>
  );
}

function AnimatedDistribution({
  title, data, colorFn, labelFn,
}: {
  title: string; data: Record<string, number>; colorFn: (key: string) => string; labelFn: (key: string) => string;
}) {
  const entries = Object.entries(data).sort((a, b) => b[1] - a[1]);
  const total = entries.reduce((sum, [, c]) => sum + c, 0);

  if (entries.length === 0) {
    return (
      <GlassPanel>
        <h3 className="text-sm font-medium text-muted uppercase tracking-wider mb-4">{title}</h3>
        <div className="text-sm text-muted py-4 text-center">Nema podataka</div>
      </GlassPanel>
    );
  }

  return (
    <GlassPanel>
      <h3 className="text-sm font-medium text-muted uppercase tracking-wider mb-4">{title}</h3>
      <div className="space-y-3">
        {entries.map(([key, count], i) => {
          const pct = total > 0 ? (count / total) * 100 : 0;
          return (
            <div key={key} className="flex items-center gap-3">
              <div className="w-24 text-sm truncate">{labelFn(key)}</div>
              <div className="flex-1 h-2 bg-card-hover rounded-full overflow-hidden">
                <motion.div
                  className="h-full rounded-full"
                  initial={{ width: 0 }}
                  animate={{ width: `${pct}%` }}
                  transition={{ duration: 0.7, delay: 0.1 + i * 0.08, ease: [0.25, 0.46, 0.45, 0.94] }}
                  style={{ backgroundColor: colorFn(key) }}
                />
              </div>
              <div className="text-sm text-muted w-10 text-right font-mono tabular-nums">
                <AnimatedNumber value={count} />
              </div>
            </div>
          );
        })}
      </div>
    </GlassPanel>
  );
}

function StatusBadge({ status }: { status: string }) {
  const styles: Record<string, string> = {
    Completed: "bg-green-500/10 text-green-400 border-green-500/20",
    Analyzing: "bg-blue-500/10 text-blue-400 border-blue-500/20",
    Pending: "bg-amber-500/10 text-amber-400 border-amber-500/20",
    Failed: "bg-red-500/10 text-red-400 border-red-500/20",
  };
  const labels: Record<string, string> = {
    Completed: "Zavrseno", Analyzing: "U analizi", Pending: "Cekanje", Failed: "Neuspjelo",
  };
  return (
    <span className={cn("inline-flex px-2 py-0.5 rounded-md text-xs font-medium border", styles[status] || "bg-card text-muted border-border")}>
      {labels[status] || status}
    </span>
  );
}

function RiskBadge({ level }: { level?: string }) {
  if (!level) return <span className="text-xs text-muted">—</span>;
  const styles: Record<string, string> = {
    Low: "bg-green-500/10 text-green-400 border-green-500/20",
    Medium: "bg-amber-500/10 text-amber-400 border-amber-500/20",
    High: "bg-orange-500/10 text-orange-400 border-orange-500/20",
    Critical: "bg-red-500/10 text-red-400 border-red-500/20",
  };
  const labels: Record<string, string> = { Low: "Nizak", Medium: "Srednji", High: "Visok", Critical: "Kritican" };
  return (
    <span className={cn("inline-flex px-2 py-0.5 rounded-md text-xs font-medium border", styles[level] || "bg-card text-muted border-border")}>
      {labels[level] || level}
    </span>
  );
}

function ShimmerGrid({ count, rows }: { count: number; rows?: boolean }) {
  const shimmerStyle: React.CSSProperties = {
    backgroundImage: "linear-gradient(90deg, transparent 0%, var(--color-card-hover) 50%, transparent 100%)",
    backgroundSize: "200% 100%",
    animation: "shimmer 1.5s ease-in-out infinite",
  };

  if (rows) {
    return (
      <div className="space-y-3">
        {Array.from({ length: count }).map((_, i) => (
          <div key={i} className="h-14 rounded-xl overflow-hidden bg-card">
            <div className="h-full w-full" style={shimmerStyle} />
          </div>
        ))}
      </div>
    );
  }
  return (
    <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
      {Array.from({ length: count }).map((_, i) => (
        <div key={i} className="h-24 rounded-xl overflow-hidden bg-card">
          <div className="h-full w-full" style={shimmerStyle} />
        </div>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Label/color helpers
// ---------------------------------------------------------------------------

function riskColor(level: string): string {
  switch (level) {
    case "Low": return "#22c55e";
    case "Medium": return "#f59e0b";
    case "High": return "#f97316";
    case "Critical": return "#ef4444";
    default: return "#71717a";
  }
}

function riskLabel(level: string): string {
  const labels: Record<string, string> = { Low: "Nizak", Medium: "Srednji", High: "Visok", Critical: "Kritican" };
  return labels[level] || level;
}

function verdictColor(verdict: string): string {
  switch (verdict) {
    case "authentic": return "#22c55e";
    case "ai_generated": return "#a855f7";
    case "tampered": return "#ef4444";
    default: return "#71717a";
  }
}

function verdictLabel(verdict: string): string {
  const labels: Record<string, string> = { authentic: "Autenticno", ai_generated: "AI generirano", tampered: "Manipulirano" };
  return labels[verdict] || verdict;
}

function decisionColor(outcome: string): string {
  switch (outcome) {
    case "AutoApprove": return "#22c55e";
    case "HumanReview": return "#f59e0b";
    case "Escalate": return "#ef4444";
    default: return "#71717a";
  }
}

function decisionLabel(outcome: string): string {
  const labels: Record<string, string> = { AutoApprove: "Autenticno", HumanReview: "Pregled", Escalate: "Eskalacija" };
  return labels[outcome] || outcome;
}
