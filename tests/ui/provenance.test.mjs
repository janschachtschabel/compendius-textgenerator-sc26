// Where a paragraph of a compendium comes from, as the review page tells it (D66).
import { test } from 'node:test';
import assert from 'node:assert/strict';

import { parseInline, parseMarkdown } from '../../app/ui/static/markdown.mjs';
import {
  blockOrigin,
  citationIndex,
  originCaption,
  shares,
  sourceIndex,
  statusKind,
} from '../../app/ui/static/provenance.mjs';

const OPTIK = 'https://de.wikipedia.org/wiki/Optik';
const compendium = {
  sections: [
    {
      slot_id: 'sc26_1',
      status: 'maschinell-extraktiv',
      text: 'Erster Absatz. [1]\n\nZweiter Absatz. [2]',
      citations: [
        { number: 1, source_id: 'wikipedia:Optik', source_title: 'Optik', source_url: OPTIK, section_heading: 'Einleitung', snippet: 'Erster' },
        { number: 2, source_id: 'klexikon:Optik', source_title: 'Optik', source_url: 'https://klexikon.zum.de/wiki/Optik', section_heading: 'Einleitung', snippet: 'Zweiter' },
      ],
    },
    {
      slot_id: 'sc26_2',
      status: 'ki-generiert',
      text: 'Umformuliert. [3] Ergänzt. [Modellwissen]',
      citations: [
        { number: 3, source_id: 'wikipedia:Linse', source_title: 'Linse (Optik)', source_url: 'https://de.wikipedia.org/wiki/Linse_(Optik)', section_heading: 'Aufbau', snippet: 'Linse' },
      ],
    },
    { slot_id: 'sc26_12', status: 'maschinell-generiert', text: 'Liste der Quellen', citations: [] },
    { slot_id: 'sc26_4', status: 'leer', text: '', citations: [] },
  ],
  sources: [
    { source_id: 'wikipedia:Optik', project: 'wikipedia', title: 'Optik', url: OPTIK },
    { source_id: 'klexikon:Optik', project: 'klexikon', title: 'Optik', url: 'https://klexikon.zum.de/wiki/Optik' },
    { source_id: 'wikipedia:Linse', project: 'wikipedia', title: 'Linse (Optik)', url: 'https://de.wikipedia.org/wiki/Linse_(Optik)' },
  ],
};
const citations = citationIndex(compendium);
const sources = sourceIndex(compendium);
const paragraph = (text) => ({ type: 'paragraph', children: parseInline(text) });

test('the status of a block says how its text came about', () => {
  assert.deepEqual(
    ['maschinell-extraktiv', 'ki-ausgewählt', 'ki-generiert', 'maschinell-generiert', 'redaktionell-geprüft', 'leer', 'neu'].map(statusKind),
    ['extract', 'selected', 'written', 'assembled', 'reviewed', 'empty', 'unknown'],
  );
});

test('the citations of every block are known by their number', () => {
  assert.deepEqual([...citations.keys()], [1, 2, 3]);
  assert.equal(citations.get(3).source_title, 'Linse (Optik)');
});

test('an extracted paragraph names its article, its lexicon and its section', () => {
  const origin = blockOrigin(paragraph('Erster Absatz. [1]'), 'extract', citations, sources);

  assert.deepEqual(origin, {
    kind: 'extract',
    sources: [{ title: 'Optik', url: OPTIK, heading: 'Einleitung', project: 'Wikipedia' }],
    marks: {},
  });
  assert.equal(originCaption(origin), 'Wörtlich aus „Optik“ (Wikipedia, Einleitung)');
});

test('every source of a paragraph is named once, in the order of its citations', () => {
  const origin = blockOrigin(paragraph('A. [2] B. [1] C. [2]'), 'extract', citations, sources);

  assert.equal(originCaption(origin), 'Wörtlich aus „Optik“ (Klexikon, Einleitung) · „Optik“ (Wikipedia, Einleitung)');
});

test('a written paragraph says what it is based on and what the model added', () => {
  const block = parseMarkdown('Umformuliert. [3] <!-- f: Evidenzgrad=Modellwissen -->Ergänzt. [Modellwissen]<!-- /f -->').blocks[0];
  const origin = blockOrigin(block, 'written', citations, sources);

  assert.deepEqual(origin.marks, { Modellwissen: 1 });
  assert.equal(
    originCaption(origin),
    'Von der KI formuliert auf Basis von „Linse (Optik)“ (Wikipedia, Aufbau) · 1 Satz Modellwissen der KI, ohne Beleg',
  );
});

test('a paragraph of nothing but model knowledge says it has no source', () => {
  const block = parseMarkdown('<!-- f: Evidenzgrad=Modellwissen -->Eins. [Modellwissen]<!-- /f --> <!-- f: Evidenzgrad=Modellwissen -->Zwei. [Modellwissen]<!-- /f -->').blocks[0];
  const origin = blockOrigin(block, 'written', citations, sources);

  assert.equal(originCaption(origin), 'Von der KI aus eigenem Wissen ergänzt · 2 Sätze Modellwissen der KI, ohne Beleg');
});

test('a sentence the model concluded is named as such', () => {
  const block = parseMarkdown('Belegt. [3] <!-- f: Evidenzgrad=Schlussfolgerung -->Also so.<!-- /f -->').blocks[0];

  assert.match(originCaption(blockOrigin(block, 'written', citations, sources)), /1 Satz Schlussfolgerung der KI, ohne Beleg$/);
});

test('a paragraph without a citation has nothing to tell', () => {
  assert.equal(blockOrigin(paragraph('Akteure aus den herangezogenen Artikeln.'), 'extract', citations, sources), null);
});

test('a citation number the answer does not know is left out', () => {
  assert.equal(blockOrigin(paragraph('Satz. [99]'), 'extract', citations, sources), null);
});

test('citations in list items and table cells count as well', () => {
  const [list, table] = parseMarkdown('- Punkt [1]\n  - tiefer [3]\n\n| Beleg | Text |\n| --- | --- |\n| [2] | x |').blocks;

  assert.equal(blockOrigin(list, 'extract', citations, sources).sources.length, 2);
  assert.equal(blockOrigin(table, 'extract', citations, sources).sources[0].project, 'Klexikon');
});

test('the shares of the text by the way it came about', () => {
  const [extract, written, assembled] = compendium.sections.map((section) => section.text.length);
  const total = extract + written + assembled;

  assert.deepEqual(shares(compendium), [
    { kind: 'extract', chars: extract, share: extract / total },
    { kind: 'written', chars: written, share: written / total },
    { kind: 'assembled', chars: assembled, share: assembled / total },
  ]);
});
