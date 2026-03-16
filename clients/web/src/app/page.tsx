"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { getDashboardStats, type DashboardStats as Stats } from "@/lib/api";
import { DashboardStats } from "@/components/DashboardStats";
import { InspectionCard } from "@/components/InspectionCard";

const features = [
  {
    icon: (
      <svg className="w-6 h-6" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
        <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v3.75m-9.303 3.376c-.866 1.5.217 3.374 1.948 3.374h14.71c1.73 0 2.813-1.874 1.948-3.374L13.949 3.378c-.866-1.5-3.032-1.5-3.898 0L2.697 16.126zM12 15.75h.007v.008H12v-.008z" />
      </svg>
    ),
    title: "Detekcija prijevara",
    desc: "Forenzička analiza slika: ELA, FFT spektar, CNN detekcija manipulacija, analiza metapodataka i provjera autentičnosti.",
  },
  {
    icon: (
      <svg className="w-6 h-6" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
        <path strokeLinecap="round" strokeLinejoin="round" d="M7.5 3.75H6A2.25 2.25 0 003.75 6v1.5M16.5 3.75H18A2.25 2.25 0 0120.25 6v1.5m0 9V18A2.25 2.25 0 0118 20.25h-1.5m-9 0H6A2.25 2.25 0 013.75 18v-1.5M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
      </svg>
    ),
    title: "Detekcija šteta",
    desc: "AI prepoznaje ogrebotine, udubljenja, pukotine, oštećenja boje, slomljeno staklo i deformacije karoserije.",
  },
  {
    icon: (
      <svg className="w-6 h-6" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
        <path strokeLinecap="round" strokeLinejoin="round" d="M9.75 3.104v5.714a2.25 2.25 0 01-.659 1.591L5 14.5M9.75 3.104c-.251.023-.501.05-.75.082m.75-.082a24.301 24.301 0 014.5 0m0 0v5.714c0 .597.237 1.17.659 1.591L19.8 15.3M14.25 3.104c.251.023.501.05.75.082M19.8 15.3l-1.57.393A9.065 9.065 0 0112 15a9.065 9.065 0 00-6.23.693L5 14.5m14.8.8l1.402 1.402c1.232 1.232.65 3.318-1.067 3.611A48.309 48.309 0 0112 21c-2.773 0-5.491-.235-8.135-.687-1.718-.293-2.3-2.379-1.067-3.61L5 14.5" />
      </svg>
    ),
    title: "AI agent evaluacija",
    desc: "LLM agent analizira cijeli predmet: štete, forenziku, vremenske uvjete i autonomno donosi odluku o odobrenju.",
  },
  {
    icon: (
      <svg className="w-6 h-6" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
        <path strokeLinecap="round" strokeLinejoin="round" d="M12 6v12m-3-2.818l.879.659c1.171.879 3.07.879 4.242 0 1.172-.879 1.172-2.303 0-3.182C13.536 12.219 12.768 12 12 12c-.725 0-1.45-.22-2.003-.659-1.106-.879-1.106-2.303 0-3.182s2.9-.879 4.006 0l.415.33M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
      </svg>
    ),
    title: "Procjena troškova",
    desc: "Automatska kalkulacija troškova popravka s detaljnim stavkama: rad, dijelovi, materijali i ukupna procjena.",
  },
  {
    icon: (
      <svg className="w-6 h-6" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
        <path strokeLinecap="round" strokeLinejoin="round" d="M16.5 10.5V6.75a4.5 4.5 0 10-9 0v3.75m-.75 11.25h10.5a2.25 2.25 0 002.25-2.25v-6.75a2.25 2.25 0 00-2.25-2.25H6.75a2.25 2.25 0 00-2.25 2.25v6.75a2.25 2.25 0 002.25 2.25z" />
      </svg>
    ),
    title: "Sudska admisibilnost",
    desc: "SHA-256 hash, RFC 3161 vremenski pečat, lanac skrbništva (ISO 27037) i PDF/XML izvještaji za sud.",
  },
  {
    icon: (
      <svg className="w-6 h-6" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
        <path strokeLinecap="round" strokeLinejoin="round" d="M9 12.75L11.25 15 15 9.75m-3-7.036A11.959 11.959 0 013.598 6 11.99 11.99 0 003 9.749c0 5.592 3.824 10.29 9 11.623 5.176-1.332 9-6.03 9-11.622 0-1.31-.21-2.571-.598-3.751h-.152c-3.196 0-6.1-1.248-8.25-3.285z" />
      </svg>
    ),
    title: "Automatska odluka",
    desc: "STP (Straight-Through Processing): automatsko odobrenje, eskalacija ili pregled - s punim traceom odluke.",
  },
];

