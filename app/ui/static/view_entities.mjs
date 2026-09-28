// Entities of a text (D66): the text with each entity marked where it stands, then every entity with its kind, the
// way that found it, the article behind it and its identifiers.

import { h, link } from './dom.mjs';
import { facts, infoPart, technical } from './panels.mjs';
import { formatNumber } from './stats.mjs';
import { ENTITY_KINDS, ENTITY_METHODS, label } from './texts.mjs';

export function renderEntities(answer, run) {
  const entities = answer.entities ?? [];
  // start and end count in the text of the answer when the service read another than the one sent (a node, or
  // the sent text in one spelling)
  const text = answer.text ?? run.request.body?.text ?? '';
  const body = h(
    'div',
    { class: 'document' },
    h('h2', {}, 'Entitäten im Text'),
    answer.note ? h('p', { class: 'note' }, answer.note) : null,
    h('p', { class: 'entity-text' }, marked(text, entities)),
    entities.length ? table(entities) : h('p', {}, 'Keine Entitäten gefunden.'),
  );
  const llm = answer.llm;
  const info = h(
    'section',
    { class: 'info' },
    h('h2', {}, 'Wie kamen die Entitäten zustande?'),
    infoPart(
      'Wege und Prüfung',
      facts([
        ['Gelaufen', (answer.methods ?? []).map((method) => label(ENTITY_METHODS, method))],
        ['Archive', answer.archives],
        ['Knoten', answer.node ? link(answer.node.render_url, answer.node.title) : null],
        ['Von der KI genannt', llm ? String(llm.named) : null],
        ['Von der KI geprüft', llm ? String(llm.checked) : null],
        ['Verworfen', llm?.dropped],
        ['Modell', llm?.model],
        ['Warum ohne KI', llm?.fallback],
        ['Tokens', llm ? `${formatNumber(llm.total_tokens)} in ${llm.calls} Aufrufen` : 'keine'],
      ]),
    ),
    technical(run),
  );
  return { body, info };
}

/** The text in pieces, each entity one of them. start and end count code points, as the service (Python) does,
 * not the UTF-16 units of a JavaScript string: after an emoji those would be off. An entity overlapping one before
 * it, or reaching past the text, stays unmarked. */
export function segments(text, entities) {
  const chars = Array.from(String(text ?? ''));
  const parts = [];
  let at = 0;
  for (const entity of [...entities].sort((a, b) => a.start - b.start)) {
    if (entity.start < at || entity.end > chars.length || entity.end <= entity.start) continue;
    if (entity.start > at) parts.push({ text: chars.slice(at, entity.start).join('') });
    parts.push({ text: chars.slice(entity.start, entity.end).join(''), entity });
    at = entity.end;
  }
  if (at < chars.length) parts.push({ text: chars.slice(at).join('') });
  return parts;
}

function marked(text, entities) {
  return segments(text, entities).map((part) =>
    part.entity ? h('mark', { class: `entity kind-${part.entity.kind || 'term'}` }, part.text) : part.text,
  );
}

function table(entities) {
  return h(
    'div',
    { class: 'table-wrap' },
    h(
      'table',
      { class: 'entities' },
      h('thead', {}, h('tr', {}, ['Entität', 'Art', 'Gefunden durch', 'Artikel', 'Kennungen'].map((name) => h('th', { scope: 'col' }, name)))),
      h(
        'tbody',
        {},
        entities.map((entity) =>
          h(
            'tr',
            {},
            h('td', {}, entity.text),
            h('td', {}, entity.kind ? label(ENTITY_KINDS, entity.kind) : entity.article?.kind ?? 'Begriff'),
            h('td', {}, label(ENTITY_METHODS, entity.source)),
            h('td', {}, entity.article ? [link(entity.article.url, entity.article.title), h('span', { class: 'lead' }, entity.article.lead)] : 'nicht verknüpft'),
            h('td', {}, identifiers(entity.article?.ids)),
          ),
        ),
      ),
    ),
  );
}

function identifiers(ids) {
  if (!ids) return '–';
  const named = [
    ids.gnd ? ['GND', `https://d-nb.info/gnd/${ids.gnd}`] : null,
    ids.wikidata ? ['Wikidata', `https://www.wikidata.org/wiki/${ids.wikidata}`] : null,
    ids.viaf ? ['VIAF', `https://viaf.org/viaf/${ids.viaf}`] : null,
    ids.dbpedia ? ['DBpedia', ids.dbpedia] : null,
  ].filter(Boolean);
  return h('ul', { class: 'ids' }, named.map(([name, href]) => h('li', {}, link(href, name))));
}
