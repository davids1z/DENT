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

function useDarkMode() {
  const [dark, setDark] = useState(false);

  useEffect(() => {
    const saved = localStorage.getItem("dent_theme");
    if (saved === "dark" || (!saved && window.matchMedia("(prefers-color-scheme: dark)").matches)) {
      document.documentElement.classList.add("dark");
      setDark(true);
    }
  }, []);

  const toggle = useCallback(() => {
    const next = !dark;
    setDark(next);
    if (next) {
      document.documentElement.classList.add("dark");
      document.documentElement.classList.remove("light");
      localStorage.setItem("dent_theme", "dark");
    } else {
      document.documentElement.classList.remove("dark");
      document.documentElement.classList.add("light");
      localStorage.setItem("dent_theme", "light");
    }
  }, [dark]);

  return { dark, toggle };
}

export function Navbar() {
  const pathname = usePathname();
  const { user, logout } = useAuth();
  const [menuOpen, setMenuOpen] = useState(false);
  const { dark, toggle: toggleDark } = useDarkMode();

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

          <button
            onClick={toggleDark}
            className="p-2 rounded-lg text-muted hover:text-foreground hover:bg-card transition-colors"
            title={dark ? "Svijetla tema" : "Tamna tema"}
          >
            {dark ? (
              <svg className="w-4.5 h-4.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M12 3v2.25m6.364.386l-1.591 1.591M21 12h-2.25m-.386 6.364l-1.591-1.591M12 18.75V21m-4.773-4.227l-1.591 1.591M5.25 12H3m4.227-4.773L5.636 5.636M15.75 12a3.75 3.75 0 11-7.5 0 3.75 3.75 0 017.5 0z" />
              </svg>
            ) : (
              <svg className="w-4.5 h-4.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M21.752 15.002A9.718 9.718 0 0118 15.75c-5.385 0-9.75-4.365-9.75-9.75 0-1.33.266-2.597.748-3.752A9.753 9.753 0 003 11.25C3 16.635 7.365 21 12.75 21a9.753 9.753 0 009.002-5.998z" />
              </svg>
            )}
          </button>

          {user ? (
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
                  onClick={() => setMenuOpen(!menuOpen)}
                  className="flex items-center gap-2 px-3 py-1.5 rounded-lg text-sm font-medium text-muted hover:text-foreground hover:bg-card transition-colors"
                >
                  <div className="w-7 h-7 rounded-full bg-accent/10 text-accent flex items-center justify-center text-xs font-bold">
                    {user.fullName.charAt(0).toUpperCase()}
                  </div>
                  <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M19.5 8.25l-7.5 7.5-7.5-7.5" />
                  </svg>
                </button>

                {menuOpen && (
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
          ) : (
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
