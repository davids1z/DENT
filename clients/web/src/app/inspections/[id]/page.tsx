"use client";

import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { getInspection, deleteInspection, formatDate, type Inspection } from "@/lib/api";
import { DamageReport } from "@/components/DamageReport";

export default function InspectionDetailPage() {
  const params = useParams();
  const router = useRouter();
  const [inspection, setInspection] = useState<Inspection | null>(null);
  const [loading, setLoading] = useState(true);
  const [deleting, setDeleting] = useState(false);

  useEffect(() => {
    if (params.id) {
      getInspection(params.id as string)
        .then(setInspection)
        .catch(() => router.push("/inspections"))
        .finally(() => setLoading(false));
    }
  }, [params.id, router]);

  const handleDelete = async () => {
    if (!inspection || !confirm("Jeste li sigurni da zelite obrisati ovu inspekciju?")) return;
    setDeleting(true);
    try {
      await deleteInspection(inspection.id);
      router.push("/inspections");
    } catch {
      setDeleting(false);
    }
  };

  if (loading) {
    return (
      <div className="max-w-7xl mx-auto px-6 py-8">
        <div className="h-8 w-48 skeleton rounded-lg mb-4" />
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          <div className="h-96 skeleton rounded-2xl" />
          <div className="space-y-4">
            <div className="h-32 skeleton rounded-2xl" />
            <div className="h-24 skeleton rounded-2xl" />
            <div className="h-48 skeleton rounded-2xl" />
          </div>
        </div>
      </div>
    );
  }

  if (!inspection) return null;

  return (
    <div className="max-w-7xl mx-auto px-6 py-8">
      {/* Header */}
      <div className="flex items-center justify-between mb-8">
        <div>
          <button
            onClick={() => router.back()}
            className="text-muted hover:text-foreground text-sm mb-2 flex items-center gap-1 transition-colors"
          >
            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
            </svg>
            Natrag
          </button>
          <h1 className="text-3xl font-bold">
            {inspection.vehicleMake && inspection.vehicleModel
              ? `${inspection.vehicleMake} ${inspection.vehicleModel}`
              : "Inspekcija"}
          </h1>
          <p className="text-muted text-sm mt-1">{formatDate(inspection.createdAt)}</p>
        </div>
        <button
          onClick={handleDelete}
          disabled={deleting}
          className="px-4 py-2 bg-red-500/10 text-red-400 border border-red-500/20 rounded-lg text-sm hover:bg-red-500/20 transition-colors disabled:opacity-50"
        >
          {deleting ? "Brisanje..." : "Obrisi"}
        </button>
      </div>

      {/* Content */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Image */}
        <div className="space-y-4">
          <div className="bg-card rounded-2xl border border-border overflow-hidden">
            <img
              src={inspection.imageUrl}
              alt="Vehicle damage"
              className="w-full h-auto max-h-[600px] object-contain bg-black"
            />
          </div>
          <div className="bg-card rounded-2xl border border-border p-4">
            <div className="text-xs text-muted">
              <span>Datoteka: {inspection.originalFileName}</span>
              <span className="mx-2">|</span>
              <span>ID: {inspection.id.slice(0, 8)}...</span>
            </div>
          </div>
        </div>

        {/* Report */}
        <DamageReport inspection={inspection} />
      </div>
    </div>
  );
}
