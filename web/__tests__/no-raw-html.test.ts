import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";

/** Security guard (docs/SECURITY.md): user text must only ever be rendered as text, never as HTML. */
function sources(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const p = join(dir, name);
    if (statSync(p).isDirectory()) return sources(p);
    return /\.(tsx?|jsx?)$/.test(name) ? [p] : [];
  });
}

test("no component renders raw HTML or evaluates strings", () => {
  const files = ["app", "components", "lib"].flatMap((d) => sources(join(process.cwd(), d)));
  expect(files.length).toBeGreaterThan(20);
  const allowed = join(process.cwd(), "components", "JsonLd.tsx"); // escaped JSON for search engines, tested in jsonld.test.tsx
  const bad = files.filter((f) => f !== allowed && /dangerouslySetInnerHTML|\.innerHTML\s*=|\beval\(|new Function\(|document\.write\(/.test(readFileSync(f, "utf8")));
  expect(bad).toEqual([]);
});
