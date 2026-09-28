// Curriculum elements for a keyword or a topic (D66), grouped by federal state, each with its curriculum, school
// type, level and grade, whether the element or only its heading names the topic, and the LLM's rating if it gave one.

import { h, link } from './dom.mjs';
import { facts, infoPart, technical } from './panels.mjs';
import { formatNumber } from './stats.mjs';
import { label, MATCHED_IN, RATINGS, STEPS } from './texts.mjs';

export function renderLehrplan(answer, run) {
  const matches = answer.matches ?? [];
  const byState = new Map();
  for (const match of matches) byState.set(match.bundesland, [...(byState.get(match.bundesland) ?? []), match]);
  const title = answer.topic ? `Lehrplanelemente zu „${answer.topic}“` : `Lehrplanelemente zu „${run.request.query.q}“`;
  const body = h(
    'div',
    { class: 'document' },
    h('h2', {}, title),
    answer.available === false ? h('p', { class: 'note' }, answer.note ?? 'Der Lehrplan-Cache ist noch nicht geerntet.') : null,
    h('p', { class: 'lead-note' }, summary(answer, matches.length)),
    [...byState].map(([state, elements]) => [h('h3', {}, state || 'ohne Land'), h('ul', { class: 'elements' }, elements.map(element))]),
  );
  const llm = answer.llm ?? {};
  const info = h(
    'section',
    { class: 'info' },
    h('h2', {}, 'Wie kam die Liste zustande?'),
    infoPart(
      'Suche und Prüfung',
      facts([
        ['Suche nach', answer.mode === 'topic' ? 'dem Thema, wie Teil 2 eines Kompendiums' : 'den Wörtern, wie eingegeben'],
        ['Stichwörter', answer.keywords],
        ['Fachwörter', answer.subject_terms],
        ['Profil', answer.preset],
        ['Prüfung der Elemente', llm.curriculum_check ? label(STEPS.curriculum_check.values, llm.curriculum_check.used) : 'Stichwortregeln'],
        ['Hinweis', llm.note],
        ['Tokens', answer.llm_tokens?.total ? formatNumber(answer.llm_tokens.total) : 'keine'],
      ]),
    ),
    technical(run),
  );
  return { body, info };
}

function summary(answer, shown) {
  const parts = [`${formatNumber(answer.total_hits ?? 0)} Treffer, ${formatNumber(shown)} gezeigt`];
  if (answer.cut_hits) parts.push(`${formatNumber(answer.cut_hits)} jenseits der Suchgrenze`);
  if (answer.excluded_noise) parts.push(`${formatNumber(answer.excluded_noise)} als Rauschen verworfen`);
  return `${parts.join(', ')}. Jedes Element stammt aus dem Lehrplan, auf den es verweist.`;
}

function element(match) {
  const where = [match.schulart, match.schulstufe, match.klassenstufe].filter(Boolean).join(' · ');
  return h(
    'li',
    { class: 'element' },
    h('p', { class: 'element-label' }, h('strong', {}, match.label), match.rollen?.length ? ` (${match.rollen.join(', ')})` : ''),
    match.bereich ? h('p', { class: 'element-meta' }, `Bereich: ${match.bereich}`) : null,
    h('p', { class: 'element-meta' }, match.lehrplan_iri ? link(match.lehrplan_iri, match.lehrplan) : match.lehrplan, where ? ` · ${where}` : ''),
    h(
      'p',
      { class: 'element-flags' },
      // Only the exception is flagged: most elements name the topic themselves
      match.matched_in === 'parent' ? h('span', { class: 'flag' }, label(MATCHED_IN, match.matched_in)) : null,
      match.note !== null && match.note !== undefined ? h('span', { class: 'flag rating' }, `KI: ${label(RATINGS, match.note)}`) : null,
    ),
  );
}
