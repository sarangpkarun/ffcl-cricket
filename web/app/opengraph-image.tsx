import { ImageResponse } from "next/og";
import { LOGO, logoDataUri } from "@/lib/logo";

export const alt = "FFCL digit cricket league";
export const size = { width: 1200, height: 630 };
export const contentType = "image/png";

export default function Image() {
  return new ImageResponse(
    (
      <div style={{ display: "flex", alignItems: "center", width: "100%", height: "100%", background: "#faf7f0", color: LOGO.brand, padding: 80 }}>
        <img src={logoDataUri()} width={360} height={360} alt="" />
        <div style={{ display: "flex", flexDirection: "column", marginLeft: 70 }}>
          <div style={{ fontSize: 130, fontWeight: 800 }}>FFCL</div>
          <div style={{ fontSize: 48, marginTop: 12 }}>Digit cricket league</div>
          <div style={{ fontSize: 30, marginTop: 36, color: "#4b5563" }}>Live scores · points table · fixtures · stats</div>
        </div>
      </div>
    ),
    size,
  );
}
