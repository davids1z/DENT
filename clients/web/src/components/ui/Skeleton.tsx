import { cn } from "@/lib/cn";

interface SkeletonProps {
  className?: string;
  variant?: "text" | "card" | "circle";
}

export function Skeleton({ className, variant = "text" }: SkeletonProps) {
  return (
    <div
      className={cn(
        "skeleton rounded-lg",
        variant === "card" && "rounded-xl",
        variant === "circle" && "rounded-full",
        className
      )}
    />
  );
}
