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
        <path strokeLinecap="round" strokeLinejoin="round" d="M7.5 3.75H6A2.25 2.25 0 003.75 6v1.5M16.5 3.75H18A2.25 2.25 0 0120.25 6v1.5m0 9V18A2.25 2.25 0 0118 20.25h-1.5m-9 0H6A2.25 2.25 0 013.75 18v-1.5M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
      </svg>
    ),
    title: "Detekcija šteta",
    desc: "AI prepoznaje ogrebotine, udubljenja, pukotine, oštećenja boje, slomljeno staklo i deformacije karoserije.",
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
        <path strokeLinecap="round" strokeLinejoin="round" d="M3.75 3v11.25A2.25 2.25 0 006 16.5h2.25M3.75 3h-1.5m1.5 0h16.5m0 0h1.5m-1.5 0v11.25A2.25 2.25 0 0118 16.5h-2.25m-7.5 0h7.5m-7.5 0l-1 3m8.5-3l1 3m0 0l.5 1.5m-.5-1.5h-9.5m0 0l-.5 1.5m.75-9l3-3 2.148 2.148A12.061 12.061 0 0116.5 7.605" />
      </svg>
    ),
    title: "Klasifikacija ozbiljnosti",
    desc: "Svaka šteta se klasificira po ozbiljnosti: manja, umjerena, ozbiljna ili kritična, za brže odluke.",
  },
  {
    icon: (
      <svg className="w-6 h-6" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
        <path strokeLinecap="round" strokeLinejoin="round" d="M8.25 18.75a1.5 1.5 0 01-3 0m3 0a1.5 1.5 0 00-3 0m3 0h6m-9 0H3.375a1.125 1.125 0 01-1.125-1.125V14.25m17.25 4.5a1.5 1.5 0 01-3 0m3 0a1.5 1.5 0 00-3 0m3 0h1.125c.621 0 1.129-.504 1.09-1.124a17.902 17.902 0 00-3.213-9.193 2.056 2.056 0 00-1.58-.86H14.25M16.5 18.75h-2.25m0-11.177v-.958c0-.568-.422-1.048-.987-1.106a48.554 48.554 0 00-10.026 0 1.106 1.106 0 00-.987 1.106v7.635m12-6.677v6.677m0 4.5v-4.5m0 0h-12" />
      </svg>
    ),
    title: "Prepoznavanje vozila",
    desc: "AI automatski prepoznaje marku, model, godinu i boju vozila iz fotografije bez ručnog unosa.",
  },
  {
    icon: (
      <svg className="w-6 h-6" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
        <path strokeLinecap="round" strokeLinejoin="round" d="M9 12.75L11.25 15 15 9.75m-3-7.036A11.959 11.959 0 013.598 6 11.99 11.99 0 003 9.749c0 5.592 3.824 10.29 9 11.623 5.176-1.332 9-6.03 9-11.622 0-1.31-.21-2.571-.598-3.751h-.152c-3.196 0-6.1-1.248-8.25-3.285z" />
      </svg>
    ),
    title: "Odluka u realnom vremenu",
    desc: "Automatski sustav odlučivanja: odobri, pregledaj ili eskaliraj - na temelju pravila i pragova troškova.",
  },
  {
    icon: (
      <svg className="w-6 h-6" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
        <path strokeLinecap="round" strokeLinejoin="round" d="M2.25 15.75l5.159-5.159a2.25 2.25 0 013.182 0l5.159 5.159m-1.5-1.5l1.409-1.409a2.25 2.25 0 013.182 0l2.909 2.909M3.75 21h16.5A2.25 2.25 0 0022.5 18.75V5.25A2.25 2.25 0 0020.25 3H3.75A2.25 2.25 0 001.5 5.25v13.5A2.25 2.25 0 003.75 21z" />
      </svg>
    ),
    title: "Više slika odjednom",
    desc: "Uploadajte do 8 fotografija iz različitih kutova za sveobuhvatnu analizu cijelog vozila.",
  },
];

