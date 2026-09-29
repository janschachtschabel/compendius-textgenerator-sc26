// Answers as the endpoints really give them, for the tests of the views (D66; audit 2026-09-29, U4). The files in
// answers/ are made offline by tests/test_ui_answers.py, which keeps their form in step with the endpoints; each holds
// the request as the page sends it and the answer, as "Antwort speichern" writes them, and options.json is the
// options of that server.
import { readdirSync, readFileSync } from 'node:fs';

import { installDocument } from './dom_stub.mjs';
import { renderResults } from '../../app/ui/static/results.mjs';

const FOLDER = new URL('./answers/', import.meta.url);
const read = (name) => JSON.parse(readFileSync(new URL(name, FOLDER), 'utf8'));

export const OPTIONS = read('options.json');
export const MODES = ['compendium', 'knowledge', 'lehrplan', 'entities', 'qa'];
/** The names of the saved answers, each starting with its mode: compendium_material, lehrplan_topic, … */
export const NAMES = readdirSync(FOLDER)
  .filter((file) => file.endsWith('.json') && file !== 'options.json')
  .map((file) => file.replace(/\.json$/, ''));

/** A saved answer as main.mjs holds a finished run: its mode, and its profile, request, answer, time and id. */
export function saved(name) {
  const { request, answer } = read(`${name}.json`);
  const mode = MODES.find((one) => name.startsWith(`${one}_`));
  return { mode, run: { preset: (request.body ?? request.query).preset, request, data: answer, elapsedMs: 1234, requestId: 'r-1' } };
}

/** The results of one saved answer as the page shows them, in a fresh stand-in document. */
export function shown(name) {
  installDocument();
  const { mode, run } = saved(name);
  return renderResults(mode, [run], { options: OPTIONS, announce() {}, suggest() {} });
}
