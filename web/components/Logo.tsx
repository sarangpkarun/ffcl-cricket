import { useId } from "react";
import { LOGO } from "@/lib/logo";

/** The FFCL logo for page headers. Decorative: the name is always written next to it. */
export function Logo({ size = 28, className }: { size?: number; className?: string }) {
  const id = useId();
  const L = LOGO;
  return (
    <svg width={size} height={size} viewBox="0 0 512 512" aria-hidden="true" focusable="false" className={className}>
      <defs>
        <linearGradient id={`${id}bg`} x1="0" y1="0" x2="1" y2="1"><stop offset="0" stopColor={L.bgFrom} /><stop offset="1" stopColor={L.bgTo} /></linearGradient>
        <radialGradient id={`${id}ball`} cx="0.35" cy="0.3" r="0.85"><stop offset="0" stopColor={L.ballLight} /><stop offset="1" stopColor={L.ballDark} /></radialGradient>
      </defs>
      <rect width="512" height="512" rx="112" fill={`url(#${id}bg)`} />
      <circle cx="256" cy="256" r="170" fill={`url(#${id}ball)`} />
      {size >= 40 && L.seams.map((d) => <path key={d} d={d} fill="none" stroke={L.seam} strokeWidth="9" strokeLinecap="round" strokeDasharray="2 22" />)}
      <g transform={L.digitTransform} fill="none" stroke={L.digit} strokeWidth={L.digitStroke} strokeLinecap="round">
        <circle cx={L.bowl.cx} cy={L.bowl.cy} r={L.bowl.r} />
        <path d={L.tail} />
      </g>
    </svg>
  );
}
