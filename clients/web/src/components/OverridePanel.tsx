"use client";

import { useState } from "react";
import type { DecisionOverride } from "@/lib/api";
import { overrideDecision, decisionOutcomeLabel, formatDate } from "@/lib/api";

interface OverridePanelProps {
  inspectionId: string;
  currentOutcome: string;
  overrides: DecisionOverride[];
  onOverrideComplete: () => void;
}

const outcomes = [
  { value: "AutoApprove", label: "Automatski odobreno" },
  { value: "HumanReview", label: "Potreban pregled" },
  { value: "Escalate", label: "Eskalirano" },
];

export function OverridePanel({ inspectionId, currentOutcome, overrides, onOverrideComplete }: OverridePanelProps) {
  const [showForm, setShowForm] = useState(false);
  const [newOutcome, setNewOutcome] = useState("");
  const [reason, setReason] = useState("");
  const [operatorName, setOperatorName] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async () => {
    if (!newOutcome || !reason.trim() || !operatorName.trim()) return;
    setSubmitting(true);
    setError(null);
    try {
      await overrideDecision(inspectionId, newOutcome, reason, operatorName);
      setShowForm(false);
      setNewOutcome("");
      setReason("");
      onOverrideComplete();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Greška");
    } finally {
      setSubmitting(false);
    }
  };

  const availableOutcomes = outcomes.filter((o) => o.value !== currentOutcome);

  return (
    <div className="bg-card border border-border rounded-xl overflow-hidden">
      <div className="flex items-center justify-between px-4 py-3">
        <span className="text-sm font-medium">Pregazi odluku</span>
        {!showForm && (
          <button
            onClick={() => setShowForm(true)}
            className="px-3 py-1.5 text-xs bg-accent text-white rounded-md font-medium hover:bg-accent-hover transition-colors"
          >
            Pregazi
          </button>
        )}
      </div>

      {showForm && (
        <div className="px-4 pb-4 space-y-3 border-t border-border pt-3">
          <div>
            <label className="block text-xs text-muted mb-1.5">Nova odluka</label>
            <select
              value={newOutcome}
              onChange={(e) => setNewOutcome(e.target.value)}
              className="w-full px-3 py-2 bg-white border border-border rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-accent/20 focus:border-accent"
            >
              <option value="">Odaberite...</option>
              {availableOutcomes.map((o) => (
                <option key={o.value} value={o.value}>{o.label}</option>
              ))}
            </select>
          </div>
          <div>
            <label className="block text-xs text-muted mb-1.5">Razlog</label>
            <textarea
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              placeholder="Razlog za promjenu odluke..."
              rows={2}
              className="w-full px-3 py-2 bg-white border border-border rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-accent/20 focus:border-accent resize-none"
            />
          </div>
          <div>
            <label className="block text-xs text-muted mb-1.5">Ime operatera</label>
            <input
              type="text"
              value={operatorName}
              onChange={(e) => setOperatorName(e.target.value)}
              placeholder="Vaše ime..."
              className="w-full px-3 py-2 bg-white border border-border rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-accent/20 focus:border-accent"
            />
          </div>
          {error && <p className="text-xs text-red-500">{error}</p>}
          <div className="flex gap-2">
            <button
              onClick={handleSubmit}
              disabled={submitting || !newOutcome || !reason.trim() || !operatorName.trim()}
              className="px-4 py-2 bg-accent text-white rounded-lg text-xs font-medium hover:bg-accent-hover disabled:opacity-40 transition-colors"
            >
              {submitting ? "Slanje..." : "Potvrdi"}
            </button>
            <button
              onClick={() => setShowForm(false)}
              className="px-4 py-2 text-xs text-muted hover:text-foreground transition-colors"
            >
              Odustani
            </button>
          </div>
        </div>
      )}

      {overrides.length > 0 && (
        <div className="px-4 pb-4 border-t border-border">
          <p className="text-xs text-muted mt-3 mb-2">Povijest promjena:</p>
          <div className="space-y-2">
            {overrides.map((o, i) => (
              <div key={i} className="bg-gray-50 rounded-lg px-3 py-2 text-xs">
                <div className="flex items-center gap-2 mb-1">
                  <span className="text-muted">{decisionOutcomeLabel(o.originalOutcome)}</span>
                  <span className="text-muted">&rarr;</span>
                  <span className="font-medium">{decisionOutcomeLabel(o.newOutcome)}</span>
                </div>
                <p className="text-muted">{o.reason}</p>
                <p className="text-muted mt-1">{o.operatorName} &middot; {formatDate(o.createdAt)}</p>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
