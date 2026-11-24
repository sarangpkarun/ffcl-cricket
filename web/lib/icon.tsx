import { ImageResponse } from "next/og";
import { logoDataUri } from "@/lib/logo";

/**
 * The app icon at a given size. `bleed` fills the whole square (iPhone home screen and Android adaptive icons, which the
 * phone then rounds or masks itself); otherwise the corners are rounded. Small sizes drop the stitching so the ball stays clear.
 */
export function iconImage(size: number, bleed = false) {
  const src = logoDataUri({ rounded: !bleed, seams: size >= 96 });
  return new ImageResponse(
    (
      // eslint-disable-next-line @next/next/no-img-element -- an image inside a generated image, not a page
      <img src={src} width={size} height={size} alt="" />
    ),
    { width: size, height: size },
  );
}
