// How the answers of a run look on the review page (D66): one column per profile, its metrics, the view of its
// endpoint and what it says about its making; two profiles also get their metrics side by side. The display switches
// hold for every answer shown. What the presentation needs of the page comes as ``host``: its options, announce() and
// suggest(), which puts a proposed title into the form.

import { append, copyText, download, h } from './dom.mjs';
import { compendiumInfo } from './info_compendium.mjs';
import { compareTable, errorBox, metricsBar } from './panels.mjs';
import { formatDuration, metrics } from './stats.mjs';
import { label, MODES, PROFILE_NAMES } from './texts.mjs';
import { renderCompendium } from './view_compendium.mjs';
import { renderEntities } from './view_entities.mjs';
import { renderKnowledge } from './view_knowledge.mjs';
import { renderLehrplan } from './view_lehrplan.mjs';
import { renderQa } from './view_qa.mjs';

const VIEWS = {
  compendium(answer, run, options, prefix) {
    const { body, headings } = renderCompendium(answer, prefix);
    return { body, headings, info: compendiumInfo(answer, run, options), markdown: answer.markdown };
  },
  knowledge: (answer, run) => renderKnowledge(answer, run),
  lehrplan: (answer, run) => renderLehrplan(answer, run),
  entities: (answer, run) => renderEntities(answer, run),
  qa: (answer, run) => renderQa(answer, run),
};
const INTRO = {
  compendium: ['Links ein Thema eingeben oder ein Beispiel laden.', 'Teile und Profil wählen – zum Vergleich ein zweites Profil.', '„Kompendium erzeugen“ drücken; der Text erscheint hier.'],
  knowledge: ['Ein Thema eingeben oder ein Beispiel laden.', 'Ein Profil wählen.', 'Die Artikel erscheinen hier, jeder mit dem Weg, auf dem er gefunden wurde.'],
  lehrplan: ['Ein Stichwort oder Thema eingeben, bei Bedarf ein Fach.', 'Ein Profil wählen.', 'Die Lehrplanelemente erscheinen hier, nach Ländern geordnet.'],
  entities: ['Einen Text eingeben oder ein Beispiel laden.', 'Ein Profil wählen.', 'Der Text erscheint mit den markierten Entitäten, darunter jede mit Artikel und Kennungen.'],
  qa: ['Ein Thema oder einen eigenen Text eingeben.', 'Ein Profil und die Anzahl der Paare wählen.', 'Die Paare erscheinen hier.'],
};
const display = { origin: true, cites: true }; // the switches over the answers, the same for every run
let columns = 0; // numbers the ids of the columns and switches, unique on the page

export function renderResults(mode, runs, host) {
  const container = h('div', { class: `results${runs.length > 1 ? ' compared' : ''}` });
  showDisplay(container);
  if (mode === 'compendium' && runs.some((one) => !one.error)) container.append(toolbar(container));
  if (runs.length > 1) {
    const lists = runs.map((one) => (one.error ? [] : metrics(mode, one.data, one.elapsedMs)));
    container.append(
      compareTable(runs.map((one) => label(PROFILE_NAMES, one.preset)), lists),
      h('p', { class: 'help compare-note' }, 'Die Anfragen liefen nacheinander; jede Dauer gilt für ihr Profil allein.'),
    );
  }
  container.append(h('div', { class: 'columns' }, runs.map((one) => column(mode, one, host))));
  return container;
}

// Switches of the display only: they change what shows, not what was asked
function toolbar(container) {
  const toggle = (name, text) => {
    const id = `anzeige-${name}-${(columns += 1)}`;
    const box = h('input', {
      type: 'checkbox',
      id,
      checked: display[name],
      on: {
        change: () => {
          display[name] = box.checked;
          showDisplay(container);
        },
      },
    });
    return h('div', { class: 'check' }, box, h('label', { for: id }, text));
  };
  return h('div', { class: 'toolbar', role: 'group', 'aria-label': 'Anzeige' }, toggle('origin', 'Herkunft je Absatz'), toggle('cites', 'Belegnummern im Text'));
}

function showDisplay(container) {
  container.classList.toggle('show-origin', display.origin);
  container.classList.toggle('hide-cites', !display.cites);
}

function column(mode, one, host) {
  const name = label(PROFILE_NAMES, one.preset);
  const head = h('div', { class: 'column-head' }, h('p', { class: 'profile-name' }, name));
  const frame = h('article', { class: 'column', 'aria-label': `Ergebnis mit ${name}` }, head);
  if (one.error) {
    frame.append(errorBox(one.error, (title) => host.suggest(mode, title)));
    return frame;
  }
  let view;
  try {
    view = VIEWS[mode](one.data, one, host.options, `e${(columns += 1)}`);
  } catch (error) {
    // An answer the page cannot show is still worth a report: its JSON can be saved
    head.append(actions(mode, one, {}, host));
    frame.append(errorBox({ message: 'Die Antwort ließ sich nicht darstellen.', detail: String(error?.message ?? error) }));
    return frame;
  }
  head.append(actions(mode, one, view, host));
  append(frame, [metricsBar(metrics(mode, one.data, one.elapsedMs)), unsure(mode, one.data.resolution, host), contents(view.headings), view.body, view.info]);
  return frame;
}

