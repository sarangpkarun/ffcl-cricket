import { renderToStaticMarkup } from "react-dom/server";
import { JsonLd, jsonLdText } from "@/components/JsonLd";

test("structured data cannot break out of its script tag", () => {
  const evil = { name: '</script><script>alert(1)</script> & <b>"quote"</b>' + String.fromCharCode(0x2028) };
  const html = renderToStaticMarkup(<JsonLd data={evil} />);
  expect(html.match(/<script/g)).toHaveLength(1); // no second script
  expect(html.match(/<\/script>/g)).toHaveLength(1); // only our own closing tag
  expect(html).not.toContain("<b>");
  const text = jsonLdText(evil);
  expect(JSON.parse(text)).toEqual(evil); // still valid JSON that reads back exactly
  expect(text).not.toMatch(new RegExp("[<>&" + String.fromCharCode(0x2028) + "]"));
});
