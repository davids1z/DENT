"use client";

import { useState, useEffect, useCallback } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { cn } from "@/lib/cn";
import { useAuth } from "@/lib/auth";
import { ThemeToggle } from "./ThemeToggle";

const links = [
  { href: "/", label: "Početna" },
  { href: "/inspections", label: "Analize" },
];

export function Navbar() {
  const pathname = usePathname();
  const { user, isLoading, hasToken, logout } = useAuth();
  const [menuOpen, setMenuOpen] = useState(false);

  const showLoggedIn = user || (isLoading && hasToken);

  const closeMenu = useCallback(() => setMenuOpen(false), []);

  useEffect(() => {
    if (!menuOpen) return;
    const handleClickOutside = (e: MouseEvent) => {
      const target = e.target as HTMLElement;
      if (!target.closest("[data-user-menu]")) closeMenu();
    };
    window.addEventListener("scroll", closeMenu, true);
    document.addEventListener("mousedown", handleClickOutside);
    return () => {
      window.removeEventListener("scroll", closeMenu, true);
      document.removeEventListener("mousedown", handleClickOutside);
    };
  }, [menuOpen, closeMenu]);

  function isActive(href: string) {
    if (href === "/") return pathname === "/";
    return pathname.startsWith(href);
  }

  return (
    <div className="sticky top-0 z-50 px-3 sm:px-4 pt-2.5 pb-1">
      {/* Blur mask behind navbar — hides scrolling content above */}
      <div className="absolute inset-x-0 -top-1 h-[calc(100%+4px)] bg-background/70 backdrop-blur-xl -z-10 mask-b pointer-events-none" />
      <nav className="relative h-12 rounded-full bg-card/90 border border-border/60 backdrop-blur-xl shadow-lg shadow-black/[0.06] dark:shadow-black/25">
        <div className="px-2 sm:px-3 h-full flex items-center justify-between">
          {/* ── Left: Logo ── */}
          <Link href="/" className="flex items-center gap-2 pl-1.5">
            <div className="w-7 h-7 rounded-full bg-accent flex items-center justify-center text-white font-bold text-xs">
              D
            </div>
            <span className="font-heading font-bold text-base tracking-tight">
              DENT
            </span>
            <span className="ml-0.5 px-1.5 py-0.5 text-[9px] font-bold bg-amber-500/15 text-amber-600 dark:text-amber-400 rounded-full border border-amber-500/20 uppercase tracking-wider">
              Beta
            </span>
          </Link>

          {/* ── Right side ── */}
          <div className="flex items-center gap-0.5">
            <ThemeToggle />

            {/* Desktop nav links */}
            <div className="hidden md:flex items-center">
              <div className="w-px h-5 bg-border/50 mx-1" />

              {links.map((link) => {
                const active = isActive(link.href);
                return (
                  <Link
                    key={link.href}
                    href={link.href}
                    className={cn(
                      "px-3 py-1.5 rounded-full text-sm font-medium transition-colors",
                      active
                        ? "text-foreground"
                        : "text-muted hover:text-foreground"
                    )}
                  >
                    {link.label}
                  </Link>
                );
              })}

              {showLoggedIn && (
                <>
                  <div className="w-px h-5 bg-border/50 mx-1" />
                  <Link
                    href="/inspect"
                    className="px-4 py-1.5 rounded-full text-sm font-semibold bg-accent text-white hover:bg-accent-hover transition-colors"
                  >
                    Nova provjera
                  </Link>
                </>
              )}
            </div>

            {/* User menu (all screen sizes) */}
            {showLoggedIn && (
              <div className="relative ml-1" data-user-menu>
                <button
                  onClick={() => user && setMenuOpen(!menuOpen)}
                  className="flex items-center gap-1.5 pl-2.5 pr-1.5 py-1 rounded-full border border-border/50 bg-background/50 hover:bg-background/80 transition-colors"
                >
                  <span className="text-xs font-medium truncate max-w-[120px] hidden sm:block text-muted">
                    {user?.email || ""}
                  </span>
                  <div className="w-7 h-7 rounded-full bg-accent/15 text-accent flex items-center justify-center text-xs font-bold flex-shrink-0">
                    {user ? user.fullName.charAt(0).toUpperCase() : ""}
                  </div>
                </button>

                {menuOpen && user && (
                  <div className="absolute right-0 mt-2 w-52 bg-card/95 backdrop-blur-xl rounded-2xl border border-border/60 shadow-xl z-50 py-1 overflow-hidden">
                    <div className="px-4 py-2.5 border-b border-border/40">
                      <div className="text-sm font-medium truncate">{user.fullName}</div>
                      <div className="text-xs text-muted truncate">{user.email}</div>
                    </div>

                    {/* Mobile nav links in dropdown */}
                    <div className="md:hidden border-b border-border/40">
                      {links.map((link) => (
                        <Link
                          key={link.href}
                          href={link.href}
                          onClick={() => setMenuOpen(false)}
                          className="block px-4 py-2 text-sm text-muted hover:text-foreground hover:bg-background/50 transition-colors"
                        >
                          {link.label}
                        </Link>
                      ))}
                      <Link
                        href="/inspect"
                        onClick={() => setMenuOpen(false)}
                        className="block px-4 py-2 text-sm text-accent font-medium hover:bg-background/50 transition-colors"
                      >
                        Nova provjera
                      </Link>
                    </div>

                    {user.role === "Admin" && (
                      <Link
                        href="/admin"
                        onClick={() => setMenuOpen(false)}
                        className="block px-4 py-2 text-sm text-muted hover:text-foreground hover:bg-background/50 transition-colors"
                      >
                        Admin panel
                      </Link>
                    )}
                    <button
                      onClick={() => { setMenuOpen(false); logout(); }}
                      className="w-full text-left px-4 py-2 text-sm text-red-500 hover:bg-red-500/10 transition-colors"
                    >
                      Odjava
                    </button>
                  </div>
                )}
              </div>
            )}

            {/* Login button (not logged in) */}
            {!showLoggedIn && !isLoading && (
              <Link
                href="/login"
                className="ml-1 px-4 py-1.5 rounded-full bg-accent text-white text-sm font-semibold hover:bg-accent-hover transition-colors"
              >
                Prijava
              </Link>
            )}
          </div>
        </div>
      </nav>
    </div>
  );
}