const steps = [
  {
    num: "01",
    title: "Uploadajte fotografije",
    desc: "Dodajte do 8 fotografija oštećenog vozila. Sustav hvata GPS, uređaj i metadata za kompletnu evidenciju.",
  },
  {
    num: "02",
    title: "AI analizira i verificira",
    desc: "Gemini 2.5 Pro detektira štete, 6 forenzičkih modula provjerava autentičnost, AI agent donosi odluku.",
  },
  {
    num: "03",
    title: "Zapečaćen izvještaj",
    desc: "Dobijte kriptografski potpisan izvještaj s SHA-256 hashevima, RFC 3161 pečatom i lancem skrbništva.",
  },
];

export default function Dashboard() {
  const [stats, setStats] = useState<Stats | null>(null);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    getDashboardStats()
      .then(setStats)
      .catch(() => {})
      .finally(() => setLoaded(true));
  }, []);

  return (
    <div>
      {/* ===== HERO ===== */}
      <section className="relative overflow-hidden">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 pt-16 pb-20 md:pt-24 md:pb-28">
          <div className="max-w-3xl mx-auto text-center">
            <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-accent-light text-accent text-xs font-medium mb-6">
              <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M9.813 15.904L9 18.75l-.813-2.846a4.5 4.5 0 00-3.09-3.09L2.25 12l2.846-.813a4.5 4.5 0 003.09-3.09L9 5.25l.813 2.846a4.5 4.5 0 003.09 3.09L15.75 12l-2.846.813a4.5 4.5 0 00-3.09 3.09z" />
              </svg>
              Pogonjeno Gemini 2.5 Pro AI modelom
            </div>
            <h1 className="font-heading text-4xl sm:text-5xl md:text-6xl font-extrabold tracking-tight leading-[1.1] mb-6">
              Detekcija prijevara{" "}
              <span className="text-accent">u osiguranju vozila</span>
            </h1>
            <p className="text-lg sm:text-xl text-muted leading-relaxed mb-10 max-w-2xl mx-auto">
              AI platforma za analizu šteta, forenzičku verifikaciju fotografija,
              detekciju manipulacija i automatsko donošenje odluka
              s kriptografskim dokazima za sud.
            </p>
            <div className="flex flex-col sm:flex-row items-center justify-center gap-3">
              <Link
                href="/inspect"
                className="w-full sm:w-auto px-8 py-3.5 bg-accent text-white rounded-xl font-semibold text-base hover:bg-accent-hover transition-colors"
              >
                Pokreni analizu
              </Link>
              <Link
                href="/inspections"
                className="w-full sm:w-auto px-8 py-3.5 bg-card border border-border text-foreground rounded-xl font-semibold text-base hover:bg-card-hover transition-colors"
              >
                Pregledaj inspekcije
              </Link>
            </div>
          </div>
        </div>
        <div className="absolute inset-0 -z-10 overflow-hidden">
          <div className="absolute -top-40 -right-40 w-[600px] h-[600px] rounded-full bg-accent/[0.03]" />
          <div className="absolute -bottom-40 -left-40 w-[500px] h-[500px] rounded-full bg-accent/[0.02]" />
        </div>
      </section>

      {/* ===== HOW IT WORKS ===== */}
      <section className="section-alt border-y border-border">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 py-16 md:py-20">
          <div className="text-center mb-12">
            <p className="text-xs font-semibold uppercase tracking-widest text-accent mb-2">
              Kako funkcionira
            </p>
            <h2 className="font-heading text-2xl sm:text-3xl font-bold tracking-tight">
              Tri koraka do odluke
            </h2>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-8 md:gap-12">
            {steps.map((step) => (
              <div key={step.num} className="text-center md:text-left">
                <div className="inline-flex items-center justify-center w-12 h-12 rounded-2xl bg-accent text-white font-heading font-bold text-sm mb-4">
                  {step.num}
                </div>
                <h3 className="font-heading font-semibold text-lg mb-2">
                  {step.title}
                </h3>
                <p className="text-sm text-muted leading-relaxed">
                  {step.desc}
                </p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ===== FEATURES ===== */}
      <section>
        <div className="max-w-7xl mx-auto px-4 sm:px-6 py-16 md:py-20">
          <div className="text-center mb-12">
            <p className="text-xs font-semibold uppercase tracking-widest text-accent mb-2">
              Mogućnosti
            </p>
            <h2 className="font-heading text-2xl sm:text-3xl font-bold tracking-tight">
              Kompletna platforma za osiguranje
            </h2>
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-6">
            {features.map((f) => (
              <div
                key={f.title}
                className="p-6 rounded-2xl border border-border hover:border-accent/20 hover:bg-accent-light/30 transition-colors"
              >
                <div className="w-10 h-10 rounded-xl bg-accent-light flex items-center justify-center text-accent mb-4">
                  {f.icon}
                </div>
                <h3 className="font-heading font-semibold mb-2">{f.title}</h3>
                <p className="text-sm text-muted leading-relaxed">{f.desc}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ===== FORENSIC PIPELINE ===== */}
      <section className="section-alt border-y border-border">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 py-16 md:py-20">
          <div className="text-center mb-12">
            <p className="text-xs font-semibold uppercase tracking-widest text-accent mb-2">
              Forenzički pipeline
            </p>
            <h2 className="font-heading text-2xl sm:text-3xl font-bold tracking-tight mb-4">
              6 modula forenzičke analize
            </h2>
            <p className="text-muted max-w-2xl mx-auto">
              Svaka fotografija prolazi kroz višeslojnu provjeru autentičnosti
              koja detektira Photoshop manipulacije, AI-generirane slike i lažne metapodatke.
            </p>
          </div>
          <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-3 gap-4">
            {[
              { label: "Analiza metapodataka", desc: "EXIF, GPS, kamera, softver" },
              { label: "Detekcija modifikacija", desc: "ELA, FFT spektar, JPEG artefakti" },
              { label: "CNN duboka analiza", desc: "CatNet, TruFor neuralne mreže" },
              { label: "Optička forenzika", desc: "Razina šuma, CFA uzorci" },
              { label: "Semantička forenzika", desc: "AI detekcija, VLM provjera" },
              { label: "Forenzika dokumenata", desc: "PDF struktura, potpisi, fontovi" },
            ].map((item) => (
              <div
                key={item.label}
                className="flex flex-col px-4 py-4 bg-white rounded-xl border border-border"
              >
                <div className="flex items-center gap-2 mb-1">
                  <div className="w-2 h-2 rounded-full bg-accent flex-shrink-0" />
                  <span className="text-sm font-medium">{item.label}</span>
                </div>
                <span className="text-xs text-muted pl-4">{item.desc}</span>
              </div>
            ))}
          </div>
          <div className="mt-10 grid grid-cols-1 sm:grid-cols-4 gap-4 max-w-4xl mx-auto">
            <div className="text-center py-6 px-4 bg-white rounded-2xl border border-border">
              <div className="font-heading text-3xl font-bold text-accent mb-1">6</div>
              <div className="text-xs text-muted">Forenzičkih modula</div>
            </div>
            <div className="text-center py-6 px-4 bg-white rounded-2xl border border-border">
              <div className="font-heading text-3xl font-bold text-accent mb-1">12+</div>
              <div className="text-xs text-muted">Tipova šteta</div>
            </div>
            <div className="text-center py-6 px-4 bg-white rounded-2xl border border-border">
              <div className="font-heading text-3xl font-bold text-accent mb-1">26+</div>
              <div className="text-xs text-muted">Dijelova vozila</div>
            </div>
            <div className="text-center py-6 px-4 bg-white rounded-2xl border border-border">
              <div className="font-heading text-3xl font-bold text-accent mb-1">RFC 3161</div>
              <div className="text-xs text-muted">Vremenski pečat</div>
            </div>
          </div>
        </div>
      </section>

      {/* ===== DASHBOARD STATS (if available) ===== */}
      {loaded && stats && stats.totalInspections > 0 && (
        <section>
          <div className="max-w-7xl mx-auto px-4 sm:px-6 py-16 md:py-20">
            <div className="text-center mb-12">
              <p className="text-xs font-semibold uppercase tracking-widest text-accent mb-2">
                Vaše statistike
              </p>
              <h2 className="font-heading text-2xl sm:text-3xl font-bold tracking-tight">
                Pregled vaših inspekcija
              </h2>
            </div>
            <DashboardStats stats={stats} />
            {stats.recentInspections.length > 0 && (
              <div className="mt-10">
                <div className="flex items-center justify-between mb-5">
                  <h3 className="font-heading font-semibold">
                    Zadnje inspekcije
                  </h3>
                  <Link
                    href="/inspections"
                    className="text-sm text-accent hover:text-accent-hover transition-colors font-medium"
                  >
                    Vidi sve
                  </Link>
                </div>
                <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
                  {stats.recentInspections.map((inspection) => (
                    <InspectionCard
                      key={inspection.id}
                      inspection={inspection}
                    />
                  ))}
                </div>
              </div>
            )}
          </div>
        </section>
      )}

      {/* ===== CTA BANNER ===== */}
      <section className={loaded && stats && stats.totalInspections > 0 ? "section-alt border-y border-border" : "border-t border-border section-alt"}>
        <div className="max-w-7xl mx-auto px-4 sm:px-6 py-16 md:py-20">
          <div className="max-w-2xl mx-auto text-center">
            <h2 className="font-heading text-2xl sm:text-3xl font-bold tracking-tight mb-4">
              Spremni za analizu?
            </h2>
            <p className="text-muted mb-8">
              Uploadajte fotografije i dobijte forenzički verificiran
              izvještaj s kriptografskim dokazima za manje od 2 minute.
            </p>
            <Link
              href="/inspect"
              className="inline-flex items-center gap-2 px-8 py-3.5 bg-accent text-white rounded-xl font-semibold text-base hover:bg-accent-hover transition-colors"
            >
              <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M3 16.5v2.25A2.25 2.25 0 005.25 21h13.5A2.25 2.25 0 0021 18.75V16.5m-13.5-9L12 3m0 0l4.5 4.5M12 3v13.5" />
              </svg>
              Pokreni novu analizu
            </Link>
          </div>
        </div>
      </section>
    </div>
  );
}
