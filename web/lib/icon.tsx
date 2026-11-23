import { ImageResponse } from "next/og";

/** The app icon: a white digit on a dark rounded square. `safe` leaves extra margin for maskable (cropped) icons. */
export function iconImage(size: number, safe = false) {
  const digit = Math.round(size * (safe ? 0.5 : 0.62));
  return new ImageResponse(
    (
      <div style={{ display: "flex", alignItems: "center", justifyContent: "center", width: "100%", height: "100%", background: "#111111", color: "#ffffff", fontSize: digit, fontWeight: 800, borderRadius: safe ? 0 : size * 0.2 }}>
        6
      </div>
    ),
    { width: size, height: size },
  );
}
