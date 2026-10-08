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

/** The text of the part of the info section whose title starts so. */
const partText = (section, title) => section.descendants().find((node) => node.tagName === 'DETAILS' && node.children[0]?.textContent.startsWith(title)).textContent;

test('the time in the service is the whole request, not the sum of its stages, which overlap beside part 1', () => {
  const section = info('compendium_topic', (answer) => Object.assign(answer.audit, { timings_ms: { resolve: 800, match: 3000, curricula: 2500 }, duration_ms: 3400 }));

  const text = partText(section, 'Zeit je Schritt');

  assert.match(text, /Dauer im Browser 1,2 s, davon im Dienst 3,4 s\./);
  assert.match(text, /Teil 2 und Teil 3 entstehen neben Teil 1/);
});

test('without the whole time, as in answers saved before it, the time in the service is the sum of its stages', () => {
  const section = info('compendium_topic', (answer) => {
    answer.audit.timings_ms = { resolve: 800, corpus: 1200 };
    delete answer.audit.duration_ms;
  });

  const text = partText(section, 'Zeit je Schritt');

  assert.match(text, /davon im Dienst 2,0 s\./);
  assert.doesNotMatch(text, /neben Teil 1/);
});

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

test('a collection as a source counts its materials, those it could not read and those time left unread', () => {
  const kept = info('compendium_topic');
  const late = info('compendium_topic', (answer) => Object.assign(answer.audit.knowledge, { failed: ['a1', 'b2'], timed_out: 3 }));

  assert.equal(fact(kept, 'Thema und Artikel', 'Wissens-Sammlung'), '15 von 16 Materialien als Quelle, nur Beschreibungen, 1 ohne verwertbaren Text');
  assert.equal(
    fact(late, 'Thema und Artikel', 'Wissens-Sammlung'),
    '15 von 16 Materialien als Quelle, nur Beschreibungen, 1 ohne verwertbaren Text, 2 nicht lesbar, 3 aus Zeitmangel nicht gelesen',
  );
});

test('a collection read with its full texts and its sub-collections says so (D70)', () => {
  const deep = info('compendium_topic', (answer) => Object.assign(answer.audit.knowledge, { fulltext: true, depth: 2, collections: 5 }));

  assert.equal(fact(deep, 'Thema und Artikel', 'Wissens-Sammlung'), '15 von 16 Materialien als Quelle, aus 5 Sammlungen, mit Volltext, 1 ohne verwertbaren Text');
});

test('a compendium without a material says nothing of one', () => {
  assert.equal(fact(info('compendium_topic'), 'Thema und Artikel', 'Artikel des Materials'), null);
});

test('the topic of the text is named, and one the model worded from a text says what it came from (D72)', () => {
  const section = info('compendium_material', (answer) => {
    answer.topic = 'Spiegelung und Brechung des Lichts';
    answer.audit.llm.topic_wording = { source: 'Material', reason: 'Metadaten eines Knotens ohne Thema', topic: 'Spiegelung und Brechung des Lichts', fallback: null };
  });

  assert.equal(fact(section, 'Thema und Artikel', 'Thema des Textes'), 'Spiegelung und Brechung des Lichts');
  assert.equal(fact(section, 'Thema und Artikel', 'Thema von der KI formuliert'), '„Spiegelung und Brechung des Lichts“ (aus Material, Metadaten eines Knotens ohne Thema)');
});

test('a wording without an answer keeps the topic as asked and says why (D72)', () => {
  const section = info('compendium_material', (answer) => {
    answer.audit.llm.topic_wording = { source: 'Thema', reason: 'ein Satz oder eine Frage', topic: null, fallback: 'Antwort nicht lesbar' };
  });

  assert.equal(fact(section, 'Thema und Artikel', 'Thema von der KI formuliert'), 'nein, Thema wie angefragt (aus Thema, ein Satz oder eine Frage; Antwort nicht lesbar)');
});

