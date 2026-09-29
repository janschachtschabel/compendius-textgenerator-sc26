// The text inside one block of the service's markdown (D66), read into a tree of plain values: text, strong,
// emphasis, code, links to web addresses, evidence numbers, the label of model knowledge and the sentences marked as
// model knowledge or conclusion. Nothing in it ever becomes markup.

import { webAddress } from './urls.mjs';

const ESCAPABLE = /^[!-/:-@[-`{-~]$/;
const CITATION = /^\[(\d{1,4})\](?!\()/;
// The label the service puts behind a sentence of the model's own knowledge (D56, app/synthesis/citations.py)
const MODEL_KNOWLEDGE_LABEL = /^\[(Modellwissen)\]/;
// The comments around such a sentence, and around one the model concluded (LLM_UNSUPPORTED_SENTENCES=mark)
const MARK_OPEN = /^<!--\s*f:\s*Evidenzgrad=([^\s>]+)\s*-->/;
const MARK_CLOSE = '<!-- /f -->';
const AUTOLINK = /^<(https?:\/\/[^\s<>]+)>/i;

/** The inline tree of one block's text: text, strong, em, code, links, citations, labels and marked sentences. */
export function parseInline(source) {
  const s = String(source ?? '');
  const out = [];
  let plain = '';
  let i = 0;
  while (i < s.length) {
    const found = special(s, i);
    if (found) {
      if (plain) out.push({ type: 'text', value: plain });
      plain = '';
      out.push(...found.nodes);
      i = found.next;
    } else if (s[i] === '\\' && ESCAPABLE.test(s[i + 1] ?? '')) {
      plain += s[i + 1];
      i += 2;
    } else {
      plain += s[i] === '\n' ? ' ' : s[i];
      i += 1;
    }
  }
  if (plain) out.push({ type: 'text', value: plain });
  return merged(out);
}

function special(s, i) {
  switch (s[i]) {
    case '`':
      return codeSpan(s, i);
    case '<':
      return comment(s, i) ?? autolink(s, i);
    case '[':
      return citation(s, i) ?? modelKnowledgeLabel(s, i) ?? link(s, i);
    case '*':
      return emphasis(s, i);
    default:
      return null;
  }
}

function codeSpan(s, i) {
  const run = /^`+/.exec(s.slice(i))[0];
  let end = s.indexOf(run, i + run.length);
  while (end >= 0 && s[end + run.length] === '`') end = s.indexOf(run, end + run.length + 1);
  if (end < 0) return null;
  let value = s.slice(i + run.length, end).replace(/\n/g, ' ');
  if (value.length > 2 && value.startsWith(' ') && value.endsWith(' ') && value.trim()) value = value.slice(1, -1);
  return { nodes: [{ type: 'code', value }], next: end + run.length };
}

function comment(s, i) {
  if (!s.startsWith('<!--', i)) return null;
  const close = s.indexOf('-->', i + 4);
  if (close < 0) return null;
  const mark = MARK_OPEN.exec(s.slice(i));
  if (!mark) return { nodes: [], next: close + 3 }; // hidden, as it is from a reader of the rendered text
  const start = i + mark[0].length;
  const end = s.indexOf(MARK_CLOSE, start);
  if (end < 0) return { nodes: [], next: start }; // a marker that never closes marks nothing
  return {
    nodes: [{ type: 'mark', grade: mark[1], children: parseInline(s.slice(start, end)) }],
    next: end + MARK_CLOSE.length,
  };
}

function autolink(s, i) {
  const found = AUTOLINK.exec(s.slice(i));
  const href = found && webAddress(found[1]);
  return href ? { nodes: [{ type: 'link', href, children: [{ type: 'text', value: found[1] }] }], next: i + found[0].length } : null;
}

function citation(s, i) {
  const found = CITATION.exec(s.slice(i));
  return found ? { nodes: [{ type: 'cite', number: Number(found[1]) }], next: i + found[0].length } : null;
}

function modelKnowledgeLabel(s, i) {
  const found = MODEL_KNOWLEDGE_LABEL.exec(s.slice(i));
  return found ? { nodes: [{ type: 'label', value: found[1] }], next: i + found[0].length } : null;
}

function link(s, i) {
  const close = matchingBracket(s, i);
  if (close < 0 || s[close + 1] !== '(') return null;
  const target = destination(s, close + 2);
  if (!target) return null;
  const children = parseInline(s.slice(i + 1, close));
  const href = webAddress(target.url);
  // Anything but a web address keeps its words and loses its target: the service defuses such links too
  return { nodes: href ? [{ type: 'link', href, children }] : children, next: target.next };
}

function matchingBracket(s, i) {
  let depth = 0;
  for (let k = i; k < s.length; k += 1) {
    if (s[k] === '\\') {
      k += 1;
    } else if (s[k] === '[') {
      depth += 1;
    } else if (s[k] === ']') {
      depth -= 1;
      if (depth === 0) return k;
    }
  }
  return -1;
}

// A link target: in angle brackets (the service puts one there that holds spaces or parentheses), or up to the
// parenthesis that closes it, one level of balanced parentheses inside; an optional title is read and dropped
function destination(s, start) {
  let k = start;
  while (s[k] === ' ') k += 1;
  let url;
  if (s[k] === '<') {
    const end = s.indexOf('>', k + 1);
    if (end < 0) return null;
    url = s.slice(k + 1, end);
    k = end + 1;
  } else {
    const begin = k;
    let depth = 0;
    for (; k < s.length; k += 1) {
      const char = s[k];
      if (char === '\\') {
        k += 1;
      } else if (char === '(') {
        depth += 1;
      } else if (char === ')') {
        if (depth === 0) break;
        depth -= 1;
      } else if (char === ' ' || char === '\n') {
        break;
      }
    }
    url = s.slice(begin, k);
  }
  const rest = /^[ \n]*(?:"[^"]*"|'[^']*')?[ \n]*\)/.exec(s.slice(k));
  if (!rest) return null;
  return { url: url.replace(/\\([!-/:-@[-`{-~])/g, '$1'), next: k + rest[0].length };
}

function emphasis(s, i) {
  const strong = s.startsWith('**', i);
  const mark = strong ? '**' : '*';
  const start = i + mark.length;
  if (!s[start] || /\s/.test(s[start]) || s[start] === '*') return null;
  let end = s.indexOf(mark, start);
  while (end >= 0 && !closes(s, end, strong)) end = s.indexOf(mark, end + 1);
  if (end < 0) return null;
  return { nodes: [{ type: strong ? 'strong' : 'em', children: parseInline(s.slice(start, end)) }], next: end + mark.length };
}

// A closing delimiter follows the words it ends; a single one that belongs to a double is none
function closes(s, end, strong) {
  if (/\s/.test(s[end - 1] ?? ' ')) return false;
  return strong || (s[end - 1] !== '*' && s[end + 1] !== '*');
}

function merged(nodes) {
  const out = [];
  for (const node of nodes) {
    const last = out.at(-1);
    if (node.type === 'text' && last?.type === 'text') last.value += node.value;
    else out.push(node);
  }
  return out;
}

/** The words of an inline tree as a reader sees them; a citation reads as its number in brackets. */
export function inlineText(nodes) {
  return (nodes ?? [])
    .map((node) => {
      switch (node.type) {
        case 'text':
        case 'code':
          return node.value;
        case 'cite':
          return `[${node.number}]`;
        case 'label':
          return `[${node.value}]`;
        default:
          return inlineText(node.children);
      }
    })
    .join('');
}
