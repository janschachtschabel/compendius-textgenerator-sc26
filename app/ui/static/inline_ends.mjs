// Where the constructs of inline.mjs end (D66), found in time linear in the length of the text, however it is
// formed: a search for the end of emphasis or a comment goes on from where the last one of its kind stopped, a scan of
// brackets records every pair it passes, and what the reader asks for out of order is a table built in one pass.
// `text` is the reader's state of one text - { s, depth, ends, tables } - to which these functions add what they found.

// The comment that ends a sentence marked as model knowledge or conclusion
export const MARK_CLOSE = '<!-- /f -->';

// The "]" that closes the "[" at i, or -1; a backslash takes the sign after it out of the count. The scan records
// every pair it passes and every "[" it leaves open, so a "[" inside a stretch already scanned is looked up
export function closingBracket(text, i) {
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

// Past the target: spaces, an optional title in quotes, the closing parenthesis. Several targets can end at one
// place, so each place is read once
export function afterTarget(text, k) {
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

// A closing delimiter follows the words it ends; a single one that belongs to a double is none
function closes(s, end, strong) {
  if (/\s/.test(s[end - 1] ?? ' ')) return false;
  return strong || (s[end - 1] !== '*' && s[end + 1] !== '*');
}

// Where the next end of a kind lies at or after `from`, or -1. The reader moves only forward, and whether a place
// ends a construct depends on that place alone, so an answer still ahead holds for every later start: a search runs
// only past it, and each kind of end is looked for once over the text
export function nextEnd(text, kind, from) {
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
export function table(text, name) {
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
export function firstFrom(positions = [], from) {
  let low = 0;
  let high = positions.length;
  while (low < high) {
    const middle = (low + high) >> 1;
    if (positions[middle] < from) low = middle + 1;
    else high = middle;
  }
  return low < positions.length ? positions[low] : -1;
}
