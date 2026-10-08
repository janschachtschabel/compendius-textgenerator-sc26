// Quality, time and cost of an answer as the review page counts them (D66).
import { test } from 'node:test';
import assert from 'node:assert/strict';

import { saved } from './saved_answers.mjs';
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
  assert.equal(countWords('a <!-- b'), 2, 'a comment that never closes stays text');
});

test('words count in time linear in the text, however many comments stay open', () => {
  const text = `Licht ${'<!--'.repeat(50_000)} bricht`;

  const start = performance.now();
  const words = countWords(text);
  const ms = performance.now() - start;

  assert.equal(words, 2);
  assert.ok(ms < 500, `${Math.round(ms)} ms for ${text.length} characters`);
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

test('the time of a compendium in the service is the whole request where the service names it: its stages overlap', () => {
  const found = byKey(metrics('compendium', { ...compendium, audit: { ...compendium.audit, duration_ms: 1500 } }, 15246));

  assert.deepEqual([found.server.value, found.server.display], [1500, '1,5 s']);
});

test('a compendium counts the tokens its model read from the prompt cache, where there were any (D69)', () => {
  const tokens = { prompt: 90000, completion: 11150, total: 101150, calls: 24, cached: 50936 };
  const found = byKey(metrics('compendium', { ...compendium, audit: { ...compendium.audit, llm_tokens: tokens } }, 37000));

  assert.deepEqual([found.cached.dimension, found.cached.value, found.cached.display, found.cached.headline], ['cost', 50936, '50.936', false]);
  assert.equal(byKey(metrics('compendium', compendium, 1000)).cached, undefined);
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

test('a curriculum search counts the calls of the LLM it reports, as the other endpoints do', () => {
  const { run } = saved('lehrplan_topic');

  const found = byKey(metrics('lehrplan', run.data, 700));

  assert.equal(found.tokens.value, 96);
  assert.equal(found.calls.value, 4);
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

test('question pairs count what the LLM cost, as the service reports it', () => {
  const rules = byKey(metrics('qa', { method: 'rule-based', pairs: [{}, {}, {}], chars: 7993, llm_tokens: null }, 2000));
  const llm = byKey(metrics('qa', { method: 'llm', pairs: [{}], chars: 7993, llm_tokens: { prompt: 1100, completion: 134, total: 1234, calls: 2 } }, 9000));

  assert.equal(rules.pairs.value, 3);
  assert.equal(rules.method.display, 'Regeln aus dem Satzbau');
  assert.equal(rules.tokens.display, 'keine');
  assert.equal(llm.tokens.value, 1234);
  assert.equal(llm.tokens.display, '1.234');
  assert.equal(llm.calls.value, 2);
});
