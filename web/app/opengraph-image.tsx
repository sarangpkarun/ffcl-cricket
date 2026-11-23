import { ImageResponse } from "next/og";

export const alt = "FFCL digit cricket league";
export const size = { width: 1200, height: 630 };
export const contentType = "image/png";

export default function Image() {
  return new ImageResponse(
    (
      <div style={{ display: "flex", flexDirection: "column", justifyContent: "center", width: "100%", height: "100%", background: "#111", color: "#fff", padding: 80 }}>
        <div style={{ fontSize: 120, fontWeight: 800 }}>FFCL</div>
        <div style={{ fontSize: 48, marginTop: 16 }}>Digit cricket league</div>
        <div style={{ fontSize: 30, marginTop: 40, color: "#bbb" }}>Live scores · points table · fixtures · stats</div>
      </div>
    ),
    size,
  );
}
