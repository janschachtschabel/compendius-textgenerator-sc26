// Quality, time and cost of an answer as the review page counts them (D66).
import { test } from 'node:test';
import assert from 'node:assert/strict';

import { countWords, formatDuration, metrics } from '../../app/ui/static/stats.mjs';

const byKey = (items) => Object.fromEntries(items.map((item) => [item.key, item]));

const compendium = {
  resolution: { title: 'Optik', confident: true, method: 'title' },
  sections: [
    { status: 'maschinell-extraktiv', text: 'Die Optik ist die Lehre vom Licht. [1]' },
    { status: 'ki-generiert', text: 'Licht wird gebrochen. [2] <!-- f: Evidenzgrad=Modellwissen -->Mehr. [Modellwissen]<!-- /f -->' },
    { status: 'leer', text: '' },
  ],
  sources: [{ source_id: 'a' }, { source_id: 'b' }],
  curricula: { entries: [{}, {}, {}] },
  collection: { summary: { materials: 168, missing_descriptions: 50 } },
  audit: {
    sections_filled: 2,
    sections_empty: 1,
    citations: 2,
    lint: [{ rule: 'x' }],
    timings_ms: { resolve: 800, corpus: 1200 },
    llm_tokens: { prompt: 900, completion: 100, total: 1000, calls: 3 },
  },
  markdown: 'x <!-- f: Evidenzgrad=Modellwissen -->Mehr. [Modellwissen]<!-- /f -->',
};

test('words count letters and digits, not markers and signs', () => {
  assert.equal(countWords('Die Optik [1] – ist <!-- f: x --> die Lehre vom Licht. [Modellwissen] 1905'), 8);
  assert.equal(countWords(''), 0);
});

test('a duration reads in seconds with one decimal, under a second in milliseconds', () => {
  assert.equal(formatDuration(15246), '15,2 s');
  assert.equal(formatDuration(1000), '1,0 s');
  assert.equal(formatDuration(380.4), '380 ms');
});

test('a compendium counts its quality, its time and its cost', () => {
  const found = byKey(metrics('compendium', compendium, 15246));

  assert.deepEqual(
    Object.fromEntries(Object.entries(found).map(([key, item]) => [key, [item.dimension, item.value, item.display]])),
    {
      article: ['quality', null, 'Optik (sicher, exakter Titel)'],
      sections: ['quality', 2, '2 von 3'],
      citations: ['quality', 2, '2'],
      words: ['quality', 11, '11'],
      written: ['quality', 1, '1'],
      model_knowledge: ['quality', 1, '1'],
      sources: ['quality', 2, '2'],
      lint: ['quality', 1, '1'],
      curricula: ['quality', 3, '3'],
      collection: ['quality', 168, '168, davon 50 ohne Beschreibung'],
      elapsed: ['time', 15246, '15,2 s'],
      server: ['time', 2000, '2,0 s'],
      tokens: ['cost', 1000, '1.000'],
      calls: ['cost', 3, '3'],
    },
  );
  assert.deepEqual(
    Object.values(found).filter((item) => item.headline).map((item) => item.key),
    ['article', 'sections', 'citations', 'elapsed', 'tokens'],
  );
});

test('a compendium without an LLM costs no tokens', () => {
  const found = byKey(metrics('compendium', { ...compendium, audit: { ...compendium.audit, llm_tokens: null } }, 1000));

  assert.equal(found.tokens.value, 0);
  assert.equal(found.tokens.display, 'keine');
  assert.equal(found.calls, undefined);
});

test('knowledge texts count their articles and characters', () => {
  const found = byKey(metrics('knowledge', { resolution: { title: 'Optik', confident: false, method: 'search' }, articles: [{}, {}], chars: 13244, truncated: true, article_choice: { tokens: 480 } }, 400));

  assert.equal(found.article.display, 'Optik (unsicher, Volltextsuche)');
  assert.equal(found.articles.value, 2);
  assert.equal(found.chars.display, '13.244, gekürzt');
  assert.equal(found.tokens.value, 480);
});

test('a curriculum search counts what it found, showed and cut', () => {
  const found = byKey(metrics('lehrplan', { total_hits: 69629, cut_hits: 49629, excluded_noise: 3, matches: [{}, {}], llm_tokens: null }, 700));

  assert.equal(found.hits.display, '69.629');
  assert.equal(found.shown.value, 2);
  assert.equal(found.cut.value, 49629);
  assert.equal(found.noise.value, 3);
  assert.equal(found.tokens.value, 0);
});

test('entities count by way and link, with what the LLM cost', () => {
  const found = byKey(
    metrics('entities', { methods: ['llm'], entities: [{ source: 'llm', linked: true }, { source: 'llm', linked: false }], llm: { total_tokens: 812, calls: 2 } }, 3000),
  );

  assert.equal(found.entities.value, 2);
  assert.equal(found.linked.display, '1 von 2');
  assert.equal(found.ways.display, 'KI');
  assert.equal(found.tokens.value, 812);
  assert.equal(found.calls.value, 2);
});

test('question pairs say that the service does not report the tokens of the LLM', () => {
  const rules = byKey(metrics('qa', { method: 'rule-based', pairs: [{}, {}, {}], chars: 7993 }, 2000));
  const llm = byKey(metrics('qa', { method: 'llm', pairs: [{}], chars: 7993 }, 9000));

  assert.equal(rules.pairs.value, 3);
  assert.equal(rules.method.display, 'Regeln aus dem Satzbau');
  assert.equal(rules.tokens.display, 'keine');
  assert.equal(llm.tokens.value, null);
  assert.equal(llm.tokens.display, 'nicht gemeldet');
});

test('question pairs say "keine" tokens only where the request asked no LLM for anything', () => {
  const options = {
    preset_default: 'balanced',
    presets: [
      { id: 'llm-free', switches: { article_choice: 'rule-based' } },
      { id: 'balanced', switches: { article_choice: 'llm' } },
      { id: 'best-quality', switches: { article_choice: 'llm-thorough' } },
    ],
    qa: { profiles: { 'llm-free': 'rule-based', balanced: 'rule-based', 'best-quality': 'llm' } },
  };
  const rules = { method: 'rule-based', pairs: [{}], chars: 900 };
  const tokens = (request) => byKey(metrics('qa', rules, 2000, { request, options })).tokens.display;

  // A node's article is the profile's to choose (app/api/v2/qa.py): balanced asks the LLM
  assert.equal(tokens({ node_id: 'n1', preset: 'balanced' }), 'nicht gemeldet');
  assert.equal(tokens({ node_id: 'n1', preset: 'llm-free' }), 'keine');
  // The article of a topic the rules choose in every profile (D55)
  assert.equal(tokens({ topic: 'Optik', preset: 'balanced' }), 'keine');
  assert.equal(tokens({ text: 'Ein Satz.', preset: 'balanced' }), 'keine');
  // Pairs the LLM was asked for and the rules made after all may still have cost tokens
  assert.equal(tokens({ topic: 'Optik', preset: 'best-quality' }), 'nicht gemeldet');
  assert.equal(tokens({ topic: 'Optik', preset: 'llm-free', method: 'llm' }), 'nicht gemeldet');
  assert.equal(tokens({ topic: 'Optik', preset: 'best-quality', method: 'rule-based' }), 'keine');
});
