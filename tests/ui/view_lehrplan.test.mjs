// The curriculum elements of a search and how they came about, with answers as the endpoint gives them (D66).
import { test } from 'node:test';
import assert from 'node:assert/strict';

import { installDocument } from './dom_stub.mjs';
import { fact, saved, shown } from './saved_answers.mjs';
import { renderLehrplan } from '../../app/ui/static/view_lehrplan.mjs';

const CHECK = 'Suche und Prüfung';

test('the elements stand under their state, with their curriculum and the rating of the model', () => {
  const results = shown('lehrplan_topic');

  const nodes = results.descendants();
  assert.deepEqual(nodes.filter((node) => node.tagName === 'H3').map((node) => node.textContent), ['Sachsen']);
  const [element] = nodes.filter((node) => node.classList.contains('element'));
  assert.match(element.textContent, /^Lichtbrechung an Linsen \(kompetenz\)Bereich: Lernbereich 2: OptikGymnasium Physik/);
  assert.match(element.textContent, /nur die Überschrift nennt das Thema.*KI: passt zum Thema/);
  assert.equal(fact(results, CHECK, 'Prüfung der Elemente'), 'KI bewertet jedes Element');
  assert.equal(fact(results, CHECK, 'Hinweis'), '1 von 1 bewertet, 0 entfernt');
});

test('a search that found nothing to check says so, not what a compendium says of its blocks', () => {
  const results = shown('lehrplan_nothing_to_check');

  assert.equal(fact(results, CHECK, 'Prüfung der Elemente'), 'Stichwortregeln');
  assert.equal(fact(results, CHECK, 'Hinweis'), 'nichts zu prüfen: kein Lehrplanelement gefunden');
  assert.doesNotMatch(results.textContent, /Absatz|Baustein/);
});

test('a check the model could not do falls back to the rules and says why', () => {
  installDocument();
  const { run } = saved('lehrplan_topic');
  const answer = structuredClone(run.data);
  Object.assign(answer.llm.curriculum_check, { used: 'rule-based', rated: 0, answered: 0, fallback: 'b-api nicht erreichbar' });

  const { info } = renderLehrplan(answer, { ...run, data: answer });

  assert.equal(fact(info, CHECK, 'Prüfung der Elemente'), 'Stichwortregeln Rückfall auf die Regeln');
  assert.equal(fact(info, CHECK, 'Hinweis'), 'b-api nicht erreichbar');
});
