"use client";

import { severityLabel } from "@/lib/api";

interface SeverityGaugeProps {
  severity: string;
  size?: number;
}

const SEVERITY_MAP: Record<string, { angle: number; color: string }> = {
  Minor: { angle: 30, color: "#22c55e" },
  Moderate: { angle: 80, color: "#f59e0b" },
  Severe: { angle: 130, color: "#f97316" },
  Critical: { angle: 170, color: "#ef4444" },
};

export function SeverityGauge({ severity, size = 120 }: SeverityGaugeProps) {
  const config = SEVERITY_MAP[severity] || SEVERITY_MAP.Moderate;
  const cx = size / 2;
  const cy = size / 2 + 5;
  const r = size / 2 - 12;
  const strokeWidth = 8;

  function polarToCartesian(angle: number) {
    const rad = (angle * Math.PI) / 180;
    return { x: cx + r * Math.cos(rad), y: cy - r * Math.sin(rad) };
  }

  const bgStart = polarToCartesian(180);
  const bgEnd = polarToCartesian(0);
  const bgArc = `M ${bgStart.x} ${bgStart.y} A ${r} ${r} 0 0 1 ${bgEnd.x} ${bgEnd.y}`;

  const segments = [
    { from: 180, to: 135, color: "#22c55e" },
    { from: 135, to: 90, color: "#f59e0b" },
    { from: 90, to: 45, color: "#f97316" },
    { from: 45, to: 0, color: "#ef4444" },
  ];

  const needleAngle = 180 - config.angle;
  const needleEnd = polarToCartesian(needleAngle);

  return (
    <div className="flex flex-col items-center">
      <svg width={size} height={size / 2 + 20} viewBox={`0 0 ${size} ${size / 2 + 20}`}>
        <path d={bgArc} fill="none" stroke="#e5e7eb" strokeWidth={strokeWidth} strokeLinecap="round" />
        {segments.map((seg, i) => {
          const s = polarToCartesian(seg.from);
          const e = polarToCartesian(seg.to);
          return <path key={i} d={`M ${s.x} ${s.y} A ${r} ${r} 0 0 1 ${e.x} ${e.y}`} fill="none" stroke={seg.color} strokeWidth={strokeWidth} strokeLinecap="round" opacity={0.3} />;
        })}
        <line x1={cx} y1={cy} x2={needleEnd.x} y2={needleEnd.y} stroke={config.color} strokeWidth={2.5} strokeLinecap="round" />
        <circle cx={cx} cy={cy} r={4} fill={config.color} />
      </svg>
      <span className="text-sm font-semibold -mt-1" style={{ color: config.color }}>{severityLabel(severity)}</span>
    </div>
  );
}
