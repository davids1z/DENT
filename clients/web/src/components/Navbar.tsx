"use client";

import { useState, useEffect, useCallback } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { cn } from "@/lib/cn";
import { useAuth } from "@/lib/auth";

const links = [
  { href: "/", label: "Početna" },
  { href: "/inspections", label: "Analize" },
];

export function Navbar() {
  const pathname = usePathname();
  const { user, isLoading, hasToken, logout } = useAuth();
  const [menuOpen, setMenuOpen] = useState(false);

  // Show logged-in layout if user loaded OR token hint exists (prevents flash)
  const showLoggedIn = user || (isLoading && hasToken);

  const closeMenu = useCallback(() => setMenuOpen(false), []);

  useEffect(() => {
    if (!menuOpen) return;
    window.addEventListener("scroll", closeMenu, true);
    return () => window.removeEventListener("scroll", closeMenu, true);
  }, [menuOpen, closeMenu]);

  function isActive(href: string) {
    if (href === "/") return pathname === "/";
    return pathname.startsWith(href);
  }

  return (
    <nav className="h-14 bg-background border-b border-border sticky top-0 z-50">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 h-full flex items-center justify-between">
        <Link href="/" className="flex items-center gap-2.5">
          <div className="w-8 h-8 rounded-lg bg-accent flex items-center justify-center text-white font-bold text-sm">
            D
          </div>
          <span className="font-heading font-bold text-lg tracking-tight">
            DENT
          </span>
          <span className="ml-1.5 px-1.5 py-0.5 text-[10px] font-bold bg-amber-100 text-amber-700 rounded border border-amber-200 uppercase tracking-wider">
            Beta
          </span>
        </Link>

        <div className="hidden md:flex items-center gap-1">
          {links.map((link) => {
            const active = isActive(link.href);
            return (
              <Link
                key={link.href}
                href={link.href}
                className={cn(
                  "px-3.5 py-1.5 rounded-lg text-sm font-medium transition-colors",
                  active
                    ? "bg-accent/10 text-accent"
                    : "text-muted hover:text-foreground"
                )}
              >
                {link.label}
              </Link>
            );
          })}

          {showLoggedIn ? (
            <>
              <Link
                href="/inspect"
                className={cn(
                  "ml-2 px-5 py-2 rounded-lg text-sm font-semibold transition-colors",
                  pathname.startsWith("/inspect") && !pathname.startsWith("/inspections")
                    ? "bg-accent text-white"
                    : "bg-accent text-white hover:bg-accent-hover"
                )}
              >
                Nova provjera
              </Link>

              {/* User menu */}
              <div className="relative ml-2">
                <button
                  onClick={() => user && setMenuOpen(!menuOpen)}
                  className="flex items-center gap-2 px-3 py-1.5 rounded-lg text-sm font-medium text-muted hover:text-foreground hover:bg-card transition-colors"
                >
                  <div className="w-7 h-7 rounded-full bg-accent/10 text-accent flex items-center justify-center text-xs font-bold">
                    {user ? user.fullName.charAt(0).toUpperCase() : ""}
                  </div>
                  <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M19.5 8.25l-7.5 7.5-7.5-7.5" />
                  </svg>
                </button>

                {menuOpen && user && (
                  <>
                    <div className="fixed inset-0 z-40" onClick={() => setMenuOpen(false)} />
                    <div className="absolute right-0 mt-1 w-48 bg-background rounded-xl border border-border shadow-lg z-50 py-1">
                      <div className="px-4 py-2 border-b border-border">
                        <div className="text-sm font-medium truncate">{user.fullName}</div>
                        <div className="text-xs text-muted truncate">{user.email}</div>
                      </div>
                      {user.role === "Admin" && (
                        <Link
                          href="/admin"
                          onClick={() => setMenuOpen(false)}
                          className="block px-4 py-2 text-sm text-muted hover:text-foreground hover:bg-card transition-colors"
                        >
                          Upravljanje korisnicima
                        </Link>
                      )}
                      <button
                        onClick={() => { setMenuOpen(false); logout(); }}
                        className="w-full text-left px-4 py-2 text-sm text-red-500 hover:bg-red-50 transition-colors"
                      >
                        Odjava
                      </button>
                    </div>
                  </>
                )}
              </div>
            </>
          ) : isLoading ? null : (
            <Link
              href="/login"
              className="ml-2 px-5 py-2 rounded-lg text-sm font-semibold bg-accent text-white hover:bg-accent-hover transition-colors"
            >
              Prijava
            </Link>
          )}
        </div>
      </div>
    </nav>
  );
}
