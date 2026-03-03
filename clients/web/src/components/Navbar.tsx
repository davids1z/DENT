"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

export function Navbar() {
  const pathname = usePathname();

  const links = [
    { href: "/", label: "Dashboard" },
    { href: "/inspect", label: "Nova inspekcija" },
    { href: "/inspections", label: "Inspekcije" },
  ];

  return (
    <nav className="h-16 border-b border-border bg-card/50 backdrop-blur-xl sticky top-0 z-50">
      <div className="max-w-7xl mx-auto px-6 h-full flex items-center justify-between">
        <Link href="/" className="flex items-center gap-3 group">
          <div className="w-8 h-8 rounded-lg bg-accent flex items-center justify-center text-white font-bold text-sm group-hover:shadow-lg group-hover:shadow-accent/25 transition-shadow">
            D
          </div>
          <span className="font-semibold text-lg tracking-tight">DENT</span>
          <span className="text-xs text-muted hidden sm:block">Damage Evaluation & Notification Tool</span>
        </Link>

        <div className="flex items-center gap-1">
          {links.map((link) => (
            <Link
              key={link.href}
              href={link.href}
              className={`px-4 py-2 rounded-lg text-sm font-medium transition-all ${
                pathname === link.href
                  ? "bg-accent/10 text-accent"
                  : "text-muted hover:text-foreground hover:bg-card-hover"
              }`}
            >
              {link.label}
            </Link>
          ))}
        </div>
      </div>
    </nav>
  );
}
