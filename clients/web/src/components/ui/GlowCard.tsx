"use client";

import { cn } from "@/lib/cn";

interface GlowCardProps {
  children: React.ReactNode;
  className?: string;
  glowColor?: string;
  padding?: boolean;
}

export function GlowCard({
  children,
  className,
  padding = true,
}: GlowCardProps) {
  return (
    <div
      className={cn(
        "bg-card border border-border rounded-xl",
        padding && "p-5",
        className
      )}
    >
      {children}
    </div>
  );
}
