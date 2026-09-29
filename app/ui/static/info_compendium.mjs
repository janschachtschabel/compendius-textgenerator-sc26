// "How did this text come about?" below a compendium (D66): the topic and how it was found, the shares of the
// text by the way it came about, the method of every step as asked and as used, time by stage, cost, sources, the
// findings of the lint and the technical details - each part folded, so the text stays the first thing to read.

import { h, link } from './dom.mjs';
import { facts, infoPart, nodeArticleFacts, resolutionFacts, technical } from './panels.mjs';
import { shares } from './provenance.mjs';
import { stepsAccount } from './steps.mjs';
import { formatDuration, formatNumber } from './stats.mjs';
import { KINDS, label, ORIGINS, PART_STATUS, PARTS, PROJECTS, STAGES, STEPS } from './texts.mjs';

const PERCENT = new Intl.NumberFormat('de-DE', { style: 'percent', maximumFractionDigits: 0 });

export function compendiumInfo(answer, run, options) {
  const audit = answer.audit ?? {};
  return h(
    'section',
    { class: 'info' },
    h('h2', {}, 'Wie entstand dieser Text?'),
    topic(answer, run),
    origins(answer),
    methods(answer, run, options),
    time(audit.timings_ms ?? {}, run.elapsedMs),
    cost(audit.llm_tokens, answer.frontmatter?.llm),
    sources(answer.sources ?? []),
    findings(audit.lint ?? [], answer.parts_status ?? {}),
    technical(run, [['Protokoll der Erzeugung (audit)', audit], ['Kopf des Dokuments (frontmatter)', answer.frontmatter ?? {}]]),
  );
}

function topic(answer, run) {
  const node = answer.node;
  return infoPart(
    'Thema und Artikel',
    facts([
      ...resolutionFacts(answer),
      ['Fächer des Knotens', node?.subjects],
      ['Stufen des Knotens', node?.educational_contexts],
      ...nodeArticleFacts(answer.audit?.node_article, answer, run.request.body),
      ['Wissens-Sammlung', knowledge(answer.audit?.knowledge)],
    ]),
  );
}

// The account of app/compendium/repository.py: materials considered, taken as sources, and why others were not
function knowledge(block) {
  if (!block) return null;
  if (block.error) return `nicht lesbar: ${block.error}`;
  return [
    `${block.sources ?? 0} von ${block.considered ?? 0} Materialien als Quelle`,
    block.skipped_license ? `${block.skipped_license} wegen der Lizenz ausgelassen` : null,
    block.empty ? `${block.empty} ohne Text` : null,
    block.failed ? `${block.failed} nicht lesbar` : null,
  ]
    .filter(Boolean)
    .join(', ');
}

function origins(answer) {
  const parts = shares(answer);
  if (!parts.length) return null;
  const words = parts.map((part) => `${PERCENT.format(part.share)} ${KINDS[part.kind].name.toLowerCase()}`).join(', ');
  const bar = h('div', { class: 'shares', role: 'img', 'aria-label': `Anteile von Teil 1: ${words}` });
  for (const part of parts) {
    const segment = h('span', { class: `share kind-${part.kind}` });
    segment.style.setProperty('--share', String(part.share));
    bar.append(segment);
  }
  const legend = h('ul', { class: 'legend' }, parts.map((part) => h('li', { class: `kind-${part.kind}` }, `${KINDS[part.kind].name}: ${PERCENT.format(part.share)} (${formatNumber(part.chars)} Zeichen)`)));
  return infoPart('Woher der Text stammt', bar, legend);
}

function methods(answer, run, options) {
  const rows = stepsAccount(answer, run.request.body, run.preset, options).map((row) => {
    const values = STEPS[row.step].values;
    const used = row.applies
      ? [label(values, row.used), row.fellBack ? h('span', { class: 'flag' }, ' Rückfall auf die Regeln') : null]
      : `– läuft nur mit ${row.parts.map((part) => label(PARTS, part)).join(' oder ')}`;
    return h(
      'tr',
      { class: row.fellBack ? 'fell-back' : null },
      h('th', { scope: 'row' }, STEPS[row.step].name),
      h('td', {}, label(values, row.asked)),
      h('td', {}, used),
      h('td', {}, row.note ?? ''),
    );
  });
  const note = answer.audit?.llm?.note;
  return infoPart(
    'Methoden je Schritt',
    h('div', { class: 'table-wrap' }, h('table', { class: 'steps' }, h('thead', {}, h('tr', {}, ['Schritt', 'Angefragt', 'Verwendet', 'Hinweis'].map((name) => h('th', { scope: 'col' }, name)))), h('tbody', {}, rows))),
    note ? h('p', { class: 'note' }, note) : null,
  );
}

function time(timings, elapsedMs) {
  const stages = Object.entries(timings).filter(([, ms]) => ms > 0);
  const longest = Math.max(1, ...stages.map(([, ms]) => ms));
  const rows = stages.map(([stage, ms]) => {
    const bar = h('span', { class: 'bar' });
    bar.style.setProperty('--part', String(ms / longest));
    return h('li', {}, h('span', { class: 'stage' }, label(STAGES, stage)), bar, h('span', { class: 'ms' }, formatDuration(ms)));
  });
  const server = stages.reduce((sum, [, ms]) => sum + ms, 0);
  return infoPart(
    'Zeit je Schritt',
    h('p', {}, `Dauer im Browser ${formatDuration(elapsedMs)}, davon im Dienst ${formatDuration(server)}.`),
    rows.length ? h('ul', { class: 'stages' }, rows) : null,
  );
}

function cost(tokens, llm) {
  if (!tokens) return infoPart('Kosten', h('p', {}, 'Keine Tokens: kein Schritt hat die KI gefragt.'));
  return infoPart(
    'Kosten',
    facts([
      ['Tokens gesamt', formatNumber(tokens.total)],
      ['davon Eingabe', formatNumber(tokens.prompt)],
      ['davon Ausgabe', formatNumber(tokens.completion)],
      ['Aufrufe der KI', formatNumber(tokens.calls)],
      ['Modell', llm?.model],
      ['Prompts', llm?.prompts],
    ]),
  );
}

function sources(list) {
  if (!list.length) return null;
  return infoPart(
    `Quellen (${list.length})`,
    h(
      'ol',
      { class: 'sources' },
      list.map((source) =>
        h('li', {}, link(source.url, source.title), ` · ${label(PROJECTS, source.project)}`, source.is_primary ? ` · ${ORIGINS.primary}` : '', source.license ? ` · ${source.license}` : ''),
      ),
    ),
  );
}

function findings(lint, partsStatus) {
  const parts = Object.entries(partsStatus).map(([part, status]) => [label(PARTS, part), label(PART_STATUS, status)]);
  return infoPart(
    lint.length ? `Hinweise der Prüfung (${lint.length})` : 'Hinweise der Prüfung',
    facts(parts),
    lint.length
      ? h('ul', {}, lint.map((finding) => h('li', {}, finding.message, finding.section_id ? ` (Baustein ${finding.section_id})` : '')))
      : h('p', {}, 'Die Prüfung des Textes fand nichts.'),
  );
}
