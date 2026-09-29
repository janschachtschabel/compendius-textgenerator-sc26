// Which addresses the review page links to (D66): web addresses only. inline.mjs asks it for every link target
// of the text, dom.mjs for every link it builds, also from the fields of an answer.

const WEB_SCHEMES = new Set(['http:', 'https:']);

/** The address as a link target when it is a web address (http, https), else null: dom.mjs checks every link
 * with it, since fields of an answer such as the ccm:wwwurl of a material are typed by editors. */
export function webAddress(url) {
  const text = String(url ?? '').trim();
  if (!text) return null;
  try {
    const parsed = new URL(text);
    return WEB_SCHEMES.has(parsed.protocol) ? parsed.href : null;
  } catch {
    return null; // no absolute address at all, as "//host/x" or "javascript" without a scheme separator
  }
}
