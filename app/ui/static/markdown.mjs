// The markdown the service writes, read into a tree of plain values that render.js sets as text (D66).
//
// Not a general parser: it reads what the endpoints produce - YAML frontmatter, headings, paragraphs, lists, tables
// and the comments that mark blocks and facets - and it never produces markup. A tag in the text stays text, a
// comment is dropped unless it is one of the service's markers, and a link only becomes one when its target is a web
// address. The service escapes the text of its sources for CommonMark (app/synthesis/safe_markdown.py), so an escape
// reads as the sign it stands for.

const FRONTMATTER = /^---\n([\s\S]*?)\n---(?:\n|$)/;
const HEADING = /^ {0,3}(#{1,6})[ \t]+(.*?)(?:[ \t]+#+)?[ \t]*$/;
// A comment alone on its line; "-->" may not occur inside, or a line that only holds a marked sentence would read as one
const COMMENT_LINE = /^[ \t]*<!--((?:(?!-->)[\s\S])*)-->[ \t]*$/;
const SECTION = /^kompendium:section\s+(.*)$/;
const ATTRIBUTE = /([a-z_]+)=(?:"([^"]*)"|(\S+))/g;
const LIST_ITEM = /^([ \t]*)([-*+]|\d{1,9}[.)])[ \t]+(.*)$/;
const RULE = /^ {0,3}([-*_])(?:[ \t]*\1){2,}[ \t]*$/;
const FENCE = /^ {0,3}(`{3,}|~{3,})/;
const QUOTE = /^ {0,3}>[ \t]?(.*)$/;
const DELIMITER_CELL = /^[ \t]*:?-+:?[ \t]*$/;
const ESCAPABLE = /^[!-/:-@[-`{-~]$/;
const CITATION = /^\[(\d{1,4})\](?!\()/;
// The label the service puts behind a sentence of the model's own knowledge (D56, app/synthesis/citations.py)
const MODEL_KNOWLEDGE_LABEL = /^\[(Modellwissen)\]/;
// The comments around such a sentence, and around one the model concluded (LLM_UNSUPPORTED_SENTENCES=mark)
const MARK_OPEN = /^<!--\s*f:\s*Evidenzgrad=([^\s>]+)\s*-->/;
const MARK_CLOSE = '<!-- /f -->';
const AUTOLINK = /^<(https?:\/\/[^\s<>]+)>/i;
const WEB_SCHEMES = new Set(['http:', 'https:']);

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

function parseBlocks(lines) {
  const blocks = [];
  let i = 0;
  while (i < lines.length) {
    if (!lines[i].trim()) {
      i += 1;
      continue;
    }
    const [block, next] = readBlock(lines, i);
    blocks.push(block);
    i = next;
  }
  return blocks;
}

function readBlock(lines, i) {
  const line = lines[i];
  const comment = COMMENT_LINE.exec(line);
  if (comment) return [commentBlock(comment[1].trim()), i + 1];
  const heading = HEADING.exec(line);
  if (heading) return [{ type: 'heading', level: heading[1].length, children: parseInline(heading[2]) }, i + 1];
  if (FENCE.test(line)) return readFence(lines, i);
  if (isTableStart(lines, i)) return readTable(lines, i);
  if (RULE.test(line)) return [{ type: 'rule' }, i + 1];
  if (LIST_ITEM.test(line)) return readList(lines, i);
  if (QUOTE.test(line)) return readQuote(lines, i);
  return readParagraph(lines, i);
}

function startsBlock(lines, i) {
  const line = lines[i];
  return [COMMENT_LINE, HEADING, FENCE, RULE, LIST_ITEM, QUOTE].some((pattern) => pattern.test(line)) || isTableStart(lines, i);
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

function readQuote(lines, i) {
  const inner = [];
  let next = i;
  while (next < lines.length && QUOTE.test(lines[next])) {
    inner.push(QUOTE.exec(lines[next])[1]);
    next += 1;
  }
  return [{ type: 'quote', blocks: parseBlocks(inner) }, next];
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
  while (next < lines.length && lines[next].includes('|') && lines[next].trim()) {
    const cells = splitRow(lines[next]);
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

function readList(lines, i) {
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
    if (item && indent === base && isOrdered(item[2]) === ordered) {
      items.push({ lines: [item[3]], lists: [] });
      next += 1;
    } else if (item && indent > base && items.length) {
      const [nested, after] = readList(lines, next);
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

function webAddress(url) {
  try {
    const parsed = new URL(url.trim());
    return WEB_SCHEMES.has(parsed.protocol) ? parsed.href : null;
  } catch {
    return null; // no absolute address at all, as "//host/x" or "javascript" without a scheme separator
  }
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
