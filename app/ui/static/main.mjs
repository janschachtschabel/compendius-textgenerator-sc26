// The review page (D66): the modes and their forms on the left, the answers on the right - of one profile, or of two
// side by side with their metrics compared. Each mode keeps its form and its last answers while another is shown.

import { send } from './api.mjs';
import { append, copyText, download, h } from './dom.mjs';
import { buildForm } from './fields.mjs';
import { buildRequests, defaults, fromExample, problems } from './forms.mjs';
import { compendiumInfo } from './info_compendium.mjs';
import { compareTable, errorBox, metricsBar } from './panels.mjs';
import { formatDuration, metrics } from './stats.mjs';
import { label, MODES, PROFILE_NAMES } from './texts.mjs';
import { renderCompendium } from './view_compendium.mjs';
import { renderEntities } from './view_entities.mjs';
import { renderKnowledge } from './view_knowledge.mjs';
import { renderLehrplan } from './view_lehrplan.mjs';
import { renderQa } from './view_qa.mjs';

const KEY_STORE = 'kompendium-pruefen-schluessel';
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
const SLOW = /^best-quality/;
const STACKED = window.matchMedia('(max-width: 900px)'); // ui.css puts the form above the answers there

const page = {
  options: null,
  mode: 'compendium',
  forms: new Map(), // mode → its form (fields.mjs)
  results: new Map(), // mode → the element with its last answers
  controllers: new Map(), // mode → the running request, to cancel it
  columns: 0,
  display: { origin: true, cites: true },
};

const byId = (id) => document.getElementById(id);

start();

async function start() {
  try {
    const response = await fetch('options.json', { headers: { Accept: 'application/json' } });
    if (!response.ok) throw new Error(`status ${response.status}`);
    page.options = await response.json();
  } catch (error) {
    announce(`Die Einstellungen des Servers ließen sich nicht laden (${error.message}). Bitte die Seite neu laden.`);
    return;
  }
  describeServer();
  setUpKey();
  setUpModes();
  showMode(page.mode);
}

function describeServer() {
  const { llm_configured: llm, preset_default: preset } = page.options;
  byId('server-note').textContent = llm
    ? `KI verfügbar · Vorgabe des Servers: ${label(PROFILE_NAMES, preset)}`
    : 'Dieser Server hat keine KI: nur das Profil llm-free antwortet.';
}

function setUpKey() {
  byId('key-box').hidden = !page.options.keys_required;
  const input = byId('api-key');
  try {
    input.value = sessionStorage.getItem(KEY_STORE) ?? '';
  } catch {
    // storage refused (a strict browser setting): the key then lives in the field only
  }
  input.addEventListener('change', () => {
    try {
      sessionStorage.setItem(KEY_STORE, input.value);
    } catch {
      // as above; nothing is lost but the convenience of not typing it again in this tab
    }
  });
}

function setUpModes() {
  const group = byId('modes');
  for (const [mode, name] of Object.entries(MODES)) {
    const id = `modus-${mode}`;
    const radio = h('input', { type: 'radio', name: 'mode', id, value: mode, checked: mode === page.mode, on: { change: () => showMode(mode) } });
    group.append(h('div', { class: 'mode' }, radio, h('label', { for: id }, name)));
  }
}

function showMode(mode) {
  page.mode = mode;
  if (!page.forms.has(mode)) {
    const form = buildForm(mode, page.options, { onSubmit: () => run(mode), onExample: (example) => loadExample(mode, example) });
    form.write(defaults(mode, page.options));
    page.forms.set(mode, form);
  }
  byId('form-slot').replaceChildren(page.forms.get(mode).element);
  byId('results').replaceChildren(page.results.get(mode) ?? intro(mode));
  document.title = `${MODES[mode]} prüfen`;
}

function loadExample(mode, example) {
  const form = page.forms.get(mode);
  form.write(fromExample(mode, example, page.options));
  form.show({});
  announce(`Beispiel geladen: ${example.label}`);
}

async function run(mode) {
  const form = page.forms.get(mode);
  const values = form.read();
  if (form.show(problems(mode, values, page.options))) {
    announce('Bitte die markierten Eingaben prüfen.');
    return;
  }
  page.controllers.get(mode)?.abort();
  const controller = new AbortController();
  page.controllers.set(mode, controller);
  const planned = buildRequests(mode, values, page.options);
  const key = byId('api-key').value.trim();
  form.busy(true);
  const stopClock = waiting(mode, planned, controller);
  const settled = await Promise.allSettled(planned.map((plan) => send(plan.request, key, controller.signal).then((answer) => ({ ...plan, ...answer }))));
  stopClock();
  if (page.controllers.get(mode) !== controller) return; // a newer run of this mode took over the page and the form
  form.busy(false);
  if (controller.signal.aborted) {
    place(mode, h('div', { class: 'empty' }, h('p', {}, 'Abgebrochen. Der Server rechnet eine begonnene Anfrage womöglich noch zu Ende.')));
    announce('Abgebrochen.');
    return;
  }
  const runs = settled.map((outcome, index) => (outcome.status === 'fulfilled' ? outcome.value : { ...planned[index], error: outcome.reason }));
  place(mode, results(mode, runs));
  announce(summary(mode, runs));
  if (runs.some((one) => one.error?.status === 401)) byId('api-key').focus();
  else if (STACKED.matches && page.mode === mode) byId('ergebnis').focus(); // the answer lies below the form there
}

// The answers of a mode are kept for it and shown when it is the one on screen
function place(mode, element) {
  page.results.set(mode, element);
  if (page.mode === mode) byId('results').replaceChildren(element);
}

