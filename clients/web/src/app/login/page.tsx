"use client";

import { useState } from "react";
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

  // Redirect if already logged in
  if (user) {
    router.replace("/inspections");
    return null;
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    setLoading(true);

    try {
      if (tab === "login") {
        await login(email, password);
      } else {
        if (!fullName.trim()) {
          setError("Unesite ime i prezime.");
          setLoading(false);
          return;
        }
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
    <div className="min-h-[80vh] flex items-center justify-center px-4">
      <div className="w-full max-w-sm">
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
                ? "bg-white text-foreground shadow-sm"
                : "text-muted hover:text-foreground"
            }`}
          >
            Prijava
          </button>
          <button
            onClick={() => { setTab("register"); setError(""); }}
            className={`flex-1 py-2 text-sm font-medium rounded-lg transition-colors ${
              tab === "register"
                ? "bg-white text-foreground shadow-sm"
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
                className="w-full px-4 py-2.5 rounded-xl border border-border bg-white text-sm focus:outline-none focus:ring-2 focus:ring-accent/20 focus:border-accent transition-colors"
                required
              />
            </div>
          )}

          <div>
            <label className="block text-sm font-medium mb-1.5">Email</label>
            <input
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="vas@email.com"
              className="w-full px-4 py-2.5 rounded-xl border border-border bg-white text-sm focus:outline-none focus:ring-2 focus:ring-accent/20 focus:border-accent transition-colors"
              required
            />
          </div>

          <div>
            <label className="block text-sm font-medium mb-1.5">Lozinka</label>
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="Najmanje 6 znakova"
              className="w-full px-4 py-2.5 rounded-xl border border-border bg-white text-sm focus:outline-none focus:ring-2 focus:ring-accent/20 focus:border-accent transition-colors"
              required
              minLength={6}
            />
          </div>

          {error && (
            <div className="px-4 py-2.5 rounded-xl bg-red-50 border border-red-200 text-red-600 text-sm">
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
