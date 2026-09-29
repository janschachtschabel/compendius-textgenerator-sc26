// The text inside one block of the service's markdown (D66), read into a tree of plain values: text, strong,
// emphasis, code, links to web addresses, evidence numbers, the label of model knowledge and the sentences marked as
// model knowledge or conclusion. Nothing in it ever becomes markup.
//
// The text need not be well formed - an asterisk inside a line of a source stays one, and a model writes markdown of
// its own - so reading it stays linear in its length: no search for the end of a construct reads a stretch of the
// text twice, and text nested deeper than MAX_DEPTH reads as text.

import { webAddress } from './urls.mjs';

const ESCAPABLE = /^[!-/:-@[-`{-~]$/;
const CITATION = /\[(\d{1,4})\](?!\()/y;
// The label the service puts behind a sentence of the model's own knowledge (D56, app/synthesis/citations.py)
const MODEL_KNOWLEDGE_LABEL = /\[(Modellwissen)\]/y;
// The comments around such a sentence, and around one the model concluded (LLM_UNSUPPORTED_SENTENCES=mark)
const MARK_OPEN = /<!--\s*f:\s*Evidenzgrad=([^\s>]+)\s*-->/y;
const MARK_CLOSE = '<!-- /f -->';
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

// The "]" that closes the "[" at i, or -1; a backslash takes the sign after it out of the count. The scan records
// every pair it passes and every "[" it leaves open, so a "[" inside a stretch already scanned is looked up
function closingBracket(text, i) {
  const pairs = (text.pairs ??= new Map());
  if (!pairs.has(i)) {
    const { s } = text;
    const open = [i];
    for (let k = i + 1; k < s.length && open.length; k += 1) {
      if (s[k] === '\\') k += 1;
      else if (s[k] === '[') open.push(k);
      else if (s[k] === ']') pairs.set(open.pop(), k);
    }
    for (const left of open) pairs.set(left, -1);
  }
  return pairs.get(i);
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

// Past the target: spaces, an optional title in quotes, the closing parenthesis. Several targets can end at one
// place, so each place is read once
function afterTarget(text, k) {
  const tails = (text.tails ??= new Map());
  if (!tails.has(k)) tails.set(k, readTail(text.s, k));
  return tails.get(k);
}

function readTail(s, k) {
  let at = skipBlanks(s, k);
  if (s[at] === '"' || s[at] === "'") {
    const close = s.indexOf(s[at], at + 1);
    if (close < 0) return -1;
    at = skipBlanks(s, close + 1);
  }
  return s[at] === ')' ? at + 1 : -1;
}

function skipBlanks(s, k) {
  let at = k;
  while (s[at] === ' ' || s[at] === '\n') at += 1;
  return at;
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

// A closing delimiter follows the words it ends; a single one that belongs to a double is none
function closes(s, end, strong) {
  if (/\s/.test(s[end - 1] ?? ' ')) return false;
  return strong || (s[end - 1] !== '*' && s[end + 1] !== '*');
}

// Where the next end of a kind lies at or after `from`, or -1. The reader moves only forward, and whether a place
// ends a construct depends on that place alone, so an answer still ahead holds for every later start: a search runs
// only past it, and each kind of end is looked for once over the text
function nextEnd(text, kind, from) {
  const last = text.ends[kind];
  if (last && from >= last.from && (last.at < 0 || last.at >= from)) return last.at;
  const at = FIND[kind](text.s, from);
  text.ends[kind] = { from, at };
  return at;
}

const FIND = {
  em: (s, from) => firstWhere(s, '*', from, (k) => closes(s, k, false)),
  strong: (s, from) => firstWhere(s, '**', from, (k) => closes(s, k, true)),
  comment: (s, from) => s.indexOf('-->', from),
  mark: (s, from) => s.indexOf(MARK_CLOSE, from),
};

function firstWhere(s, sign, from, holds) {
  let at = s.indexOf(sign, from);
  while (at >= 0 && !holds(at)) at = s.indexOf(sign, at + 1);
  return at;
}

// What the reader may ask for out of order - link attempts inside one another start at targets before the last one,
// a code span may start inside a run of backticks after an escaped one - as tables of the text, each built on first
// use in one pass
function table(text, name) {
  text.tables[name] ??= TABLES[name](text.s);
  return text.tables[name];
}

const TABLES = { angleEnds, targetEnds, backticks: backtickRuns };

// For each start the first ">" at or after it, or -1
function angleEnds(s) {
  const ends = new Int32Array(s.length + 1).fill(-1);
  for (let k = s.length - 1; k >= 0; k -= 1) ends[k] = s[k] === '>' ? k : ends[k + 1];
  return ends;
}

// For each start of a plain link target - the first sign after "](" and the spaces behind it - where the target
// ends: at the first space or line break, or at the first ")" that closes no "(" opened after the start, where the
// count of open parentheses falls back to its count at the start. A backslash takes the sign after it out of the
// reading. The starts still open wait on a stack, their counts rising
function targetEnds(s) {
  const ends = new Map(); // a target that runs to the end of the text has none here
  const starts = [];
  const counts = [];
  let open = 0;
  let opened = false;
  for (let k = 0; k < s.length; k += 1) {
    const char = s[k];
    if (opened && char !== ' ') {
      starts.push(k);
      counts.push(open);
      opened = false;
    }
    if (char === '\\') {
      k += 1;
    } else if (char === '(') {
      opened = s[k - 1] === ']';
      open += 1;
    } else if (char === ')') {
      while (counts.length && counts.at(-1) === open) {
        counts.pop();
        ends.set(starts.pop(), k);
      }
      open -= 1;
    } else if (char === ' ' || char === '\n') {
      for (const start of starts) ends.set(start, k);
      starts.length = 0;
      counts.length = 0;
    }
  }
  return ends;
}

// Where the run of backticks that holds each backtick ends, and the starts of the runs of each length
function backtickRuns(s) {
  const ends = new Int32Array(s.length);
  const starts = new Map();
  let k = s.indexOf('`');
  while (k >= 0) {
    let end = k;
    while (s[end] === '`') end += 1;
    ends.fill(end, k, end);
    if (!starts.has(end - k)) starts.set(end - k, []);
    starts.get(end - k).push(k);
    k = s.indexOf('`', end);
  }
  return { ends, starts };
}

// The first of the sorted positions at or after `from`, or -1
function firstFrom(positions = [], from) {
  let low = 0;
  let high = positions.length;
  while (low < high) {
    const middle = (low + high) >> 1;
    if (positions[middle] < from) low = middle + 1;
    else high = middle;
  }
  return low < positions.length ? positions[low] : -1;
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
