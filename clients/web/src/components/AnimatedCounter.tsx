"use client";

import { useEffect, useRef, useState } from "react";

interface AnimatedCounterProps {
  value: string;
  className?: string;
}

export function AnimatedCounter({ value, className }: AnimatedCounterProps) {
  const [display, setDisplay] = useState(value);
  const [triggered, setTriggered] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  // Check if value is numeric
  const numericValue = parseInt(value, 10);
  const isNumeric = !isNaN(numericValue) && String(numericValue) === value;

  useEffect(() => {
    const el = ref.current;
    if (!el || !isNumeric) return;

    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting && !triggered) {
          setTriggered(true);
          observer.unobserve(el);

          // Animate from 0 to numericValue
          const duration = 1200;
          const start = performance.now();
          setDisplay("0");

          const tick = (now: number) => {
            const elapsed = now - start;
            const progress = Math.min(elapsed / duration, 1);
            // Ease out cubic
            const eased = 1 - Math.pow(1 - progress, 3);
            setDisplay(String(Math.round(numericValue * eased)));
            if (progress < 1) requestAnimationFrame(tick);
          };

          requestAnimationFrame(tick);
        }
      },
      { threshold: 0.3 }
    );

    observer.observe(el);
    return () => observer.disconnect();
  }, [isNumeric, numericValue, triggered]);

  // Non-numeric values: just reveal with CSS
  if (!isNumeric) {
    return <div ref={ref} className={className}>{value}</div>;
  }

  return <div ref={ref} className={className}>{display}</div>;
}
