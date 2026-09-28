// A compendium as a reader sees it, every block of part 1 with how its text came about and where each paragraph
// comes from (D66). What the answer says about its making follows in info_compendium.mjs.

import { h } from './dom.mjs';
import { parseMarkdown, sectionize } from './markdown.mjs';
import { blockOrigin, citationIndex, originCaption, sourceIndex, statusKind } from './provenance.mjs';
import { heading, renderBlock, renderContext } from './render.mjs';
import { formatNumber } from './stats.mjs';
import { KINDS } from './texts.mjs';

// A block assembled from the articles (actors, sources, glossary) or left empty tells its origin once, above it
const WITHOUT_PARAGRAPH_ORIGIN = new Set(['assembled', 'empty']);

/** The document of a compendium; `headings` feed the table of contents. */
export function renderCompendium(answer, idPrefix) {
  const ctx = renderContext(idPrefix, { citations: citationIndex(answer), sources: sourceIndex(answer) });
  ctx.reasons = matchingReasons(answer);
  const { blocks } = parseMarkdown(answer.markdown);
  const sections = new Map((answer.sections ?? []).map((section) => [section.slot_id, section]));
  const document = h('div', { class: 'document' });
  for (const item of sectionize(blocks)) {
    const node = item.type === 'section' ? block(item, sections.get(item.attrs.id), ctx) : renderBlock(item, ctx);
    if (node) document.append(node);
  }
  document.append(ctx.popoverHost);
  return { body: document, headings: ctx.headings };
}

function block(item, data, ctx) {
  const kind = statusKind(item.attrs.status ?? data?.status);
  const section = h('section', { class: `block kind-${kind}`, 'data-block': item.attrs.id });
  if (item.heading) section.append(heading(item.heading.level, item.heading.children, ctx));
  section.append(h('p', { class: 'block-origin' }, h('span', { class: 'kind-badge' }, KINDS[kind].name), KINDS[kind].hint ? ` · ${KINDS[kind].hint}` : '', writing(data?.llm)));
  for (const child of item.blocks) {
    const node = renderBlock(child, ctx);
    if (!node) continue;
    const origin = WITHOUT_PARAGRAPH_ORIGIN.has(kind) ? null : blockOrigin(child, kind, ctx.citations, ctx.sources);
    section.append(origin ? h('div', { class: 'with-origin' }, node, h('p', { class: 'origin' }, originCaption(origin))) : node);
  }
  return section;
}

// What the model did in a block it wrote: which model, what it cost, what the checks took out
function writing(llm) {
  if (!llm) return null;
  const parts = [llm.model, llm.tokens ? `${formatNumber(llm.tokens)} Tokens` : null];
  if (llm.dropped_sentences) parts.push(`${llm.dropped_sentences} Sätze ohne gültigen Beleg verworfen`);
  return ` · ${parts.filter(Boolean).join(', ')}`;
}

// Why a paragraph stands in its block: the score and reasons of the matching, by the paragraph's chunk
function matchingReasons(answer) {
  const reasons = new Map();
  for (const section of answer.sections ?? []) {
    for (const candidate of section.matching?.candidates ?? []) reasons.set(candidate.chunk_id, candidate);
  }
  return reasons;
}