const steps = [
  {
    num: "01",
    title: "Uploadajte fotografije",
    desc: "Dodajte do 8 fotografija oštećenog vozila iz različitih kutova. Podržani formati: JPG, PNG, WebP, HEIC.",
  },
  {
    num: "02",
    title: "AI analizira",
    desc: "Napredni vizijski model detektira, klasificira i mapira svako oštećenje. Analiza traje 30-90 sekundi.",
  },
  {
    num: "03",
    title: "Preuzmite izvještaj",
    desc: "Dobijte detaljan izvještaj sa svim otkrivenim štetama, procjenama troškova i preporukom za djelovanje.",
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
              Analizirajte štete na vozilu{" "}
              <span className="text-accent">u sekundama</span>
            </h1>
            <p className="text-lg sm:text-xl text-muted leading-relaxed mb-10 max-w-2xl mx-auto">
              Uploadajte fotografiju oštećenog vozila i dobijte profesionalni
              AI izvještaj s detekcijom šteta, klasifikacijom ozbiljnosti i
              procjenom troškova popravka.
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
              Tri koraka do izvještaja
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
              Sve što vam treba za procjenu šteta
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

      {/* ===== WHAT AI DETECTS ===== */}
      <section className="section-alt border-y border-border">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 py-16 md:py-20">
          <div className="text-center mb-12">
            <p className="text-xs font-semibold uppercase tracking-widest text-accent mb-2">
              AI detekcija
            </p>
            <h2 className="font-heading text-2xl sm:text-3xl font-bold tracking-tight mb-4">
              Što AI prepoznaje na vašem vozilu
            </h2>
            <p className="text-muted max-w-2xl mx-auto">
              Napredni vizijski model analizira svaki piksel fotografije i detektira
              različite vrste oštećenja na svim dijelovima vozila.
            </p>
          </div>
          <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-4">
            {[
              "Ogrebotine",
              "Udubljenja",
              "Pukotine",
              "Oštećenja boje",
              "Slomljeno staklo",
              "Hrđa",
              "Deformacije karoserije",
              "Oštećenja branika",
            ].map((label) => (
              <div
                key={label}
                className="flex items-center gap-3 px-4 py-3.5 bg-white rounded-xl border border-border"
              >
                <div className="w-2 h-2 rounded-full bg-accent flex-shrink-0" />
                <span className="text-sm font-medium">{label}</span>
              </div>
            ))}
          </div>
          <div className="mt-10 grid grid-cols-1 sm:grid-cols-3 gap-4 max-w-3xl mx-auto">
            <div className="text-center py-6 px-4 bg-white rounded-2xl border border-border">
              <div className="font-heading text-3xl font-bold text-accent mb-1">12+</div>
              <div className="text-xs text-muted">Tipova šteta</div>
            </div>
            <div className="text-center py-6 px-4 bg-white rounded-2xl border border-border">
              <div className="font-heading text-3xl font-bold text-accent mb-1">26+</div>
              <div className="text-xs text-muted">Dijelova vozila</div>
            </div>
            <div className="text-center py-6 px-4 bg-white rounded-2xl border border-border">
              <div className="font-heading text-3xl font-bold text-accent mb-1">&lt;90s</div>
              <div className="text-xs text-muted">Vrijeme analize</div>
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
              Uploadajte fotografije oštećenog vozila i dobijte detaljan AI
              izvještaj za manje od 2 minute.
            </p>
            <Link
              href="/inspect"
              className="inline-flex items-center gap-2 px-8 py-3.5 bg-accent text-white rounded-xl font-semibold text-base hover:bg-accent-hover transition-colors"
            >
              <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M3 16.5v2.25A2.25 2.25 0 005.25 21h13.5A2.25 2.25 0 0021 18.75V16.5m-13.5-9L12 3m0 0l4.5 4.5M12 3v13.5" />
              </svg>
              Pokreni novu inspekciju
            </Link>
          </div>
        </div>
      </section>
    </div>
  );
}
