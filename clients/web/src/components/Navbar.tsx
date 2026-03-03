"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { cn } from "@/lib/cn";

const links = [
  { href: "/", label: "Početna" },
  { href: "/inspections", label: "Inspekcije" },
];

export function Navbar() {
  const pathname = usePathname();

  function isActive(href: string) {
    if (href === "/") return pathname === "/";
    return pathname.startsWith(href);
  }

  return (
    <nav className="h-14 bg-white border-b border-border sticky top-0 z-50">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 h-full flex items-center justify-between">
        <Link href="/" className="flex items-center gap-2.5">
          <div className="w-8 h-8 rounded-lg bg-accent flex items-center justify-center text-white font-bold text-sm">
            D
          </div>
          <span className="font-heading font-bold text-lg tracking-tight">
            DENT
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
          <Link
            href="/inspect"
            className={cn(
              "ml-2 px-5 py-2 rounded-lg text-sm font-semibold transition-colors",
              pathname.startsWith("/inspect") && !pathname.startsWith("/inspections")
                ? "bg-accent text-white"
                : "bg-accent text-white hover:bg-accent-hover"
            )}
          >
            Nova analiza
          </Link>
        </div>
      </div>
    </nav>
  );
}