function actions(mode, one, view, host) {
  const stamp = new Date().toISOString().slice(0, 19).replaceAll(':', '-');
  const copy = view.markdown
    ? h('button', { type: 'button', class: 'quiet', on: { click: async () => host.announce((await copyText(view.markdown)) ? 'Markdown kopiert.' : 'Kopieren ging in diesem Browser nicht. „Markdown speichern“ legt den Text als Datei ab.') } }, 'Markdown kopieren')
    : null;
  // The finished text as the service wrote it, frontmatter and markers included, named for its topic and profile
  const text = view.markdown
    ? h('button', { type: 'button', class: 'quiet', on: { click: () => download(`kompendium-${nameOf(one.data.topic ?? one.request.body?.topic)}-${one.preset}-${stamp}.md`, view.markdown, 'text/markdown') } }, 'Markdown speichern')
    : null;
  const save = h('button', { type: 'button', class: 'quiet', on: { click: () => download(`${mode}-${one.preset}-${stamp}.json`, JSON.stringify({ request: one.request, answer: one.data }, null, 2)) } }, 'Antwort speichern');
  return h('div', { class: 'actions' }, copy, text, save);
}

// A topic as part of a file name: its letters and digits, the rest a hyphen
function nameOf(topic) {
  return String(topic ?? '').toLowerCase().replace(/[^\p{L}\p{N}]+/gu, '-').replace(/^-+|-+$/g, '').slice(0, 60) || 'ohne-thema';
}

// A guess of the rules - a title suggestion, a full-text hit - is worth a look before the text: the other
// candidates the resolution weighed can be taken over with one click
function unsure(mode, resolution, host) {
  const others = (resolution?.alternatives ?? []).filter((title) => title !== resolution.title).slice(0, 6);
  if (!resolution?.title || resolution.confident || !others.length) return null;
  return h(
    'div',
    { class: 'unsure' },
    h('p', {}, `Der Artikel „${resolution.title}“ ist ein unsicherer Treffer. Andere Kandidaten:`),
    h('ul', { class: 'suggestions' }, others.map((title) => h('li', {}, h('button', { type: 'button', class: 'link-button', on: { click: () => host.suggest(mode, title) } }, title)))),
  );
}

// A table of contents for a long document: its title, its parts and the blocks of part 1
function contents(headings) {
  const shown = (headings ?? []).filter((heading) => heading.level <= 3);
  if (shown.length < 4) return null;
  return h(
    'details',
    { class: 'contents' },
    h('summary', {}, 'Inhalt'),
    h('ol', {}, shown.map((heading) => h('li', { class: `level-${heading.level}` }, h('a', { href: `#${heading.id}` }, heading.text)))),
  );
}

export function summary(mode, runs) {
  const failed = runs.filter((one) => one.error);
  if (failed.length === runs.length) return `Fehler: ${failed[0].error.message}`;
  const times = runs.filter((one) => !one.error).map((one) => `${label(PROFILE_NAMES, one.preset)} ${formatDuration(one.elapsedMs)}`);
  return `${MODES[mode]} fertig: ${times.join(', ')}${failed.length ? `; ${failed.length} mit Fehler` : ''}.`;
}

/** What a stopped run leaves on the page: the answers that were done - the first profile of a comparison may be,
 * and it may have cost a minute - else what the mode showed before the run. */
export function stopped(mode, runs, before, host) {
  return runs.length ? renderResults(mode, runs, host) : before ?? intro(mode);
}

export function stoppedSummary(mode, runs) {
  const kept = runs.length ? summary(mode, runs) : 'die vorige Anzeige bleibt.';
  return `Abgebrochen; ${kept} Der Server rechnet eine begonnene Anfrage womöglich noch zu Ende.`;
}

export function intro(mode) {
  return h(
    'div',
    { class: 'empty' },
    h('h2', {}, `${MODES[mode]} prüfen`),
    h('ol', {}, INTRO[mode].map((step) => h('li', {}, step))),
    mode === 'compendium'
      ? h('p', {}, 'Unter jedem Absatz steht, woher er stammt: wörtlich aus einem Artikel, von der KI ausgewählt oder von der KI formuliert. Die Nummern in Klammern öffnen den Beleg; darunter erklärt „Wie entstand dieser Text?“ den Weg Schritt für Schritt.')
      : null,
  );
}
