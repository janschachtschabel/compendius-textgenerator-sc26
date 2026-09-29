// Where each part of a compendium comes from, told from what the answer already carries (D66): the status in the
// marker of a block, the citations of every block with the article and section behind each number, and the marks
// around a sentence the model added from its own knowledge or concluded. It asks the server nothing.

import { label, PROJECTS } from './texts.mjs';

// app/domain/models.py, SectionStatus
const KIND_OF_STATUS = {
  'maschinell-extraktiv': 'extract',
  'ki-ausgewählt': 'selected',
  'ki-generiert': 'written',
  'maschinell-generiert': 'assembled',
  'redaktionell-geprüft': 'reviewed',
  leer: 'empty',
};
const KIND_ORDER = ['extract', 'selected', 'written', 'reviewed', 'assembled', 'unknown'];
const LEADS = {
  extract: 'Wörtlich aus',
  selected: 'Von der KI ausgewählt aus',
  written: 'Von der KI formuliert auf Basis von',
  reviewed: 'Redaktionell geprüft, belegt mit',
  assembled: 'Zusammengestellt aus',
  unknown: 'Belegt mit',
};
const WITHOUT_SOURCE = 'Von der KI aus eigenem Wissen ergänzt';
// The grades of app/synthesis/citations.py: what the model knew, and what it concluded without the evidence saying so
const GRADES = { Modellwissen: 'Modellwissen der KI', Schlussfolgerung: 'Schlussfolgerung der KI' };

// A status the page does not know is unknown - also one named like a property every object has (constructor)
export function statusKind(status) {
  return Object.hasOwn(KIND_OF_STATUS, status) ? KIND_OF_STATUS[status] : 'unknown';
}

/** Every citation of the answer by its number; the numbers run through the whole document. */
export function citationIndex(compendium) {
  const index = new Map();
  for (const section of compendium?.sections ?? []) {
    for (const citation of section.citations ?? []) index.set(citation.number, citation);
  }
  return index;
}

export function sourceIndex(compendium) {
  return new Map((compendium?.sources ?? []).map((source) => [source.source_id, source]));
}

/** How a block came about and which articles it cites, each article and section once, and its sentences without
 * evidence by grade (a Map: a grade is text of the answer); null with nothing to tell. */
export function blockOrigin(block, kind, citations, sources) {
  const found = { numbers: [], marks: new Map() };
  for (const nodes of inlinesOf(block)) collect(nodes, found, false);
  const seen = new Set();
  const cited = [];
  for (const number of found.numbers) {
    const citation = citations.get(number);
    const key = citation && JSON.stringify([citation.source_id, citation.section_heading]);
    if (!citation || seen.has(key)) continue;
    seen.add(key);
    cited.push({
      title: citation.source_title,
      url: citation.source_url,
      heading: citation.section_heading,
      project: projectOf(citation.source_id, sources),
    });
  }
  if (!cited.length && !found.marks.size) return null;
  return { kind, sources: cited, marks: found.marks };
}

/** One line for a reader: how the block came about, from which articles, and what stands in it without a source. */
export function originCaption(origin) {
  const parts = [origin.sources.length ? `${LEADS[origin.kind] ?? LEADS.unknown} ${origin.sources.map(describe).join(' · ')}` : WITHOUT_SOURCE];
  for (const [grade, count] of origin.marks) {
    parts.push(`${count} ${count === 1 ? 'Satz' : 'Sätze'} ${label(GRADES, grade)}, ohne Beleg`);
  }
  return parts.join(' · ');
}

/** How much of part 1 came about in which way, by characters of the blocks' text. */
export function shares(compendium) {
  const chars = new Map();
  for (const section of compendium?.sections ?? []) {
    const length = (section.text ?? '').length;
    if (!length) continue;
    const kind = statusKind(section.status);
    chars.set(kind, (chars.get(kind) ?? 0) + length);
  }
  const total = [...chars.values()].reduce((sum, value) => sum + value, 0);
  return KIND_ORDER.filter((kind) => chars.has(kind)).map((kind) => ({ kind, chars: chars.get(kind), share: chars.get(kind) / total }));
}

function describe(source) {
  const where = [source.project, source.heading].filter(Boolean).join(', ');
  return `„${source.title}“${where ? ` (${where})` : ''}`;
}

function projectOf(sourceId, sources) {
  return label(PROJECTS, sources.get(sourceId)?.project ?? String(sourceId).split(':')[0]);
}

function inlinesOf(block) {
  switch (block.type) {
    case 'paragraph':
    case 'heading':
      return [block.children];
    case 'list':
      return block.items.flatMap((item) => [item.children, ...item.lists.flatMap(inlinesOf)]);
    case 'table':
      return [...block.head, ...block.rows.flat()];
    case 'quote':
      return block.blocks.flatMap(inlinesOf);
    default:
      return [];
  }
}

// The label inside a mark belongs to that mark; one outside of any counts as a sentence of its own
function collect(nodes, found, insideMark) {
  for (const node of nodes ?? []) {
    if (node.type === 'cite') {
      found.numbers.push(node.number);
    } else if (node.type === 'mark') {
      found.marks.set(node.grade, (found.marks.get(node.grade) ?? 0) + 1);
      collect(node.children, found, true);
    } else if (node.type === 'label') {
      if (!insideMark) found.marks.set(node.value, (found.marks.get(node.value) ?? 0) + 1);
    } else {
      collect(node.children, found, insideMark);
    }
  }
}
