// The text inside one block of the service's markdown (D66), read into a tree of plain values: text, strong,
// emphasis, code, links to web addresses, evidence numbers, the label of model knowledge and the sentences marked as
// model knowledge or conclusion. Nothing in it ever becomes markup.
//
// The text need not be well formed - an asterisk inside a line of a source stays one, and a model writes markdown of
// its own - so reading it stays linear in its length: inline_ends.mjs finds where a construct ends without reading a
// stretch of the text twice, and text nested deeper than MAX_DEPTH reads as text.

import { afterTarget, closingBracket, firstFrom, MARK_CLOSE, nextEnd, table } from './inline_ends.mjs';
import { webAddress } from './urls.mjs';

const ESCAPABLE = /^[!-/:-@[-`{-~]$/;
const CITATION = /\[(\d{1,4})\](?!\()/y;
// The label the service puts behind a sentence of the model's own knowledge (D56, app/synthesis/citations.py)
const MODEL_KNOWLEDGE_LABEL = /\[(Modellwissen)\]/y;
// The comments around such a sentence, and around one the model concluded (LLM_UNSUPPORTED_SENTENCES=mark)
const MARK_OPEN = /<!--\s*f:\s*Evidenzgrad=([^\s>]+)\s*-->/y;
const AUTOLINK = /<(https?:\/\/[^\s<>]+)>/iy;
// Deeper than the service ever nests - a link in a marked sentence, emphasis in the link; below it all is text
const MAX_DEPTH = 16;

/** The inline tree of one block's text: text, strong, em, code, links, citations, labels and marked sentences. */
export function parseInline(source) {
  return read(String(source ?? ''), 0);
}

function read(s, depth) {
  const text = { s, depth, ends: {}, tables: {} };
  const out = [];
  let plain = '';
  let i = 0;
  while (i < s.length) {
    const found = depth <= MAX_DEPTH ? special(text, i) : null;
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

function special(text, i) {
  switch (text.s[i]) {
    case '`':
      return codeSpan(text, i);
    case '<':
      return comment(text, i) ?? autolink(text, i);
    case '[':
      return citation(text, i) ?? modelKnowledgeLabel(text, i) ?? link(text, i);
    case '*':
      return emphasis(text, i);
    default:
      return null;
  }
}

function matchAt(pattern, s, i) {
  pattern.lastIndex = i;
  return pattern.exec(s);
}

// A code span ends at the next run of as many backticks as open it; a run with no such closer is text, all of it
function codeSpan(text, i) {
  const { s } = text;
  const runs = table(text, 'backticks');
  const start = runs.ends[i];
  const length = start - i;
  const end = firstFrom(runs.starts.get(length), start);
  if (end < 0) return { nodes: [{ type: 'text', value: s.slice(i, start) }], next: start };
  let value = s.slice(start, end).replace(/\n/g, ' ');
  if (value.length > 2 && value.startsWith(' ') && value.endsWith(' ') && value.trim()) value = value.slice(1, -1);
  return { nodes: [{ type: 'code', value }], next: end + length };
}

function comment(text, i) {
  const { s } = text;
  if (!s.startsWith('<!--', i)) return null;
  const close = nextEnd(text, 'comment', i + 4);
  if (close < 0) return null;
  const mark = matchAt(MARK_OPEN, s, i);
  if (!mark) return { nodes: [], next: close + 3 }; // hidden, as it is from a reader of the rendered text
  const start = i + mark[0].length;
  const end = nextEnd(text, 'mark', start);
  if (end < 0) return { nodes: [], next: start }; // a marker that never closes marks nothing
  return {
    nodes: [{ type: 'mark', grade: mark[1], children: read(s.slice(start, end), text.depth + 1) }],
    next: end + MARK_CLOSE.length,
  };
}

function autolink(text, i) {
  const found = matchAt(AUTOLINK, text.s, i);
  const href = found && webAddress(found[1]);
  return href ? { nodes: [{ type: 'link', href, children: [{ type: 'text', value: found[1] }] }], next: i + found[0].length } : null;
}

function citation(text, i) {
  const found = matchAt(CITATION, text.s, i);
  return found ? { nodes: [{ type: 'cite', number: Number(found[1]) }], next: i + found[0].length } : null;
}

function modelKnowledgeLabel(text, i) {
  const found = matchAt(MODEL_KNOWLEDGE_LABEL, text.s, i);
  return found ? { nodes: [{ type: 'label', value: found[1] }], next: i + found[0].length } : null;
}

function link(text, i) {
  const { s } = text;
  const close = closingBracket(text, i);
  if (close < 0 || s[close + 1] !== '(') return null;
  const target = destination(text, close + 2);
  if (!target) return null;
  const children = read(s.slice(i + 1, close), text.depth + 1);
  const href = webAddress(target.url);
  // Anything but a web address keeps its words and loses its target: the service defuses such links too
  return { nodes: href ? [{ type: 'link', href, children }] : children, next: target.next };
}

// A link target: in angle brackets (the service puts one there that holds spaces or parentheses), or up to the
// parenthesis that closes it, balanced parentheses inside; an optional title is read and dropped
function destination(text, start) {
  const { s } = text;
  let k = start;
  while (s[k] === ' ') k += 1;
  let begin = k;
  let end;
  if (s[k] === '<') {
    begin = k + 1;
    end = table(text, 'angleEnds')[begin];
    if (end < 0) return null;
    k = end + 1;
  } else {
    end = table(text, 'targetEnds').get(begin) ?? s.length;
    k = end;
  }
  const next = afterTarget(text, k);
  if (next < 0) return null;
  return { url: s.slice(begin, end).replace(/\\([!-/:-@[-`{-~])/g, '$1'), next };
}

function emphasis(text, i) {
  const { s } = text;
  const strong = s.startsWith('**', i);
  const mark = strong ? '**' : '*';
  const start = i + mark.length;
  if (!s[start] || /\s/.test(s[start]) || s[start] === '*') return null;
  const end = nextEnd(text, strong ? 'strong' : 'em', start);
  if (end < 0) return null;
  return { nodes: [{ type: strong ? 'strong' : 'em', children: read(s.slice(start, end), text.depth + 1) }], next: end + mark.length };
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
