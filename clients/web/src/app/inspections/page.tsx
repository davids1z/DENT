"use client";

import { useEffect, useState, useMemo } from "react";
import { getInspections, type Inspection, formatCurrency, formatDate, severityColor, severityLabel } from "@/lib/api";
import { InspectionCard } from "@/components/InspectionCard";
import { SearchBar } from "@/components/ui/SearchBar";
import { Skeleton } from "@/components/ui/Skeleton";
import { cn } from "@/lib/cn";
import Link from "next/link";

const PAGE_SIZE = 15;

// Simple in-memory cache so back navigation is instant
let _cachedInspections: Inspection[] | null = null;
let _cacheTimestamp = 0;
const CACHE_TTL_MS = 30_000; // 30s stale-while-revalidate

export default function InspectionsPage() {
  const hasCachedData = _cachedInspections !== null && (Date.now() - _cacheTimestamp) < CACHE_TTL_MS * 10;
  const [inspections, setInspections] = useState<Inspection[]>(_cachedInspections ?? []);
  const [loading, setLoading] = useState(!hasCachedData);
  const [filter, setFilter] = useState<string>("");
  const [search, setSearch] = useState("");
  const [view, setView] = useState<"grid" | "table">("grid");
  const [page, setPage] = useState(1);

  useEffect(() => {
    // Show cached data immediately, fetch fresh in background
    const isFresh = _cachedInspections && (Date.now() - _cacheTimestamp) < CACHE_TTL_MS;
    if (!isFresh) {
      if (!_cachedInspections) setLoading(true);
      setPage(1);
      getInspections(1, 200, filter || undefined)
        .then((data) => {
          setInspections(data);
          _cachedInspections = data;
          _cacheTimestamp = Date.now();
        })
        .catch(() => setInspections([]))
        .finally(() => setLoading(false));
    }
  }, [filter]);

  const filtered = useMemo(() => {
    if (!search.trim()) return inspections;
    const q = search.toLowerCase();
    return inspections.filter(
      (i) =>
        i.originalFileName.toLowerCase().includes(q) ||
        (i.vehicleMake && i.vehicleMake.toLowerCase().includes(q)) ||
        (i.vehicleModel && i.vehicleModel.toLowerCase().includes(q))
    );
  }, [inspections, search]);

  const totalPages = Math.ceil(filtered.length / PAGE_SIZE);
  const paginatedItems = filtered.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE);

  // Reset page when search changes
  useEffect(() => { setPage(1); }, [search]);

  const filters = [
    { value: "", label: "Sve" },
    { value: "Completed", label: "Završeno" },
    { value: "Analyzing", label: "U obradi" },
    { value: "Failed", label: "Neuspjelo" },
  ];

  return (
    <div className="max-w-7xl mx-auto px-4 sm:px-6 py-8">
      <div className="flex items-center justify-between mb-8">
        <div>
          <h1 className="font-heading text-2xl font-bold mb-1">Analize</h1>
          <p className="text-muted text-sm">Pregled svih forenzičkih analiza</p>
        </div>
      </div>

      <div className="flex flex-col sm:flex-row gap-3 mb-6">
        <div className="flex-1"><SearchBar value={search} onChange={setSearch} placeholder="Pretraži po datoteci..." /></div>
        <div className="hidden lg:flex items-center gap-1 bg-card border border-border rounded-lg p-1">
          <button onClick={() => setView("grid")} className={cn("p-2 rounded-md transition-colors", view === "grid" ? "bg-accent/10 text-accent" : "text-muted hover:text-foreground")}>
            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}><path strokeLinecap="round" strokeLinejoin="round" d="M3.75 6A2.25 2.25 0 016 3.75h2.25A2.25 2.25 0 0110.5 6v2.25a2.25 2.25 0 01-2.25 2.25H6a2.25 2.25 0 01-2.25-2.25V6zM3.75 15.75A2.25 2.25 0 016 13.5h2.25a2.25 2.25 0 012.25 2.25V18a2.25 2.25 0 01-2.25 2.25H6A2.25 2.25 0 013.75 18v-2.25zM13.5 6a2.25 2.25 0 012.25-2.25H18A2.25 2.25 0 0120.25 6v2.25A2.25 2.25 0 0118 10.5h-2.25a2.25 2.25 0 01-2.25-2.25V6zM13.5 15.75a2.25 2.25 0 012.25-2.25H18a2.25 2.25 0 012.25 2.25V18A2.25 2.25 0 0118 20.25h-2.25a2.25 2.25 0 01-2.25-2.25v-2.25z" /></svg>
          </button>
          <button onClick={() => setView("table")} className={cn("p-2 rounded-md transition-colors", view === "table" ? "bg-accent/10 text-accent" : "text-muted hover:text-foreground")}>
            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}><path strokeLinecap="round" strokeLinejoin="round" d="M8.25 6.75h12M8.25 12h12m-12 5.25h12M3.75 6.75h.007v.008H3.75V6.75zm.375 0a.375.375 0 11-.75 0 .375.375 0 01.75 0zM3.75 12h.007v.008H3.75V12zm.375 0a.375.375 0 11-.75 0 .375.375 0 01.75 0zm-.375 5.25h.007v.008H3.75v-.008zm.375 0a.375.375 0 11-.75 0 .375.375 0 01.75 0z" /></svg>
          </button>
        </div>
      </div>

      <div className="flex gap-2 mb-6 overflow-x-auto pb-1">
        {filters.map((f) => (
          <button key={f.value} onClick={() => setFilter(f.value)} className={cn(
            "px-4 py-2 rounded-lg text-sm font-medium transition-colors whitespace-nowrap",
            filter === f.value ? "bg-accent text-white" : "bg-card border border-border text-muted hover:text-foreground"
          )}>{f.label}</button>
        ))}
      </div>

      {loading ? (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {[...Array(6)].map((_, i) => <Skeleton key={i} variant="card" className="h-72" />)}
        </div>
      ) : filtered.length === 0 ? (
        <div className="bg-card border border-border rounded-xl p-12 text-center">
          <p className="text-muted">{search ? `Nema rezultata za "${search}"` : "Nema inspekcija"}</p>
        </div>
      ) : view === "table" ? (
        <div className="bg-card border border-border rounded-xl overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border">
                <th className="text-left px-4 py-3 text-xs text-muted uppercase tracking-wider font-medium">Datoteka</th>
                <th className="text-left px-4 py-3 text-xs text-muted uppercase tracking-wider font-medium">Status</th>
                <th className="text-left px-4 py-3 text-xs text-muted uppercase tracking-wider font-medium">Rizik</th>
                <th className="text-left px-4 py-3 text-xs text-muted uppercase tracking-wider font-medium">Nalazi</th>
                <th className="text-right px-4 py-3 text-xs text-muted uppercase tracking-wider font-medium">Rezultat</th>
                <th className="text-right px-4 py-3 text-xs text-muted uppercase tracking-wider font-medium">Datum</th>
              </tr>
            </thead>
            <tbody>
              {paginatedItems.map((i) => {
                const worst = i.damages.reduce((w, d) => {
                  const order = ["Minor", "Moderate", "Severe", "Critical"];
                  return order.indexOf(d.severity) > order.indexOf(w) ? d.severity : w;
                }, "Minor");
                return (
                  <tr key={i.id} className="border-b border-border hover:bg-card-hover transition-colors cursor-pointer">
                    <td className="px-4 py-3">
                      <Link href={`/inspections/${i.id}`} className="flex items-center gap-3">
                        <img src={i.imageUrl} alt="" className="w-10 h-10 rounded-lg object-cover bg-gray-100 flex-shrink-0" />
                        <span className="font-medium truncate">{i.originalFileName}</span>
                      </Link>
                    </td>
                    <td className="px-4 py-3">
                      <span className={cn("px-2 py-0.5 rounded-full text-xs font-medium",
                        i.status === "Completed" ? "bg-green-100 text-green-700" : i.status === "Failed" ? "bg-red-100 text-red-700" : "bg-amber-100 text-amber-700"
                      )}>{i.status === "Completed" ? "Završeno" : i.status === "Failed" ? "Greška" : "U obradi"}</span>
                    </td>
                    <td className="px-4 py-3">{i.damages.length > 0 && <span className={cn("text-xs font-medium", severityColor(worst))}>{severityLabel(worst)}</span>}</td>
                    <td className="px-4 py-3 text-muted">{i.damages.length}</td>
                    <td className="px-4 py-3 text-right">{i.totalEstimatedCostMin != null ? <span className="text-accent font-medium text-sm">{formatCurrency(i.totalEstimatedCostMin)}</span> : <span className="text-muted">-</span>}</td>
                    <td className="px-4 py-3 text-right text-muted text-xs">{formatDate(i.createdAt)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {paginatedItems.map((inspection) => <InspectionCard key={inspection.id} inspection={inspection} />)}
        </div>
      )}

      {/* Pagination */}
      {totalPages > 1 && (
        <div className="flex items-center justify-center gap-2 mt-8">
          <button
            onClick={() => setPage(Math.max(1, page - 1))}
            disabled={page === 1}
            className="px-3 py-2 rounded-lg text-sm font-medium border border-border bg-card hover:bg-card-hover disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
          >
            ←
          </button>
          {Array.from({ length: totalPages }, (_, i) => i + 1)
            .filter((p) => p === 1 || p === totalPages || Math.abs(p - page) <= 2)
            .map((p, idx, arr) => (
              <span key={p}>
                {idx > 0 && arr[idx - 1] !== p - 1 && (
                  <span className="text-muted px-1">…</span>
                )}
                <button
                  onClick={() => setPage(p)}
                  className={cn(
                    "w-9 h-9 rounded-lg text-sm font-medium transition-colors",
                    p === page ? "bg-accent text-white" : "border border-border bg-card hover:bg-card-hover"
                  )}
                >
                  {p}
                </button>
              </span>
            ))}
          <button
            onClick={() => setPage(Math.min(totalPages, page + 1))}
            disabled={page === totalPages}
            className="px-3 py-2 rounded-lg text-sm font-medium border border-border bg-card hover:bg-card-hover disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
          >
            →
          </button>
          <span className="text-xs text-muted ml-3">
            {filtered.length} {filtered.length === 1 ? "analiza" : "analiza"}
          </span>
        </div>
      )}
    </div>
  );
}
