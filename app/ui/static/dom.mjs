// Building elements for the review page (D66). Text always goes in as text nodes and attributes through
// setAttribute, never through innerHTML: the answers carry text of sources and callers, and none of it may become
// markup. A link only leads to a web address: link() checks every target, as markdown.mjs does.

import { webAddress } from './markdown.mjs';

/** An element with attributes and children; a string child becomes a text node, null and false are skipped.
 * Attribute values of false or null leave the attribute out; `on` maps event names to listeners. */
export function h(tag, attributes = {}, ...children) {
  const element = document.createElement(tag);
  for (const [name, value] of Object.entries(attributes ?? {})) {
    if (name === 'on') {
      for (const [event, listener] of Object.entries(value)) element.addEventListener(event, listener);
    } else if (value !== false && value !== null && value !== undefined) {
      element.setAttribute(name, value === true ? '' : String(value));
    }
  }
  append(element, children);
  return element;
}

export function append(parent, children) {
  for (const child of children.flat(Infinity)) {
    if (child === null || child === undefined || child === false) continue;
    parent.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return parent;
}

/** A link to a web address, opened apart from the page; any other target leaves the words without a link. The
 * service filters the addresses in its markdown, not in the fields of its answers (a material's ccm:wwwurl). */
export function link(href, ...children) {
  const target = webAddress(href);
  return target
    ? h('a', { href: target, target: '_blank', rel: 'noopener noreferrer' }, ...children)
    : h('span', {}, ...children);
}

/** Copy text to the clipboard; false when the browser refuses (no secure context, no permission). */
export async function copyText(value) {
  try {
    await navigator.clipboard.writeText(value);
    return true;
  } catch {
    return false; // the caller says so; the text stays on the page to copy by hand
  }
}

/** Offer text as a file to save. */
export function download(name, value, type = 'application/json') {
  const url = URL.createObjectURL(new Blob([value], { type: `${type};charset=utf-8` }));
  const anchor = h('a', { href: url, download: name });
  document.body.append(anchor);
  anchor.click();
  anchor.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
