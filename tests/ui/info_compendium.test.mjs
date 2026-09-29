// "Wie entstand dieser Text?" below a compendium, with answers as the service gives them (D66).
import { test } from 'node:test';
import assert from 'node:assert/strict';

import { installDocument } from './dom_stub.mjs';
import { fact, OPTIONS, saved, shown } from './saved_answers.mjs';
import { compendiumInfo } from '../../app/ui/static/info_compendium.mjs';

/** The info section of a saved compendium, its answer changed first where a test needs another case. */
function info(name, change = () => {}) {
  installDocument();
  const { run } = saved(name);
  const answer = structuredClone(run.data);
  change(answer);
  return compendiumInfo(answer, { ...run, data: answer }, OPTIONS);
}

test('a compendium of a material names the article the model found for it', () => {
  const section = info('compendium_material');

  assert.equal(fact(section, 'Thema und Artikel', 'Artikel des Materials'), 'Optik');
  assert.equal(fact(section, 'Thema und Artikel', 'Gefunden durch'), 'KI');
  assert.equal(fact(section, 'Thema und Artikel', 'Warum die Regeln entschieden'), null);
});

test('where the rules found the article of a material, it is the one the text is built on, and it says why the model did not decide', () => {
  // As app/knowledge/main_article.py leaves the block when the model named a title the archive lacks
  const section = info('compendium_material', (answer) => {
    Object.assign(answer.audit.node_article, { way: 'rules', named: 'Optik (Film)', title_article: 'Optik', entities: ['Optik', 'Linse'], fallback: 'genannter Titel ist kein Artikel des Archivs' });
  });

  assert.equal(fact(section, 'Thema und Artikel', 'Artikel des Materials'), 'Optik');
  assert.equal(fact(section, 'Thema und Artikel', 'Gefunden durch'), 'Regeln aus Titel und Beschreibung');
  assert.equal(fact(section, 'Thema und Artikel', 'Warum die Regeln entschieden'), 'genannter Titel ist kein Artikel des Archivs');
});

test('a compendium without a material says nothing of one', () => {
  assert.equal(fact(info('compendium_topic'), 'Thema und Artikel', 'Artikel des Materials'), null);
});

test('the knowledge texts of a topic with a material name its own article and whether it joined the sources', () => {
  const results = shown('knowledge_material');

  assert.equal(fact(results, 'Thema und Artikel', 'Artikel des Materials'), 'Optik');
  assert.equal(fact(results, 'Thema und Artikel', 'Gefunden durch'), 'KI');
  assert.equal(fact(results, 'Thema und Artikel', 'Als weitere Quelle'), 'ja, mit dem Hauptartikel verlinkt');
});
