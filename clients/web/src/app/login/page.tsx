"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { useAuth } from "@/lib/auth";

type Tab = "login" | "register";

export default function LoginPage() {
  const router = useRouter();
  const { user, login, register } = useAuth();
  const [tab, setTab] = useState<Tab>("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [fullName, setFullName] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [showPassword, setShowPassword] = useState(false);
  const passwordRef = useRef<HTMLInputElement>(null);

  // Redirect if already logged in
  useEffect(() => {
    if (user) {
      router.replace("/inspections");
    }
  }, [user, router]);

  if (user) {
    return null;
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError("");

    if (!email.trim()) { setError("Unesite email adresu."); return; }
    if (!password) { setError("Unesite lozinku."); return; }
    if (tab === "register" && !fullName.trim()) { setError("Unesite ime i prezime."); return; }

    setLoading(true);

    try {
      if (tab === "login") {
        await login(email, password);
      } else {
        await register(email, password, fullName);
      }
      router.push("/inspections");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Greška. Pokušajte ponovo.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="relative min-h-[80dvh] flex items-center justify-center px-4 overflow-hidden">
      <div className="pointer-events-none absolute inset-0 -z-10 overflow-hidden">
        <div className="absolute -top-20 -right-20 w-[250px] h-[250px] sm:-top-28 sm:-right-28 sm:w-[350px] sm:h-[350px] lg:-top-32 lg:-right-32 lg:w-[450px] lg:h-[450px] rounded-full deco-circle" />
      </div>
      <div className="w-full max-w-sm fade-up">
        {/* Logo */}
        <div className="text-center mb-8">
          <Link href="/" className="inline-flex items-center gap-2.5">
            <div className="w-10 h-10 rounded-xl bg-accent flex items-center justify-center text-white font-bold text-lg">
              D
            </div>
            <span className="font-heading font-bold text-2xl tracking-tight">
              DENT
            </span>
          </Link>
        </div>

        {/* Tabs */}
        <div className="flex mb-6 bg-card rounded-xl p-1 border border-border">
          <button
            onClick={() => { setTab("login"); setError(""); }}
            className={`flex-1 py-2 text-sm font-medium rounded-lg transition-colors ${
              tab === "login"
                ? "bg-background text-foreground shadow-sm"
                : "text-muted hover:text-foreground"
            }`}
          >
            Prijava
          </button>
          <button
            onClick={() => { setTab("register"); setError(""); }}
            className={`flex-1 py-2 text-sm font-medium rounded-lg transition-colors ${
              tab === "register"
                ? "bg-background text-foreground shadow-sm"
                : "text-muted hover:text-foreground"
            }`}
          >
            Registracija
          </button>
        </div>

        {/* Form */}
        <form onSubmit={handleSubmit} className="space-y-4">
          {tab === "register" && (
            <div>
              <label className="block text-sm font-medium mb-1.5">Ime i prezime</label>
              <input
                type="text"
                value={fullName}
                onChange={(e) => setFullName(e.target.value)}
                placeholder="Ivan Horvat"
                className="w-full px-4 py-2.5 rounded-xl border border-border bg-background text-sm focus:outline-none focus:ring-2 focus:ring-accent/20 focus:border-accent transition-colors"
              />
            </div>
          )}

          <div>
            <label className="block text-sm font-medium mb-1.5">Email</label>
            <input
              type="text"
              inputMode="email"
              autoComplete="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") {
                  e.preventDefault();
                  passwordRef.current?.focus();
                }
              }}
              placeholder="vas@email.com"
              className="w-full px-4 py-2.5 rounded-xl border border-border bg-background text-sm focus:outline-none focus:ring-2 focus:ring-accent/20 focus:border-accent transition-colors"
            />
          </div>

          <div>
            <label className="block text-sm font-medium mb-1.5">Lozinka</label>
            <div className="relative">
              <input
                ref={passwordRef}
                type={showPassword ? "text" : "password"}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder={tab === "register" ? "Najmanje 6 znakova" : "Lozinka"}
                className="w-full px-4 py-2.5 pr-11 rounded-xl border border-border bg-background text-sm focus:outline-none focus:ring-2 focus:ring-accent/20 focus:border-accent transition-colors"
              />
              <button
                type="button"
                onClick={() => setShowPassword(!showPassword)}
                className="absolute right-3 top-1/2 -translate-y-1/2 text-muted hover:text-foreground transition-colors"
                tabIndex={-1}
              >
                {showPassword ? (
                  <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M3.98 8.223A10.477 10.477 0 001.934 12C3.226 16.338 7.244 19.5 12 19.5c.993 0 1.953-.138 2.863-.395M6.228 6.228A10.45 10.45 0 0112 4.5c4.756 0 8.773 3.162 10.065 7.498a10.523 10.523 0 01-4.293 5.774M6.228 6.228L3 3m3.228 3.228l3.65 3.65m7.894 7.894L21 21m-3.228-3.228l-3.65-3.65m0 0a3 3 0 10-4.243-4.243m4.242 4.242L9.88 9.88" />
                  </svg>
                ) : (
                  <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M2.036 12.322a1.012 1.012 0 010-.639C3.423 7.51 7.36 4.5 12 4.5c4.638 0 8.573 3.007 9.963 7.178.07.207.07.431 0 .639C20.577 16.49 16.64 19.5 12 19.5c-4.638 0-8.573-3.007-9.963-7.178z" />
                    <path strokeLinecap="round" strokeLinejoin="round" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
                  </svg>
                )}
              </button>
            </div>
          </div>

          {error && (
            <div className="px-4 py-2.5 rounded-xl bg-red-500/10 border border-red-500/20 text-red-600 dark:text-red-400 text-sm">
              {error}
            </div>
          )}

          <button
            type="submit"
            disabled={loading}
            className="w-full py-3 bg-accent text-white rounded-xl font-semibold text-sm hover:bg-accent-hover transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {loading ? (
              <span className="inline-flex items-center gap-2">
                <span className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                {tab === "login" ? "Prijava..." : "Registracija..."}
              </span>
            ) : (
              tab === "login" ? "Prijavi se" : "Registriraj se"
            )}
          </button>
        </form>

        <p className="text-center text-xs text-muted mt-6">
          {tab === "login"
            ? "Nemate račun? "
            : "Već imate račun? "}
          <button
            onClick={() => { setTab(tab === "login" ? "register" : "login"); setError(""); }}
            className="text-accent hover:text-accent-hover font-medium"
          >
            {tab === "login" ? "Registrirajte se" : "Prijavite se"}
          </button>
        </p>
      </div>
    </div>
  );
}
