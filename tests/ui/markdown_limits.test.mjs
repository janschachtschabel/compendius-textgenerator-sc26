// Text the reader of the review page cannot trust to be well formed (D66): the service escapes what its sources typed,
// but an asterisk inside a line stays one, and a model writes markdown of its own. However the text is made, reading
// it takes time in proportion to its length, not to its square, and nesting cannot exhaust the stack.
import { test } from 'node:test';
import assert from 'node:assert/strict';

import { installDocument } from './dom_stub.mjs';
import { inlineText, parseInline } from '../../app/ui/static/inline.mjs';
import { parseMarkdown } from '../../app/ui/static/markdown.mjs';
import { renderBlocks, renderContext } from '../../app/ui/static/render.mjs';

const SIZE = 60_000;
// A linear reading of 60 KB takes a few milliseconds; the readings these tests guard against took seconds
const BUDGET_MS = 500;
const repeat = (piece, length = SIZE) => piece.repeat(Math.ceil(length / piece.length)).slice(0, length);

function timed(read, input) {
  const start = performance.now();
  const result = read(input);
  return { result, ms: performance.now() - start };
}

const INLINE = {
  'openers of emphasis that never close': repeat('*a '),
  'openers of strong emphasis that never close': repeat('**a '),
  'emphasis and brackets in turn': repeat('*['),
  'brackets that never close': `a${repeat('[')}`,
  'link targets that never end': `a${repeat('[](x')}`,
  'a link target, a long gap and no end': `[a](x${' '.repeat(SIZE)}y`,
  'many link targets before a title that never closes': `${repeat('[](x', SIZE / 2)} "${repeat('a', SIZE / 2)}`,
  'a run of backticks with no closer': `a${repeat('`')}`,
  'a long run of backticks before short ones': `a${repeat('`', SIZE / 2)}${repeat('a`', SIZE / 2)}`,
  'comments that never close': `a${repeat('<!--')}`,
};

for (const [name, input] of Object.entries(INLINE)) {
  test(`the text of a block reads in linear time: ${name}`, () => {
    const { ms } = timed(parseInline, input);

    assert.ok(ms < BUDGET_MS, `${Math.round(ms)} ms for ${input.length} characters`);
  });
}

const BLOCKS = {
  'a heading with a long gap before a last sign': `# a${' '.repeat(SIZE)}#x`,
  'a heading with a long gap before a line separator': `# ${' '.repeat(SIZE)}a\u2028`,
  'a list item with a long gap before a line separator': `- ${' '.repeat(SIZE)}a\u2028`,
  'a block marker holding one long word': `<!-- kompendium:section ${repeat('a')} -->`,
  'a block marker with a long gap before a line separator': `<!-- kompendium:section${' '.repeat(SIZE)}a\u2028 -->`,
};

for (const [name, input] of Object.entries(BLOCKS)) {
  test(`a document reads in linear time: ${name}`, () => {
    const { ms } = timed(parseMarkdown, input);

    assert.ok(ms < BUDGET_MS, `${Math.round(ms)} ms for ${input.length} characters`);
  });
}

test('a short row under a wide header adds no more empty cells than the table has characters', () => {
  const columns = 4000;
  const doc = `${'|a'.repeat(columns)}|\n${'|-'.repeat(columns)}|\n${'|\n'.repeat(columns)}Danach.`;

  const { result, ms } = timed(parseMarkdown, doc);

  const tables = result.blocks.filter((block) => block.type === 'table');
  const cells = tables.reduce((sum, table) => sum + table.rows.length * table.head.length, 0);
  assert.ok(cells <= doc.length, `${cells} cells from ${doc.length} characters`);
  assert.ok(ms < BUDGET_MS, `${Math.round(ms)} ms`);
  assert.equal(result.blocks.at(-1).type, 'paragraph', 'what follows the table is still read');
});

const depth = (nodes) => Math.max(0, ...(nodes ?? []).map((node) => 1 + depth(node.children)));

test('links nested thousands deep keep the stack flat and their words', () => {
  const nested = `${'['.repeat(8000)}Kern${'](https://example.org)'.repeat(8000)}`;

  const nodes = parseInline(nested);

  assert.ok(depth(nodes) <= 20, `nesting ${depth(nodes)}`);
  assert.match(inlineText(nodes), /Kern/);
});

test('lists nested thousands deep keep the stack flat, and every item its words', () => {
  installDocument();
  // One more column of indentation per line, a tab counting four: 2000 levels in half a megabyte
  const indent = (width) => '\t'.repeat(Math.floor(width / 4)) + ' '.repeat(width % 4);
  const doc = Array.from({ length: 2000 }, (_, level) => `${indent(level)}- Punkt${level}`).join('\n');

  const { blocks } = parseMarkdown(doc);
  const host = document.createElement('div');
  host.append(renderBlocks(blocks, renderContext('t')));

  let levels = 0;
  for (let list = blocks[0]; list?.type === 'list'; list = list.items.at(-1).lists[0]) levels += 1;
  assert.ok(levels <= 20, `nesting ${levels}`);
  const items = host.descendants().filter((node) => node.tagName === 'LI');
  assert.equal(items.length, 2000, 'every line stays an item');
  assert.match(host.textContent, /Punkt0Punkt1.*Punkt1999$/);
});

test('quotes nested thousands deep keep the stack flat and their words', () => {
  const { blocks } = parseMarkdown(`${repeat('> ', SIZE)}Kern`);

  let quote = blocks[0];
  let levels = 0;
  while (quote?.type === 'quote') {
    levels += 1;
    quote = quote.blocks[0];
  }
  assert.ok(levels <= 20, `nesting ${levels}`);
  assert.equal(quote.type, 'paragraph');
  assert.match(inlineText(quote.children), /Kern/);
});
