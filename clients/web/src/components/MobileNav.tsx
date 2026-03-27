"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { cn } from "@/lib/cn";
import { useAuth } from "@/lib/auth";

export function MobileNav() {
  const pathname = usePathname();
  const { user, isLoading, hasToken } = useAuth();

  const showLoggedIn = user || (isLoading && hasToken);

  return (
    <nav className="fixed bottom-0 left-0 right-0 z-50 md:hidden bg-background border-t border-border" style={{ paddingBottom: "env(safe-area-inset-bottom)" }}>
      <div className="flex items-center justify-around px-2 py-2">
        {/* Početna */}
        <Link
          href="/"
          className="flex flex-col items-center gap-0.5 py-1 px-3"
        >
          <svg className={cn("w-5 h-5", pathname === "/" ? "text-accent" : "text-muted")} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
            <path strokeLinecap="round" strokeLinejoin="round" d="m2.25 12 8.954-8.955c.44-.439 1.152-.439 1.591 0L21.75 12M4.5 9.75v10.125c0 .621.504 1.125 1.125 1.125H9.75v-4.875c0-.621.504-1.125 1.125-1.125h2.25c.621 0 1.125.504 1.125 1.125V21h4.125c.621 0 1.125-.504 1.125-1.125V9.75M8.25 21h8.25" />
          </svg>
          <span className={cn("text-[10px] font-medium", pathname === "/" ? "text-accent" : "text-muted")}>
            Početna
          </span>
        </Link>

        {/* Primary action */}
        <Link
          href={showLoggedIn ? "/inspect" : "/login"}
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
          <span className="text-[10px] font-medium text-accent">
            {showLoggedIn ? "Upload" : "Prijava"}
          </span>
        </Link>

        {/* Analize */}
        <Link
          href="/inspections"
          className="flex flex-col items-center gap-0.5 py-1 px-3"
        >
          <svg className={cn("w-5 h-5", pathname.startsWith("/inspections") ? "text-accent" : "text-muted")} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M3.75 12h16.5m-16.5 3.75h16.5M3.75 19.5h16.5M5.625 4.5h12.75a1.875 1.875 0 0 1 0 3.75H5.625a1.875 1.875 0 0 1 0-3.75Z" />
          </svg>
          <span className={cn("text-[10px] font-medium", pathname.startsWith("/inspections") ? "text-accent" : "text-muted")}>
            Analize
          </span>
        </Link>
      </div>
    </nav>
  );
}