test('a topic that needed no wording says nothing of one', () => {
  assert.equal(fact(info('compendium_topic'), 'Thema und Artikel', 'Thema von der KI formuliert'), null);
  assert.equal(fact(info('compendium_topic'), 'Thema und Artikel', 'Thema des Textes'), 'Optik');
});

test('the check of curricula that found no element is no fallback in the table of methods, it had nothing to check', () => {
  const section = info('compendium_nothing_to_check');

  const row = section.descendants().find((node) => node.tagName === 'TR' && node.children[0]?.textContent === 'Prüfung der Lehrplanelemente');
  assert.equal(row.classList.contains('fell-back'), false);
  assert.doesNotMatch(row.textContent, /Rückfall/);
  assert.equal(row.children[3].textContent, 'nichts zu prüfen: kein Lehrplanelement gefunden');
});

test('the knowledge texts of a topic with a material name its own article and whether it joined the sources', () => {
  const results = shown('knowledge_material');

  assert.equal(fact(results, 'Thema und Artikel', 'Artikel des Materials'), 'Optik');
  assert.equal(fact(results, 'Thema und Artikel', 'Gefunden durch'), 'KI');
  assert.equal(fact(results, 'Thema und Artikel', 'Als weitere Quelle'), 'ja, mit dem Hauptartikel verlinkt');
});

test('the cost names the tokens the model read from the prompt cache, and none where there were none (D69)', () => {
  const cached = info('compendium_topic', (answer) => {
    answer.audit.llm_tokens = { prompt: 90000, completion: 11150, total: 101150, calls: 24, cached: 50936 };
  });
  const uncached = info('compendium_topic', (answer) => {
    answer.audit.llm_tokens = { prompt: 500, completion: 80, total: 580, calls: 2, cached: 0 };
  });

  assert.equal(fact(cached, 'Kosten', 'davon aus dem Prompt-Cache'), '50.936');
  assert.equal(fact(uncached, 'Kosten', 'davon aus dem Prompt-Cache'), null);
});

test('a collection whose title names nothing shows its place in the tree and what stood in for it (D92)', () => {
  const section = info('compendium_topic', (answer) => {
    answer.audit.topic_tree = { path: ['Physik-Themen', 'Kernphysik'], children: ['Kernspaltung'], materials: ['Was ist ein Isotop?', 'Halbwertszeit'], neighbours: ['Teilchenphysik'], missing: [], stand_in: 'Kernphysik' };
  });

  assert.equal(fact(section, 'Thema und Artikel', 'Ort im Themenbaum'), 'Physik-Themen › Kernphysik');
  assert.equal(fact(section, 'Thema und Artikel', 'Steht für'), '„Kernphysik“ (der Titel nennt keinen Gegenstand)');
  assert.equal(fact(section, 'Thema und Artikel', 'Von der KI gehört'), 'Untersammlungen: 1, Materialtitel: 2, Nachbarsammlungen als nicht gemeint: 1');
  assert.equal(fact(section, 'Thema und Artikel', 'Nicht gelesen'), null);
});

test('a part of the tree the repository did not give is named, and a missing path is no top level', () => {
  const section = info('compendium_topic', (answer) => {
    answer.audit.topic_tree = { path: [], children: [], materials: [], neighbours: [], missing: ['path', 'neighbours'], stand_in: 'Physik' };
  });

  assert.equal(fact(section, 'Thema und Artikel', 'Ort im Themenbaum'), null);
  assert.equal(fact(section, 'Thema und Artikel', 'Nicht gelesen'), 'Sammlungen darüber, Nachbarsammlungen');
  assert.equal(fact(section, 'Thema und Artikel', 'Von der KI gehört'), null);
});

test('without a collection as the topic there is no place in a tree', () => {
  const section = info('compendium_topic');
  assert.equal(fact(section, 'Thema und Artikel', 'Ort im Themenbaum'), null);
});
