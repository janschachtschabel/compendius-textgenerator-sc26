// The markdown the service writes, read into a tree of plain values that render.mjs sets as text (D66): the blocks
// here, the text inside each block in inline.mjs.
//
// Not a general parser: it reads what the endpoints produce - YAML frontmatter, headings, paragraphs, lists, tables
// and the comments that mark blocks and facets - and it never produces markup. A tag in the text stays text, a
// comment is dropped unless it is one of the service's markers, and a link only becomes one when its target is a web
// address. The service escapes the text of its sources for CommonMark (app/synthesis/safe_markdown.py), so an escape
// reads as the sign it stands for. Every pattern here reads a line in one pass, quotes nested deeper than MAX_DEPTH
// read as paragraphs and list items as items of the deepest list: however badly a text is formed, it takes time in
// proportion to its length, and its nesting cannot exhaust the stack.

import { parseInline } from './inline.mjs';

const FRONTMATTER = /^---\n([\s\S]*?)\n---(?:\n|$)/;
// The text of a line runs to its end, a line separator (U+2028) included, as CommonMark reads it; headingText()
// drops the closing sequence of a heading
const HEADING = /^ {0,3}(#{1,6})[ \t]+(.*)$/s;
// A comment alone on its line; "-->" may not occur inside, or a line that only holds a marked sentence would read as one
const COMMENT_LINE = /^[ \t]*<!--((?:(?!-->)[\s\S])*)-->[ \t]*$/;
const SECTION = /^kompendium:section\s+(.*)$/s;
// A name starts where a word does: tried inside one as well, a long word would be read once per letter
const ATTRIBUTE = /(?<![a-z_])([a-z_]+)=(?:"([^"]*)"|(\S+))/g;
const LIST_ITEM = /^([ \t]*)([-*+]|\d{1,9}[.)])[ \t]+(.*)$/s;
const RULE = /^ {0,3}([-*_])(?:[ \t]*\1){2,}[ \t]*$/;
const FENCE = /^ {0,3}(`{3,}|~{3,})/;
const QUOTE = /^ {0,3}>[ \t]?(.*)$/s;
const DELIMITER_CELL = /^[ \t]*:?-+:?[ \t]*$/;
// Far deeper than the service nests (lists two levels, quotes none); a quote below it reads as a paragraph, a list item
// as an item of the list above. Without it 1,500 levels of lists broke the page's stack
const MAX_DEPTH = 16;

/** The frontmatter (YAML as text, or null) and the blocks of a document. */
export function parseMarkdown(source) {
  const text = String(source ?? '').replace(/\r\n?/g, '\n');
  const front = FRONTMATTER.exec(text);
  const body = front ? text.slice(front[0].length) : text;
  return { frontmatter: front ? front[1] : null, blocks: parseBlocks(body.split('\n')) };
}

/** The blocks of part 1 grouped: from the heading before a block's marker up to the next block or part. */
export function sectionize(blocks) {
  const out = [];
  let current = null;
  for (let i = 0; i < blocks.length; i += 1) {
    const block = blocks[i];
    const next = blocks[i + 1];
    if (block.type === 'heading' && next?.type === 'section') {
      current = { type: 'section', attrs: next.attrs, heading: block, blocks: [] };
      out.push(current);
      i += 1;
      continue;
    }
    if (block.type === 'section') {
      current = { type: 'section', attrs: block.attrs, heading: null, blocks: [] };
      out.push(current);
      continue;
    }
    // A block of part 1 may hold headings of its own (the sources hold "Belegstellen"); a part ends it
    if (block.type === 'heading' && block.level <= 2) current = null;
    (current ? current.blocks : out).push(block);
  }
  return out;
}

function parseBlocks(lines, depth = 0) {
  const blocks = [];
  let i = 0;
  while (i < lines.length) {
    if (!lines[i].trim()) {
      i += 1;
      continue;
    }
    const [block, next] = readBlock(lines, i, depth);
    blocks.push(block);
    i = next;
  }
  return blocks;
}

function readBlock(lines, i, depth) {
  const line = lines[i];
  const comment = COMMENT_LINE.exec(line);
  if (comment) return [commentBlock(comment[1].trim()), i + 1];
  const heading = HEADING.exec(line);
  if (heading) return [{ type: 'heading', level: heading[1].length, children: parseInline(headingText(heading[2])) }, i + 1];
  if (FENCE.test(line)) return readFence(lines, i);
  if (isTableStart(lines, i)) return readTable(lines, i);
  if (RULE.test(line)) return [{ type: 'rule' }, i + 1];
  if (LIST_ITEM.test(line)) return readList(lines, i, depth);
  if (QUOTE.test(line) && depth < MAX_DEPTH) return readQuote(lines, i, depth);
  return readParagraph(lines, i);
}

function startsBlock(lines, i) {
  const line = lines[i];
  return [COMMENT_LINE, HEADING, FENCE, RULE, LIST_ITEM, QUOTE].some((pattern) => pattern.test(line)) || isTableStart(lines, i);
}

// A heading's text without its closing sequence: the hashes at its end that a space sets apart ("## Titel ##")
function headingText(raw) {
  const text = withoutTrailingBlanks(raw);
  let hashes = text.length;
  while (hashes > 0 && text[hashes - 1] === '#') hashes -= 1;
  if (hashes === text.length || hashes === 0 || !' \t'.includes(text[hashes - 1])) return text;
  return withoutTrailingBlanks(text.slice(0, hashes));
}

function withoutTrailingBlanks(text) {
  let end = text.length;
  while (end > 0 && (text[end - 1] === ' ' || text[end - 1] === '\t')) end -= 1;
  return text.slice(0, end);
}

function commentBlock(text) {
  const section = SECTION.exec(text);
  if (!section) return { type: 'comment', text };
  const attrs = {};
  for (const [, name, quoted, plain] of section[1].matchAll(ATTRIBUTE)) attrs[name] = quoted ?? plain;
  return { type: 'section', attrs };
}

function readParagraph(lines, i) {
  const parts = [lines[i].trim()];
  let next = i + 1;
  while (next < lines.length && lines[next].trim() && !startsBlock(lines, next)) {
    parts.push(lines[next].trim());
    next += 1;
  }
  return [{ type: 'paragraph', children: parseInline(parts.join('\n')) }, next];
}

function readFence(lines, i) {
  const marker = FENCE.exec(lines[i])[1];
  const body = [];
  let next = i + 1;
  while (next < lines.length && !lines[next].trim().startsWith(marker)) {
    body.push(lines[next]);
    next += 1;
  }
  return [{ type: 'code', text: body.join('\n') }, Math.min(next + 1, lines.length)];
}

function readQuote(lines, i, depth) {
  const inner = [];
  let next = i;
  while (next < lines.length && QUOTE.test(lines[next])) {
    inner.push(QUOTE.exec(lines[next])[1]);
    next += 1;
  }
  return [{ type: 'quote', blocks: parseBlocks(inner, depth + 1) }, next];
}

function isTableStart(lines, i) {
  if (!lines[i].includes('|') || i + 1 >= lines.length || !lines[i + 1].includes('-')) return false;
  const delimiters = splitRow(lines[i + 1]);
  return delimiters.every((cell) => DELIMITER_CELL.test(cell)) && delimiters.length === splitRow(lines[i]).length;
}

function readTable(lines, i) {
  const head = splitRow(lines[i]);
  const align = splitRow(lines[i + 1]).map(alignment);
  const rows = [];
  let next = i + 2;
  // A short row gets the empty cells it lacks, as GFM reads it - but no more of them in all than the table has
  // characters, or rows of one sign under a wide header would grow it with the square of its length
  let room = lines[i].length + lines[i + 1].length;
  while (next < lines.length && lines[next].includes('|') && lines[next].trim()) {
    const cells = splitRow(lines[next]);
    room += lines[next].length - Math.max(0, head.length - cells.length);
    if (room < 0) break;
    rows.push(head.map((_, column) => parseInline(cells[column] ?? '')));
    next += 1;
  }
  return [{ type: 'table', align, head: head.map((cell) => parseInline(cell)), rows }, next];
}

// The cells of a table row; an escaped pipe is a pipe of the cell's text, as GFM reads it
function splitRow(line) {
  let row = line.trim();
  if (row.startsWith('|')) row = row.slice(1);
  if (row.endsWith('|') && !row.endsWith('\\|')) row = row.slice(0, -1);
  const cells = [];
  let cell = '';
  for (let k = 0; k < row.length; k += 1) {
    if (row[k] === '\\' && row[k + 1] === '|') {
      cell += '|';
      k += 1;
    } else if (row[k] === '|') {
      cells.push(cell.trim());
      cell = '';
    } else {
      cell += row[k];
    }
  }
  cells.push(cell.trim());
  return cells;
}

function alignment(cell) {
  const value = cell.trim();
  const left = value.startsWith(':');
  const right = value.endsWith(':');
  if (left && right) return 'center';
  if (right) return 'right';
  return left ? 'left' : null;
}

function readList(lines, i, depth) {
  const first = LIST_ITEM.exec(lines[i]);
  const base = indentWidth(first[1]);
  const ordered = isOrdered(first[2]);
  const items = [];
  let next = i;
  while (next < lines.length) {
    const line = lines[next];
    if (!line.trim()) {
      const after = LIST_ITEM.exec(lines[next + 1] ?? '');
      if (after && indentWidth(after[1]) >= base && isOrdered(after[2]) === ordered) {
        next += 1; // a loose list goes on after a blank line
        continue;
      }
      break;
    }
    const item = LIST_ITEM.exec(line);
    const indent = item ? indentWidth(item[1]) : 0;
    if (item && ((indent === base && isOrdered(item[2]) === ordered) || (indent > base && depth + 1 >= MAX_DEPTH))) {
      items.push({ lines: [item[3]], lists: [] });
      next += 1;
    } else if (item && indent > base && items.length) {
      const [nested, after] = readList(lines, next, depth + 1);
      items.at(-1).lists.push(nested);
      next = after;
    } else if (!item && items.length && !startsBlock(lines, next)) {
      items.at(-1).lines.push(line.trim()); // a lazy continuation, as CommonMark reads it
      next += 1;
    } else {
      break;
    }
  }
  const parsed = items.map((item) => ({ children: parseInline(item.lines.join('\n')), lists: item.lists }));
  return [{ type: 'list', ordered, items: parsed }, next];
}

function isOrdered(marker) {
  return /\d/.test(marker);
}

function indentWidth(indent) {
  return [...indent].reduce((width, char) => width + (char === '\t' ? 4 : 1), 0);
}

