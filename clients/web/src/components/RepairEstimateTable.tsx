"use client";

import type { Inspection, RepairLineItem } from "@/lib/api";
import { formatCurrency, damageTypeLabel, carPartLabel, laborTypeLabel } from "@/lib/api";

interface RepairEstimateTableProps {
  inspection: Inspection;
}

export function RepairEstimateTable({ inspection }: RepairEstimateTableProps) {
  const groups = inspection.damages
    .filter((d) => d.repairLineItems && d.repairLineItems.length > 0)
    .map((d) => ({
      label: `${damageTypeLabel(d.damageType)} — ${carPartLabel(d.carPart)}`,
      items: d.repairLineItems,
    }));

  if (groups.length === 0) return null;

  const i = inspection;
  const hasStructuredTotals = i.laborTotal != null || i.partsTotal != null || i.materialsTotal != null;

  return (
    <div className="bg-card border border-border rounded-xl overflow-hidden">
      <div className="px-4 py-3 border-b border-border">
        <h3 className="text-sm font-semibold">Strukturirani izračun popravka</h3>
      </div>

      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead>
            <tr className="border-b border-border text-muted">
              <th className="text-left px-3 py-2 font-medium">#</th>
              <th className="text-left px-3 py-2 font-medium">Dio</th>
              <th className="text-left px-3 py-2 font-medium">Operacija</th>
              <th className="text-left px-3 py-2 font-medium">Vrsta rada</th>
              <th className="text-right px-3 py-2 font-medium">Sati</th>
              <th className="text-left px-3 py-2 font-medium">Tip dijela</th>
              <th className="text-right px-3 py-2 font-medium">Kol.</th>
              <th className="text-right px-3 py-2 font-medium">Cijena</th>
              <th className="text-right px-3 py-2 font-medium">Ukupno</th>
            </tr>
          </thead>
          <tbody>
            {groups.map((group, gi) => (
              <GroupRows key={gi} group={group} groupIndex={gi} />
            ))}
          </tbody>
        </table>
      </div>

      {(hasStructuredTotals || i.grossTotal != null) && (
        <div className="px-4 py-3 border-t border-border space-y-1">
          {i.laborTotal != null && (
            <div className="flex justify-between text-xs">
              <span className="text-muted">Rad ukupno</span>
              <span>{formatCurrency(i.laborTotal)}</span>
            </div>
          )}
          {i.partsTotal != null && (
            <div className="flex justify-between text-xs">
              <span className="text-muted">Dijelovi ukupno</span>
              <span>{formatCurrency(i.partsTotal)}</span>
            </div>
          )}
          {i.materialsTotal != null && (
            <div className="flex justify-between text-xs">
              <span className="text-muted">Materijali ukupno</span>
              <span>{formatCurrency(i.materialsTotal)}</span>
            </div>
          )}
          {i.grossTotal != null && (
            <div className="flex justify-between text-sm font-semibold mt-2 pt-2 border-t border-border">
              <span>Bruto ukupno</span>
              <span className="text-accent">{formatCurrency(i.grossTotal)}</span>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function GroupRows({ group, groupIndex }: { group: { label: string; items: RepairLineItem[] }; groupIndex: number }) {
  return (
    <>
      <tr className="border-b border-border">
        <td colSpan={9} className="px-3 py-2 text-[10px] font-semibold text-accent uppercase tracking-wider bg-accent/5">
          {group.label}
        </td>
      </tr>
      {group.items.map((item, i) => (
        <tr key={`${groupIndex}-${i}`} className="border-b border-border hover:bg-card-hover transition-colors">
          <td className="px-3 py-2 text-muted">{item.lineNumber}</td>
          <td className="px-3 py-2 font-medium">{item.partName}</td>
          <td className="px-3 py-2 text-muted">{item.operation}</td>
          <td className="px-3 py-2 text-muted">{laborTypeLabel(item.laborType)}</td>
          <td className="px-3 py-2 text-right">{item.laborHours > 0 ? item.laborHours.toFixed(1) : "—"}</td>
          <td className="px-3 py-2 text-muted">{item.partType}</td>
          <td className="px-3 py-2 text-right">{item.quantity}</td>
          <td className="px-3 py-2 text-right text-muted">{item.unitCost != null ? formatCurrency(item.unitCost) : "—"}</td>
          <td className="px-3 py-2 text-right font-medium">{item.totalCost != null ? formatCurrency(item.totalCost) : "—"}</td>
        </tr>
      ))}
    </>
  );
}
