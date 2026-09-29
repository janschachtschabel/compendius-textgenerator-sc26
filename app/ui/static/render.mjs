// The tree of markdown.mjs as elements of the page (D66). Every text is set as text; a citation becomes a button
// that opens the article, section and excerpt behind its number, and a sentence of the model's own knowledge is
// marked. Headings go one level down, so the page keeps its own h1, and are collected for a table of contents.

import { h, link } from './dom.mjs';
import { inlineText } from './inline.mjs';
import { label, PROJECTS } from './texts.mjs';

const SCORE = new Intl.NumberFormat('de-DE', { maximumFractionDigits: 2 });

/** What a rendering needs besides the tree: the citations and sources of the answer, ids that stay unique when two
 * answers stand side by side, and a place for the boxes the citation buttons open. A view may add `reasons`, the
 * matching candidates by chunk id, to say in each box why the paragraph stands where it does. */
export function renderContext(idPrefix, { citations = new Map(), sources = new Map() } = {}) {
  return { idPrefix, citations, sources, headings: [], popovers: new Map(), popoverHost: h('div', { class: 'popovers' }) };
}

export function renderBlocks(blocks, ctx) {
  const fragment = document.createDocumentFragment();
  for (const block of blocks) {
    const node = renderBlock(block, ctx);
    if (node) fragment.append(node);
  }
  return fragment;
}

export function renderBlock(block, ctx) {
  switch (block.type) {
    case 'heading':
      return heading(block.level, block.children, ctx);
    case 'paragraph':
      return h('p', {}, renderInlines(block.children, ctx));
    case 'list':
      return list(block, ctx);
    case 'table':
      return table(block, ctx);
    case 'quote':
      return h('blockquote', {}, renderBlocks(block.blocks, ctx));
    case 'code':
      return h('pre', {}, h('code', {}, block.text));
    case 'rule':
      return h('hr');
    default:
      return null; // markers and comments: what they say, the views show in their own way
  }
}

export function heading(level, children, ctx) {
  const id = `${ctx.idPrefix}-h${ctx.headings.length}`;
  ctx.headings.push({ level, id, text: inlineText(children) });
  return h(`h${Math.min(level + 1, 6)}`, { id }, renderInlines(children, ctx));
}

export function renderInlines(nodes, ctx) {
  const fragment = document.createDocumentFragment();
  for (const node of nodes ?? []) fragment.append(inline(node, ctx));
  return fragment;
}

function inline(node, ctx) {
  switch (node.type) {
    case 'text':
      return document.createTextNode(node.value);
    case 'strong':
      return h('strong', {}, renderInlines(node.children, ctx));
    case 'em':
      return h('em', {}, renderInlines(node.children, ctx));
    case 'code':
      return h('code', {}, node.value);
    case 'link':
      return link(node.href, renderInlines(node.children, ctx));
    case 'cite':
      return citation(node.number, ctx);
    case 'label':
      // The brackets stay in the text, as the service writes it; with the origin shown the label reads as a badge
      return h('span', { class: 'mk-label' }, h('span', { class: 'bracket' }, '['), node.value, h('span', { class: 'bracket' }, ']'));
    case 'mark':
      return h('span', { class: `mark mark-${node.grade.toLowerCase()}` }, renderInlines(node.children, ctx));
    default:
      return document.createTextNode('');
  }
}

function list(block, ctx) {
  const items = block.items.map((item) =>
    h('li', {}, renderInlines(item.children, ctx), item.lists.map((nested) => list(nested, ctx))),
  );
  return h(block.ordered ? 'ol' : 'ul', {}, items);
}

function table(block, ctx) {
  const cell = (tag, nodes, column) => h(tag, { class: block.align[column] ? `align-${block.align[column]}` : null }, renderInlines(nodes, ctx));
  return h(
    'div',
    { class: 'table-wrap' },
    h(
      'table',
      {},
      h('thead', {}, h('tr', {}, block.head.map((nodes, column) => cell('th', nodes, column)))),
      h('tbody', {}, block.rows.map((row) => h('tr', {}, row.map((nodes, column) => cell('td', nodes, column))))),
    ),
  );
}

function citation(number, ctx) {
  const found = ctx.citations.get(number);
  if (!found) return h('span', { class: 'cite-ref' }, `[${number}]`);
  const where = [label(PROJECTS, projectOf(found, ctx)), found.section_heading].filter(Boolean).join(', ');
  return h(
    'span',
    { class: 'cite-ref' },
    h('button', { type: 'button', class: 'cite', popovertarget: popover(number, found, where, ctx), 'aria-label': `Beleg ${number}: „${found.source_title}“, ${where}` }, String(number)),
  );
}

// One box per number and answer, made when the number first occurs
function popover(number, found, where, ctx) {
  const id = `${ctx.idPrefix}-beleg-${number}`;
  if (!ctx.popovers.has(number)) {
    const box = h(
      'div',
      { id, popover: 'auto', class: 'cite-popover' },
      h('p', { class: 'pop-head' }, `Beleg ${number}`),
      h('p', { class: 'pop-source' }, link(found.source_url, `„${found.source_title}“`), ` · ${where}`),
      found.snippet ? h('blockquote', { class: 'pop-snippet' }, found.snippet) : null,
      why(ctx.reasons?.get(found.chunk_id)),
      h('button', { type: 'button', class: 'pop-close', popovertarget: id, popovertargetaction: 'hide' }, 'Schließen'),
    );
    ctx.popovers.set(number, box);
    ctx.popoverHost.append(box);
  }
  return id;
}

// The matching's account of why the paragraph stands in its block (the reasons of app/matching), where it gave one
function why(candidate) {
  if (!candidate?.reasons?.length) return null;
  return h('p', { class: 'pop-why' }, `Zugeordnet mit Wert ${SCORE.format(candidate.score)}: ${candidate.reasons.join(', ')}`);
}

function projectOf(found, ctx) {
  return ctx.sources.get(found.source_id)?.project ?? String(found.source_id).split(':')[0];
}
