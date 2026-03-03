"use client";

import { useState, useMemo, useRef, useEffect } from "react";
import { motion, AnimatePresence } from "framer-motion";
import vehicleData from "@/data/vehicles.json";
import { cn } from "@/lib/cn";
import type { VehicleContext } from "@/lib/api";

interface VehicleSelectorProps {
  onNext: (vehicle: VehicleContext) => void;
  onSkip: () => void;
}

const currentYear = new Date().getFullYear();
const years = Array.from({ length: currentYear - 1989 }, (_, i) => currentYear + 1 - i);

export function VehicleSelector({ onNext, onSkip }: VehicleSelectorProps) {
  const [make, setMake] = useState("");
  const [model, setModel] = useState("");
  const [year, setYear] = useState<number | undefined>();
  const [mileage, setMileage] = useState("");
  const [makeSearch, setMakeSearch] = useState("");
  const [modelSearch, setModelSearch] = useState("");
  const [showMakeDropdown, setShowMakeDropdown] = useState(false);
  const [showModelDropdown, setShowModelDropdown] = useState(false);
  const makeRef = useRef<HTMLDivElement>(null);
  const modelRef = useRef<HTMLDivElement>(null);

  const makes = vehicleData.makes.map((m) => m.name);
  const models = useMemo(() => {
    const found = vehicleData.makes.find((m) => m.name === make);
    return found ? found.models : [];
  }, [make]);

  const filteredMakes = useMemo(
    () => makes.filter((m) => m.toLowerCase().includes(makeSearch.toLowerCase())),
    [makeSearch]
  );

  const filteredModels = useMemo(
    () => models.filter((m) => m.toLowerCase().includes(modelSearch.toLowerCase())),
    [models, modelSearch]
  );

  // Close dropdowns on outside click
  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (makeRef.current && !makeRef.current.contains(e.target as Node)) setShowMakeDropdown(false);
      if (modelRef.current && !modelRef.current.contains(e.target as Node)) setShowModelDropdown(false);
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, []);

  const handleNext = () => {
    onNext({
      vehicleMake: make || undefined,
      vehicleModel: model || undefined,
      vehicleYear: year,
      mileage: mileage ? parseInt(mileage) : undefined,
    });
  };

  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -20 }}
      className="glass rounded-2xl p-6 max-w-lg mx-auto"
    >
      <div className="flex items-center gap-3 mb-6">
        <div className="w-10 h-10 rounded-xl gradient-btn flex items-center justify-center">
          <svg className="w-5 h-5 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M8.25 18.75a1.5 1.5 0 01-3 0m3 0a1.5 1.5 0 00-3 0m3 0h6m-9 0H3.375a1.125 1.125 0 01-1.125-1.125V14.25m17.25 4.5a1.5 1.5 0 01-3 0m3 0a1.5 1.5 0 00-3 0m3 0h1.125c.621 0 1.129-.504 1.09-1.124a17.902 17.902 0 00-3.213-9.193 2.056 2.056 0 00-1.58-.86H14.25M16.5 18.75h-2.25m0-11.177v-.958c0-.568-.422-1.048-.987-1.106a48.554 48.554 0 00-10.026 0 1.106 1.106 0 00-.987 1.106v7.635m12-6.677v6.677m0 4.5v-4.5m0 0h-12" />
          </svg>
        </div>
        <div>
          <h2 className="text-lg font-semibold">Odaberite vozilo</h2>
          <p className="text-sm text-muted">Opccionalno - poboljsava tocnost analize</p>
        </div>
      </div>

      <div className="space-y-4">
        {/* Make selector */}
        <div ref={makeRef} className="relative">
          <label className="block text-xs text-muted mb-1.5">Marka</label>
          <input
            type="text"
            value={showMakeDropdown ? makeSearch : make}
            onChange={(e) => {
              setMakeSearch(e.target.value);
              setShowMakeDropdown(true);
            }}
            onFocus={() => {
              setMakeSearch("");
              setShowMakeDropdown(true);
            }}
            placeholder="Npr. Volkswagen, BMW, Audi..."
            className="w-full px-4 py-2.5 bg-background/50 border border-white/[0.06] rounded-xl text-sm focus:outline-none focus:border-accent/50 transition-colors"
          />
          <AnimatePresence>
            {showMakeDropdown && (
              <motion.div
                initial={{ opacity: 0, y: -4 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -4 }}
                className="absolute z-20 w-full mt-1 glass-strong rounded-xl max-h-48 overflow-y-auto shadow-xl"
              >
                {filteredMakes.map((m) => (
                  <button
                    key={m}
                    onClick={() => {
                      setMake(m);
                      setModel("");
                      setShowMakeDropdown(false);
                      setMakeSearch("");
                    }}
                    className={cn(
                      "w-full text-left px-4 py-2 text-sm hover:bg-accent/10 transition-colors",
                      m === make && "text-accent font-medium"
                    )}
                  >
                    {m}
                  </button>
                ))}
                {filteredMakes.length === 0 && (
                  <div className="px-4 py-3 text-sm text-muted">Nema rezultata</div>
                )}
              </motion.div>
            )}
          </AnimatePresence>
        </div>

        {/* Model selector */}
        <div ref={modelRef} className="relative">
          <label className="block text-xs text-muted mb-1.5">Model</label>
          <input
            type="text"
            value={showModelDropdown ? modelSearch : model}
            onChange={(e) => {
              setModelSearch(e.target.value);
              setShowModelDropdown(true);
            }}
            onFocus={() => {
              setModelSearch("");
              setShowModelDropdown(true);
            }}
            placeholder={make ? `Odaberite model ${make}...` : "Prvo odaberite marku"}
            disabled={!make}
            className="w-full px-4 py-2.5 bg-background/50 border border-white/[0.06] rounded-xl text-sm focus:outline-none focus:border-accent/50 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
          />
          <AnimatePresence>
            {showModelDropdown && make && (
              <motion.div
                initial={{ opacity: 0, y: -4 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -4 }}
                className="absolute z-20 w-full mt-1 glass-strong rounded-xl max-h-48 overflow-y-auto shadow-xl"
              >
                {filteredModels.map((m) => (
                  <button
                    key={m}
                    onClick={() => {
                      setModel(m);
                      setShowModelDropdown(false);
                      setModelSearch("");
                    }}
                    className={cn(
                      "w-full text-left px-4 py-2 text-sm hover:bg-accent/10 transition-colors",
                      m === model && "text-accent font-medium"
                    )}
                  >
                    {m}
                  </button>
                ))}
                {filteredModels.length === 0 && (
                  <div className="px-4 py-3 text-sm text-muted">Nema rezultata</div>
                )}
              </motion.div>
            )}
          </AnimatePresence>
        </div>

        {/* Year + Mileage row */}
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="block text-xs text-muted mb-1.5">Godiste</label>
            <select
              value={year || ""}
              onChange={(e) => setYear(e.target.value ? parseInt(e.target.value) : undefined)}
              className="w-full px-4 py-2.5 bg-background/50 border border-white/[0.06] rounded-xl text-sm focus:outline-none focus:border-accent/50 transition-colors appearance-none"
            >
              <option value="">Odaberite...</option>
              {years.map((y) => (
                <option key={y} value={y}>{y}</option>
              ))}
            </select>
          </div>
          <div>
            <label className="block text-xs text-muted mb-1.5">Kilometraza</label>
            <input
              type="number"
              value={mileage}
              onChange={(e) => setMileage(e.target.value)}
              placeholder="Npr. 120000"
              min={0}
              className="w-full px-4 py-2.5 bg-background/50 border border-white/[0.06] rounded-xl text-sm focus:outline-none focus:border-accent/50 transition-colors"
            />
          </div>
        </div>
      </div>

      {/* Buttons */}
      <div className="flex items-center justify-between mt-6">
        <button
          onClick={onSkip}
          className="px-5 py-2.5 text-sm text-muted hover:text-foreground transition-colors"
        >
          Preskoci
        </button>
        <button
          onClick={handleNext}
          className="px-6 py-2.5 gradient-btn rounded-xl text-sm font-medium"
        >
          Dalje
        </button>
      </div>
    </motion.div>
  );
}
