// The pieces every answer shares on the review page (D66): the metrics bar, the comparison of two answers, the
// collapsible parts of the info section, the technical details for a report, and the box that explains an error.

import { h, link } from './dom.mjs';
import { label, PROJECTS, RESOLUTION } from './texts.mjs';

const DIMENSIONS = { quality: 'Qualität', time: 'Zeit', cost: 'Kosten' };

/** The headline metrics of an answer, grouped by quality, time and cost. */
export function metricsBar(items) {
  const groups = Object.entries(DIMENSIONS).map(([dimension, name]) => {
    const shown = items.filter((item) => item.dimension === dimension && item.headline);
    if (!shown.length) return null;
    return h(
      'div',
      { class: `metric-group dim-${dimension}` },
      h('dt', {}, name),
      shown.map((item) => h('dd', {}, h('span', { class: 'metric-label' }, item.label), h('span', { class: 'metric-value' }, item.display))),
    );
  });
  return h('dl', { class: 'metrics' }, groups);
}

/** Every metric of two or more answers side by side; a metric one of them lacks shows a dash. */
export function compareTable(names, lists) {
  const keys = [...new Set(lists.flatMap((items) => items.map((item) => item.key)))];
  const byKey = lists.map((items) => new Map(items.map((item) => [item.key, item])));
  const rows = keys.map((key) => {
    const first = byKey.find((map) => map.has(key)).get(key);
    return h(
      'tr',
      {},
      h('th', { scope: 'row' }, h('span', { class: `dim dim-${first.dimension}` }, DIMENSIONS[first.dimension]), first.label),
      byKey.map((map) => h('td', {}, map.get(key)?.display ?? '–')),
    );
  });
  return h(
    'div',
    { class: 'table-wrap compare-wrap' },
    h(
      'table',
      { class: 'compare' },
      h('caption', {}, 'Gegenüberstellung: Qualität, Zeit, Kosten'),
      h('thead', {}, h('tr', {}, h('th', { scope: 'col' }, 'Kennzahl'), names.map((name) => h('th', { scope: 'col' }, name)))),
      h('tbody', {}, rows),
    ),
  );
}

/** A collapsible part of the info section below an answer. */
export function infoPart(title, ...content) {
  return h('details', { class: 'info-part' }, h('summary', {}, title), h('div', { class: 'info-body' }, ...content));
}

/** Names and values; an empty value leaves its row out. */
export function facts(pairs) {
  const rows = pairs
    .filter(([, value]) => value !== null && value !== undefined && value !== '' && !(Array.isArray(value) && !value.length))
    .map(([name, value]) => h('div', {}, h('dt', {}, name), h('dd', {}, Array.isArray(value) ? value.join(', ') : value)));
  return rows.length ? h('dl', { class: 'facts' }, rows) : null;
}

/** How the topic of an answer was found, as facts(): the same in every view, a compendium adds its own. */
export function resolutionFacts(answer) {
  const r = answer.resolution ?? {};
  const node = answer.node;
  return [
    ['Gesucht', r.query],
    ['Gefunden', r.title ? `„${r.title}“ (${label(PROJECTS, r.project)})` : 'kein Artikel'],
    ['Weg', r.method ? `${label(RESOLUTION, r.method)}, ${r.confident ? 'sicher' : 'unsicher'}` : null],
    ['Kontextwörter', r.context],
    ['Andere Kandidaten', r.alternatives],
    ['Knoten', node ? link(node.render_url, `${node.title} (${node.kind === 'collection' ? 'Sammlung' : 'Material'})`) : null],
    ['Archive', answer.archives],
  ];
}

/** What someone reporting a finding needs: the request as sent, the id the server logged it under, and more. */
export function technical(run, extra = []) {
  const sent = run.request.body ?? run.request.query;
  return infoPart(
    'Technische Angaben',
    facts([
      ['Anfrage-ID', run.requestId],
      ['Adresse', `${run.request.method} /${run.request.path}`],
    ]),
    h('p', { class: 'tech-label' }, 'Gesendete Anfrage'),
    h('pre', { class: 'json' }, JSON.stringify(sent, null, 2)),
    extra.map(([title, value]) => [h('p', { class: 'tech-label' }, title), h('pre', { class: 'json' }, typeof value === 'string' ? value : JSON.stringify(value, null, 2))]),
  );
}

/** An error in plain words, with what the server said; a topic it did not find offers the alternatives it knows. */
export function errorBox(error, onSuggestion) {
  const detail = error.detail;
  // No alert: the status line says a run failed, and an alert would speak again each time the mode comes back
  const box = h('div', { class: 'error' }, h('p', { class: 'error-title' }, error.message));
  if (typeof detail === 'string') {
    box.append(h('p', {}, detail));
  } else if (Array.isArray(detail)) {
    box.append(h('ul', {}, detail.map((problem) => h('li', {}, [fieldOf(problem.loc), problem.msg].filter(Boolean).join(': ')))));
  } else if (detail && typeof detail === 'object') {
    if (detail.message) box.append(h('p', {}, detail.message));
    const alternatives = detail.resolution?.alternatives ?? [];
    if (alternatives.length) {
      box.append(
        h('p', {}, 'Meinten Sie:'),
        h('ul', { class: 'suggestions' }, alternatives.map((title) => h('li', {}, h('button', { type: 'button', class: 'link-button', on: { click: () => onSuggestion?.(title) } }, title)))),
      );
    }
  }
  if (error.requestId) box.append(h('p', { class: 'error-id' }, `Anfrage-ID: ${error.requestId}`));
  return box;
}

// "body", "query" and "path" say where a value came from; the field is what a reader recognises
function fieldOf(loc) {
  return (loc ?? []).filter((part) => !['body', 'query', 'path'].includes(part)).join('.');
}
