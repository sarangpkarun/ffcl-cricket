/**
 * The FFCL logo: a red cricket ball carrying a white "6" (the digit game) on a deep-green pitch.
 * One set of shapes, drawn on a 512 x 512 canvas, used for every icon, the favicon, the share image and the header.
 * The digit is drawn as shapes, not text, so it looks the same everywhere with no font needed.
 */
export const LOGO = {
  bgFrom: "#14532d",
  bgTo: "#052e16",
  ballLight: "#f87171",
  ballDark: "#b91c1c",
  seam: "#fde68a",
  digit: "#ffffff",
  /** the dark green, for browser bars and the phone splash screen */
  brand: "#0f3d2e",
  seams: ["M 132 156 C 176 206 176 306 132 356", "M 380 156 C 336 206 336 306 380 356"],
  bowl: { cx: 50, cy: 92, r: 36 },
  tail: "M 15 96 C 12 48 38 14 86 10",
  digitTransform: "translate(183.5 154.5) scale(1.45)",
  digitStroke: 24,
} as const;

/** The whole logo as an SVG string (for generated icons). `rounded` rounds the corners; maskable and iOS icons are full-bleed. */
export function logoSvg({ rounded = true, seams = true }: { rounded?: boolean; seams?: boolean } = {}): string {
  const L = LOGO;
  return `<svg xmlns="http://www.w3.org/2000/svg" width="512" height="512" viewBox="0 0 512 512">
<defs>
<linearGradient id="bg" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="${L.bgFrom}"/><stop offset="1" stop-color="${L.bgTo}"/></linearGradient>
<radialGradient id="ball" cx="0.35" cy="0.3" r="0.85"><stop offset="0" stop-color="${L.ballLight}"/><stop offset="1" stop-color="${L.ballDark}"/></radialGradient>
</defs>
<rect width="512" height="512" rx="${rounded ? 112 : 0}" fill="url(#bg)"/>
<circle cx="256" cy="256" r="170" fill="url(#ball)"/>
${seams ? L.seams.map((d) => `<path d="${d}" fill="none" stroke="${L.seam}" stroke-width="9" stroke-linecap="round" stroke-dasharray="2 22"/>`).join("\n") : ""}
<g transform="${L.digitTransform}" fill="none" stroke="${L.digit}" stroke-width="${L.digitStroke}" stroke-linecap="round">
<circle cx="${L.bowl.cx}" cy="${L.bowl.cy}" r="${L.bowl.r}"/>
<path d="${L.tail}"/>
</g>
</svg>`;
}

export const logoDataUri = (opts?: Parameters<typeof logoSvg>[0]) => `data:image/svg+xml;base64,${Buffer.from(logoSvg(opts)).toString("base64")}`;
