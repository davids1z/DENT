"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { cn } from "@/lib/cn";
import { useAuth } from "@/lib/auth";
import { getToken } from "@/lib/api";

export function MobileNav() {
  const pathname = usePathname();
  const { user, isLoading } = useAuth();
  const hasToken = typeof window !== "undefined" && !!getToken();
  const showLoggedIn = user || (isLoading && hasToken);

  const links = showLoggedIn
    ? [
        { href: "/", label: "Početna" },
        { href: "/inspect", label: "Upload", primary: true },
        { href: "/inspections", label: "Analize" },
      ]
    : [
        { href: "/", label: "Početna" },
        { href: "/login", label: "Prijava", primary: true },
        { href: "/login", label: "Analize" },
      ];

  return (
    <nav className="fixed bottom-0 left-0 right-0 z-50 md:hidden bg-background border-t border-border" style={{ paddingBottom: "env(safe-area-inset-bottom)" }}>
      <div className="flex items-center justify-around px-2 py-2">
        {links.map((link, i) => {
          const isActive = link.href === "/" ? pathname === "/" : pathname.startsWith(link.href);

          if ('primary' in link && link.primary) {
            return (
              <Link
                key={i}
                href={link.href}
                className="flex flex-col items-center gap-0.5 -mt-4"
              >
                <div className="w-11 h-11 rounded-full bg-accent flex items-center justify-center shadow-sm">
                  {showLoggedIn ? (
                    <svg className="w-5 h-5 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                      <path strokeLinecap="round" strokeLinejoin="round" d="M12 4.5v15m7.5-7.5h-15" />
                    </svg>
                  ) : (
                    <svg className="w-5 h-5 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                      <path strokeLinecap="round" strokeLinejoin="round" d="M15.75 6a3.75 3.75 0 11-7.5 0 3.75 3.75 0 017.5 0zM4.501 20.118a7.5 7.5 0 0114.998 0A17.933 17.933 0 0112 21.75c-2.676 0-5.216-.584-7.499-1.632z" />
                    </svg>
                  )}
                </div>
                <span className="text-[10px] font-medium text-accent">{link.label}</span>
              </Link>
            );
          }

          return (
            <Link
              key={i}
              href={link.href}
              className="flex flex-col items-center gap-0.5 py-1 px-3"
            >
              <span className={cn("text-[10px] font-medium", isActive ? "text-accent" : "text-muted")}>
                {link.label}
              </span>
            </Link>
          );
        })}
      </div>
    </nav>
  );
}
