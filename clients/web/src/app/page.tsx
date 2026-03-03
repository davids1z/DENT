"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { getDashboardStats, type DashboardStats as Stats } from "@/lib/api";
import { DashboardStats } from "@/components/DashboardStats";
import { InspectionCard } from "@/components/InspectionCard";

export default function Dashboard() {
  const [stats, setStats] = useState<Stats | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getDashboardStats()
      .then(setStats)
      .catch((e) => setError(e.message));
  }, []);

  return (
    <div className="max-w-7xl mx-auto px-6 py-8">
      {/* Hero */}
      <div className="mb-10">
        <h1 className="text-3xl font-bold mb-2">Dashboard</h1>
        <p className="text-muted">Pregled svih inspekcija i statistika</p>
      </div>

      {error ? (
        <div className="bg-card rounded-2xl border border-border p-12 text-center">
          <div className="w-16 h-16 rounded-2xl bg-accent/10 flex items-center justify-center mx-auto mb-4">
            <svg className="w-8 h-8 text-accent" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M3 16.5v2.25A2.25 2.25 0 005.25 21h13.5A2.25 2.25 0 0021 18.75V16.5m-13.5-9L12 3m0 0l4.5 4.5M12 3v13.5" />
            </svg>
          </div>
          <h2 className="text-xl font-semibold mb-2">Dobrodosli u DENT</h2>
          <p className="text-muted mb-6 max-w-md mx-auto">
            AI alat za analizu steta na vozilima. Uploadajte sliku ostecenja i dobijte detaljan izvjestaj s procjenom troskova.
          </p>
          <Link
            href="/inspect"
            className="inline-flex items-center gap-2 px-6 py-3 bg-accent hover:bg-accent-hover text-white rounded-xl font-medium transition-colors"
          >
            Nova inspekcija
            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 7l5 5m0 0l-5 5m5-5H6" />
            </svg>
          </Link>
        </div>
      ) : !stats ? (
        <div className="space-y-4">
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
            {[...Array(4)].map((_, i) => (
              <div key={i} className="h-28 rounded-2xl skeleton" />
            ))}
          </div>
          <div className="h-48 rounded-2xl skeleton" />
        </div>
      ) : (
        <>
          <DashboardStats stats={stats} />

          {stats.recentInspections.length > 0 && (
            <div className="mt-8">
              <div className="flex items-center justify-between mb-4">
                <h2 className="text-sm font-medium text-muted uppercase tracking-wider">
                  Zadnje inspekcije
                </h2>
                <Link href="/inspections" className="text-sm text-accent hover:text-accent-hover transition-colors">
                  Vidi sve
                </Link>
              </div>
              <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
                {stats.recentInspections.map((inspection) => (
                  <InspectionCard key={inspection.id} inspection={inspection} />
                ))}
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
}