function waiting(mode, planned, controller) {
  const started = performance.now();
  const clock = h('span', { class: 'clock' }, formatDuration(0));
  const names = planned.map((plan) => label(PROFILE_NAMES, plan.preset)).join(' und ');
  const slow = planned.some((plan) => SLOW.test(plan.preset));
  place(
    mode,
    h(
      'div',
      { class: 'waiting' },
      h('div', { class: 'spinner', 'aria-hidden': 'true' }),
      h('p', {}, `Wird erstellt mit ${names} … `, clock),
      slow ? h('p', { class: 'help' }, 'Die Profile best-quality fragen die KI bei vielen Schritten; das dauert oft eine halbe Minute.') : null,
      h('button', { type: 'button', class: 'quiet', on: { click: () => controller.abort() } }, 'Abbrechen'),
    ),
  );
  announce(`${MODES[mode]}: wird erstellt …`);
  const timer = setInterval(() => (clock.textContent = formatDuration(performance.now() - started)), 250);
  return () => clearInterval(timer);
}

function results(mode, runs) {
  const container = h('div', { class: `results${runs.length > 1 ? ' compared' : ''}` });
  showDisplay(container);
  if (mode === 'compendium' && runs.some((one) => !one.error)) container.append(toolbar(container));
  if (runs.length > 1) {
    const lists = runs.map((one) => (one.error ? [] : metrics(mode, one.data, one.elapsedMs)));
    container.append(compareTable(runs.map((one) => label(PROFILE_NAMES, one.preset)), lists));
  }
  container.append(h('div', { class: 'columns' }, runs.map((one) => column(mode, one))));
  return container;
}

// Switches of the display only: they change what shows, not what was asked
function toolbar(container) {
  const toggle = (name, text) => {
    const id = `anzeige-${name}-${(page.columns += 1)}`;
    const box = h('input', {
      type: 'checkbox',
      id,
      checked: page.display[name],
      on: {
        change: () => {
          page.display[name] = box.checked;
          showDisplay(container);
        },
      },
    });
    return h('div', { class: 'check' }, box, h('label', { for: id }, text));
  };
  return h('div', { class: 'toolbar', role: 'group', 'aria-label': 'Anzeige' }, toggle('origin', 'Herkunft je Absatz'), toggle('cites', 'Belegnummern im Text'));
}

function showDisplay(container) {
  container.classList.toggle('show-origin', page.display.origin);
  container.classList.toggle('hide-cites', !page.display.cites);
}

function column(mode, one) {
  const name = label(PROFILE_NAMES, one.preset);
  const head = h('div', { class: 'column-head' }, h('p', { class: 'profile-name' }, name));
  const frame = h('article', { class: 'column', 'aria-label': `Ergebnis mit ${name}` }, head);
  if (one.error) {
    frame.append(errorBox(one.error, (title) => suggest(mode, title)));
    return frame;
  }
  let view;
  try {
    view = VIEWS[mode](one.data, one, page.options, `e${(page.columns += 1)}`);
  } catch (error) {
    // An answer the page cannot show is still worth a report: its JSON can be saved
    head.append(actions(mode, one, {}));
    frame.append(errorBox({ message: 'Die Antwort ließ sich nicht darstellen.', detail: String(error?.message ?? error) }));
    return frame;
  }
  head.append(actions(mode, one, view));
  append(frame, [metricsBar(metrics(mode, one.data, one.elapsedMs)), unsure(mode, one.data.resolution), contents(view.headings), view.body, view.info]);
  return frame;
}

function actions(mode, one, view) {
  const copy = view.markdown
    ? h('button', { type: 'button', class: 'quiet', on: { click: async () => announce((await copyText(view.markdown)) ? 'Markdown kopiert.' : 'Kopieren hat der Browser nicht erlaubt.') } }, 'Markdown kopieren')
    : null;
  const stamp = new Date().toISOString().slice(0, 19).replaceAll(':', '-');
  const save = h('button', { type: 'button', class: 'quiet', on: { click: () => download(`${mode}-${one.preset}-${stamp}.json`, JSON.stringify({ request: one.request, answer: one.data }, null, 2)) } }, 'Antwort speichern');
  return h('div', { class: 'actions' }, copy, save);
}

// A guess of the rules - a title suggestion, a full-text hit - is worth a look before the text: the other
// candidates the resolution weighed can be taken over with one click
function unsure(mode, resolution) {
  const others = (resolution?.alternatives ?? []).filter((title) => title !== resolution.title).slice(0, 6);
  if (!resolution?.title || resolution.confident || !others.length) return null;
  return h(
    'div',
    { class: 'unsure' },
    h('p', {}, `Der Artikel „${resolution.title}“ ist ein unsicherer Treffer. Andere Kandidaten:`),
    h('ul', { class: 'suggestions' }, others.map((title) => h('li', {}, h('button', { type: 'button', class: 'link-button', on: { click: () => suggest(mode, title) } }, title)))),
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

function suggest(mode, title) {
  const form = page.forms.get(mode);
  form.write(mode === 'lehrplan' ? { q: title } : { topic: title });
  announce(`Übernommen: ${title}. Zum Erzeugen den Knopf links drücken.`);
  form.element.querySelector('button[type="submit"]')?.focus();
}

function summary(mode, runs) {
  const failed = runs.filter((one) => one.error);
  if (failed.length === runs.length) return `Fehler: ${failed[0].error.message}`;
  const times = runs.filter((one) => !one.error).map((one) => `${label(PROFILE_NAMES, one.preset)} ${formatDuration(one.elapsedMs)}`);
  return `${MODES[mode]} fertig: ${times.join(', ')}${failed.length ? `; ${failed.length} mit Fehler` : ''}.`;
}

function intro(mode) {
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

function announce(text) {
  byId('status').textContent = text;
}
