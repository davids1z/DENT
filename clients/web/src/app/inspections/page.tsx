"use client";

import { useEffect, useState } from "react";
import { getInspections, type Inspection } from "@/lib/api";
import { InspectionCard } from "@/components/InspectionCard";

export default function InspectionsPage() {
  const [inspections, setInspections] = useState<Inspection[]>([]);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState<string>("");

  useEffect(() => {
    setLoading(true);
    getInspections(1, 50, filter || undefined)
      .then(setInspections)
      .catch(() => setInspections([]))
      .finally(() => setLoading(false));
  }, [filter]);

  const filters = [
    { value: "", label: "Sve" },
    { value: "Completed", label: "Zavrseno" },
    { value: "Analyzing", label: "U obradi" },
    { value: "Failed", label: "Neuspjelo" },
  ];

  return (
    <div className="max-w-7xl mx-auto px-6 py-8">
      <div className="flex items-center justify-between mb-8">
        <div>
          <h1 className="text-3xl font-bold mb-2">Inspekcije</h1>
          <p className="text-muted">Pregled svih analiza ostecenja</p>
        </div>
      </div>

      {/* Filters */}
      <div className="flex gap-2 mb-6">
        {filters.map((f) => (
          <button
            key={f.value}
            onClick={() => setFilter(f.value)}
            className={`px-4 py-2 rounded-lg text-sm font-medium transition-all ${
              filter === f.value
                ? "bg-accent/10 text-accent border border-accent/20"
                : "bg-card border border-border text-muted hover:text-foreground hover:border-accent/30"
            }`}
          >
            {f.label}
          </button>
        ))}
      </div>

      {loading ? (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {[...Array(6)].map((_, i) => (
            <div key={i} className="h-72 rounded-2xl skeleton" />
          ))}
        </div>
      ) : inspections.length === 0 ? (
        <div className="bg-card rounded-2xl border border-border p-12 text-center">
          <p className="text-muted">Nema inspekcija</p>
        </div>
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {inspections.map((inspection) => (
            <InspectionCard key={inspection.id} inspection={inspection} />
          ))}
        </div>
      )}
    </div>
  );
}
