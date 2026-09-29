// The review page (D66): the modes and their forms on the left, the answers on the right - of one profile, or of two
// side by side with their metrics compared. Each mode keeps its form and its last answers while another is shown;
// how an answer looks is results.mjs.

import { send } from './api.mjs';
import { h } from './dom.mjs';
import { buildForm } from './fields.mjs';
import { buildRequests, defaults, fromExample, problems } from './forms.mjs';
import { intro, renderResults, stopped, stoppedSummary, summary } from './results.mjs';
import { formatDuration } from './stats.mjs';
import { label, MODES, PROFILE_NAMES } from './texts.mjs';

const KEY_STORE = 'kompendium-pruefen-schluessel';
const SLOW = /^best-quality/;
const STACKED = window.matchMedia('(max-width: 900px)'); // ui.css puts the form above the answers there

const page = {
  options: null,
  mode: 'compendium',
  forms: new Map(), // mode → its form (fields.mjs)
  results: new Map(), // mode → the element with its last answers
  controllers: new Map(), // mode → the running request, to cancel it
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
  const shown = page.results.get(mode);
  const before = shown?.classList.contains('waiting') ? null : shown; // not the panel of a run this one replaced
  const progress = waiting(mode, planned, controller);
  // One after the other: side by side the two requests shared the workers, the CPU and the LLM gateway, and each
  // time would have held some of the other's
  const runs = [];
  for (const [index, plan] of planned.entries()) {
    progress.at(index);
    try {
      runs.push({ ...plan, ...(await send(plan.request, key, controller.signal)) });
    } catch (error) {
      if (controller.signal.aborted) break;
      runs.push({ ...plan, error });
    }
  }
  progress.stop();
  if (page.controllers.get(mode) !== controller) return; // a newer run of this mode took over the page and the form
  form.busy(false);
  // A focus in the waiting panel - on "Abbrechen" - would fall to the top of the page with it
  const waited = progress.panel.contains(document.activeElement);
  const host = { options: page.options, announce, suggest };
  if (controller.signal.aborted) {
    place(mode, stopped(mode, runs, before, host));
    announce(stoppedSummary(mode, runs));
  } else {
    place(mode, renderResults(mode, runs, host));
    announce(summary(mode, runs));
  }
  if (runs.some((one) => one.error?.status === 401)) byId('api-key').focus();
  else if ((waited || STACKED.matches) && page.mode === mode) byId('ergebnis').focus(); // stacked, the answer lies below the form
}

// The answers of a mode are kept for it and shown when it is the one on screen
function place(mode, element) {
  page.results.set(mode, element);
  if (page.mode === mode) byId('results').replaceChildren(element);
}

// The waiting panel: which profile runs, for how long, and a way to stop
function waiting(mode, planned, controller) {
  let started = performance.now();
  const clock = h('span', { class: 'clock' }, formatDuration(0));
  const now = h('span', {});
  const slow = planned.some((plan) => SLOW.test(plan.preset));
  const panel = h(
    'div',
    { class: 'waiting' },
    h('div', { class: 'spinner', 'aria-hidden': 'true' }),
    h('p', {}, now, ' ', clock),
    planned.length > 1 ? h('p', { class: 'help' }, 'Die beiden Profile laufen nacheinander, damit jede Dauer für ihr Profil allein gilt.') : null,
    slow ? h('p', { class: 'help' }, 'Die Profile best-quality fragen die KI bei vielen Schritten; das dauert oft eine halbe Minute.') : null,
    h('button', { type: 'button', class: 'quiet', on: { click: () => controller.abort() } }, 'Abbrechen'),
  );
  place(mode, panel);
  announce(`${MODES[mode]}: wird erstellt …`);
  const timer = setInterval(() => (clock.textContent = formatDuration(performance.now() - started)), 250);
  return {
    panel,
    at(index) {
      const name = label(PROFILE_NAMES, planned[index].preset);
      now.textContent = planned.length > 1 ? `Wird erstellt mit ${name} (${index + 1} von ${planned.length}) …` : `Wird erstellt mit ${name} …`;
      started = performance.now();
    },
    stop: () => clearInterval(timer),
  };
}

function suggest(mode, title) {
  const form = page.forms.get(mode);
  form.write(mode === 'lehrplan' ? { q: title } : { topic: title });
  announce(`Übernommen: ${title}. Zum Erzeugen den Knopf links drücken.`);
  form.element.querySelector('button[type="submit"]')?.focus();
}

function announce(text) {
  byId('status').textContent = text;
}
