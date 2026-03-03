"use client";

import { cn } from "@/lib/cn";

interface GlassPanelProps {
  children: React.ReactNode;
  className?: string;
  hover?: boolean;
  padding?: boolean;
}

export function GlassPanel({
  children,
  className,
  hover = false,
  padding = true,
}: GlassPanelProps) {
  return (
    <div
      className={cn(
        "bg-card border border-border rounded-xl",
        padding && "p-5",
        hover && "hover:bg-card-hover transition-colors",
        className
      )}
    >
      {children}
    </div>
  );
}
