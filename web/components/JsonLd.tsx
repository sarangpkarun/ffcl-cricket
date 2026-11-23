/**
 * Structured data for search engines. This is the ONLY place in the app that writes raw markup (the guard test allows
 * just this file). The payload is plain data turned into JSON, and every character that could end the script tag or
 * start markup is escaped, so team and player names can never break out of it.
 */
export function jsonLdText(data: unknown): string {
  return JSON.stringify(data)
    .replace(/</g, "\\u003c")
    .replace(/>/g, "\\u003e")
    .replace(/&/g, "\\u0026")
    .replace(/\u2028/g, "\\u2028")
    .replace(/\u2029/g, "\\u2029");
}

export function JsonLd({ data }: { data: unknown }) {
  return <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: jsonLdText(data) }} />;
}
