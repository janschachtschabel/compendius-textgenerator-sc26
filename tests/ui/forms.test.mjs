// What the review page sends for its forms, and what it refuses before sending (D66).
import { test } from 'node:test';
import assert from 'node:assert/strict';

import { buildRequests, defaults, FORMS, fromExample, nodeIdOf, problems } from '../../app/ui/static/forms.mjs';

const COLLECTION = '9e7ae956-e9df-430f-bace-f3db4b910013';
const MATERIAL = 'ac66224b-42b0-4676-a53d-71b058dc780b';
const options = {
  preset_default: 'balanced',
  llm_configured: true,
  presets: [{ id: 'llm-free' }, { id: 'balanced' }, { id: 'best-quality' }, { id: 'best-quality-generated' }],
  lehrplan: { modes: ['keyword', 'topic'] },
  entities: { methods: ['ner', 'dictionary', 'llm'], link_checks: ['rule-based', 'llm'] },
  qa: { methods: ['rule-based', 'llm'] },
  limits: {
    compendium: { topic: { max_length: 300 }, target_length: { default: 12000, min: 2000, max: 60000 }, max_articles: { default: null, min: 1, max: 50 } },
    knowledge: { topic: { max_length: 300 }, max_articles: { default: null, min: 1, max: 50 }, max_chars: { default: null, min: 100 } },
    lehrplan: { q: { min_length: 3, max_length: 200 }, limit: { default: 50, min: 1, max: 500 } },
    entities: { max_entities: { default: 50, min: 1, max: 200 } },
    qa: { topic: { max_length: 300 }, count: { default: 5, min: 1, max: 50 }, max_answer_length: { default: 300, min: 50, max: 2000 } },
  },
};
const form = (mode, values) => ({ ...defaults(mode, options), ...values });

test('an id is found in a link to the node, and other text stays as it is', () => {
  assert.equal(nodeIdOf(`https://repository.staging.openeduhub.net/edu-sharing/components/collections?id=${COLLECTION}`), COLLECTION);
  assert.equal(nodeIdOf(`  ${MATERIAL} `), MATERIAL);
  assert.equal(nodeIdOf('Optik'), 'Optik');
});

test('a topic alone asks for the compendium with the default parts and profile', () => {
  const [run] = buildRequests('compendium', form('compendium', { topic: ' Optik ' }), options);

  assert.equal(run.preset, 'balanced');
  assert.deepEqual(run.request, {
    method: 'POST',
    path: 'api/v2/compendium',
    body: { topic: 'Optik', parts: ['world', 'curricula'], preset: 'balanced', facets_visible: false, empty_slot_policy: 'omit' },
  });
});

test('the box for empty blocks is sent either way, so a template cannot say otherwise, and starts as the default template', () => {
  const [run] = buildRequests('compendium', form('compendium', { topic: 'Optik', template_id: 'standard' }), options);

  assert.equal(run.request.body.empty_slot_policy, 'omit');
  assert.equal(defaults('compendium', options).empty_note, false);
  assert.equal(defaults('compendium', { ...options, empty_note: true }).empty_note, true);
});

test('every input of the form reaches the request, ids taken from links', () => {
  const [run] = buildRequests(
    'compendium',
    form('compendium', {
      topic: 'Optik',
      subject: 'Physik',
      collection_id: `https://example.org/x?id=${COLLECTION}`,
      knowledge_collection_id: COLLECTION,
      node_id: MATERIAL,
      repository: 'https://repository.staging.openeduhub.net/edu-sharing/rest',
      parts: ['world', 'curricula', 'collection'],
      preset: 'best-quality',
      matcher: 'bm25',
      generation: 'llm-fast',
      target_length: '8000',
      max_articles: '5',
      template_id: 'standard',
      facets_visible: true,
      empty_note: true,
    }),
    options,
  );

  assert.deepEqual(run.request.body, {
    topic: 'Optik',
    subject: 'Physik',
    collection_id: COLLECTION,
    knowledge_collection_id: COLLECTION,
    node_id: MATERIAL,
    repository: 'https://repository.staging.openeduhub.net/edu-sharing/rest',
    parts: ['world', 'curricula', 'collection'],
    preset: 'best-quality',
    matcher: 'bm25',
    generation: 'llm-fast',
    target_length: 8000,
    max_articles: 5,
    template_id: 'standard',
    facets_visible: true,
    empty_slot_policy: 'note',
  });
});

test('a comparison asks twice, once per profile, and leaves the steps to the profiles', () => {
  const runs = buildRequests('compendium', form('compendium', { topic: 'Optik', compare: true, preset: 'llm-free', preset_b: 'best-quality', matcher: 'llm' }), options);

  assert.deepEqual(runs.map((run) => run.preset), ['llm-free', 'best-quality']);
  assert.deepEqual(runs.map((run) => run.request.body.preset), ['llm-free', 'best-quality']);
  assert.ok(runs.every((run) => !('matcher' in run.request.body)));
});

test('the compendium form refuses what the endpoint would refuse, in words a reader understands', () => {
  assert.ok(problems('compendium', form('compendium', {}), options).topic);
  assert.ok(problems('compendium', form('compendium', { topic: 'Optik', collection_id: 'keine-id' }), options).collection_id);
  assert.ok(problems('compendium', form('compendium', { topic: 'Optik', parts: [] }), options).parts);
  assert.ok(problems('compendium', form('compendium', { topic: 'Optik', parts: ['collection'] }), options).collection_id);
  assert.ok(problems('compendium', form('compendium', { topic: 'Optik', parts: ['curricula'], knowledge_collection_id: COLLECTION }), options).knowledge_collection_id);
  assert.ok(problems('compendium', form('compendium', { topic: 'Optik', repository: 'https://x.example/rest' }), options).repository);
  assert.ok(problems('compendium', form('compendium', { topic: 'Optik', compare: true, preset: 'balanced', preset_b: 'balanced' }), options).preset_b);
  assert.ok(problems('compendium', form('compendium', { topic: 'Optik', target_length: '100' }), options).target_length);
  assert.ok(problems('compendium', form('compendium', { topic: 'Optik', max_articles: 'viele' }), options).max_articles);
  assert.deepEqual(problems('compendium', form('compendium', { topic: 'Optik' }), options), {});
  assert.deepEqual(problems('compendium', form('compendium', { collection_id: COLLECTION }), options), {});
});

test('knowledge texts for a topic or a node', () => {
  const [run] = buildRequests('knowledge', form('knowledge', { topic: 'Optik', max_articles: '3', article_choice: 'llm-thorough' }), options);

  assert.deepEqual(run.request, {
    method: 'POST',
    path: 'api/v2/knowledge',
    body: { topic: 'Optik', preset: 'balanced', max_articles: 3, article_choice: 'llm-thorough' },
  });
  assert.ok(problems('knowledge', form('knowledge', {}), options).topic);
});

test('an empty number field leaves the value to the server', () => {
  const [run] = buildRequests('lehrplan', form('lehrplan', { q: 'Optik', limit: ' 20 ' }), options);

  assert.equal(run.request.query.limit, 20);
  assert.ok(!('max_entities' in buildRequests('entities', form('entities', { text: 'x' }), options)[0].request.body));
});

test('the lists of the forms come from the server, a value the page has no words for under its own name', () => {
  const choices = (mode, name, served) => Object.keys(FORMS[mode].fields.find((field) => field.name === name).choices(served));
  const more = { ...options, lehrplan: { modes: ['keyword', 'topic', 'fuzzy'] }, qa: { methods: ['llm'] } };

  assert.deepEqual(choices('lehrplan', 'mode', options), ['keyword', 'topic']);
  assert.deepEqual(choices('lehrplan', 'mode', more), ['keyword', 'topic', 'fuzzy']);
  assert.equal(FORMS.lehrplan.fields.find((field) => field.name === 'mode').choices(more).fuzzy, 'fuzzy');
  assert.deepEqual(choices('entities', 'link_check', options), ['rule-based', 'llm']);
  assert.deepEqual(choices('qa', 'method', more), ['llm']);
});

test('the bounds of the forms come from the server, and a number goes as a number', () => {
  const wider = { ...options, limits: { ...options.limits, qa: { ...options.limits.qa, topic: { max_length: 400 } }, lehrplan: { q: { min_length: 2 }, limit: { min: 1, max: 1000 } } } };
  const long = 'x'.repeat(350);

  assert.ok(problems('qa', form('qa', { topic: long }), options).topic);
  assert.deepEqual(problems('qa', form('qa', { topic: long }), wider), {});
  assert.ok(problems('lehrplan', form('lehrplan', { q: 'Optik', limit: '800' }), options).limit);
  assert.deepEqual(problems('lehrplan', form('lehrplan', { q: 'ab', limit: '800' }), wider), {});
  // "1e2" is an integer the page lets through; as text the query would be a 422 of the endpoint
  assert.equal(buildRequests('lehrplan', form('lehrplan', { q: 'Optik', limit: '1e2' }), options)[0].request.query.limit, 100);
});

test('the curriculum search is a query of the address', () => {
  const [run] = buildRequests('lehrplan', form('lehrplan', { q: 'Optik', subject: 'Physik', mode: 'topic', curriculum_check: 'llm' }), options);

  assert.deepEqual(run.request, {
    method: 'GET',
    path: 'api/v2/lehrplan/search',
    query: { q: 'Optik', subject: 'Physik', mode: 'topic', preset: 'balanced', curriculum_check: 'llm' },
  });
  assert.ok(problems('lehrplan', form('lehrplan', { q: 'ab' }), options).q);
});

test('entities of a text or of a node, never of both', () => {
  const [run] = buildRequests('entities', form('entities', { text: 'Humboldt reiste nach Quito.', methods: ['ner', 'llm'] }), options);

  assert.deepEqual(run.request.body, { text: 'Humboldt reiste nach Quito.', preset: 'balanced', link: true, methods: ['ner', 'llm'] });
  assert.ok(problems('entities', form('entities', { text: 'x', node_id: MATERIAL }), options).text);
  assert.ok(problems('entities', form('entities', {}), options).text);
  assert.ok(problems('entities', form('entities', { text: 'x', link: false, link_check: 'llm' }), options).link_check);
});

test('a comparison sends no check of links, so a check left in the locked field keeps nothing from being sent', () => {
  const values = form('entities', { text: 'x', link: false, link_check: 'llm', compare: true, preset: 'llm-free', preset_b: 'balanced' });

  assert.deepEqual(problems('entities', values, options), {});
  assert.ok(buildRequests('entities', values, options).every((run) => !('link_check' in run.request.body)));
});

test('question pairs of a text, or of a topic with its levels', () => {
  const [run] = buildRequests('qa', form('qa', { topic: 'Optik', subject: 'Physik', count: '8', levels: 'Sek I, Sek II ,', method: 'llm' }), options);

  assert.deepEqual(run.request.body, {
    topic: 'Optik',
    subject: 'Physik',
    preset: 'balanced',
    method: 'llm',
    count: 8,
    levels: ['Sek I', 'Sek II'],
  });
  assert.ok(problems('qa', form('qa', { text: 'Ein Satz.', topic: 'Optik' }), options).text);
  assert.ok(problems('qa', form('qa', {}), options).topic);
  assert.ok(problems('qa', form('qa', { text: 'Ein Satz.', subject: 'Physik' }), options).subject);
});

test('an example fills its fields and leaves the others at their defaults', () => {
  const values = fromExample('compendium', { label: 'x', values: { topic: 'Linse', subject: 'Physik' } }, options);

  assert.equal(values.topic, 'Linse');
  assert.equal(values.subject, 'Physik');
  assert.deepEqual(values.parts, ['world', 'curricula']);
  assert.equal(values.preset, 'balanced');
});

test('the facets start as the server shows them and are always sent as chosen', () => {
  assert.equal(defaults('compendium', { ...options, facets_visible: true }).facets_visible, true);
  const [run] = buildRequests('compendium', form('compendium', { topic: 'Optik', facets_visible: false }), { ...options, facets_visible: true });

  assert.equal(run.request.body.facets_visible, false);
});

test('without an LLM on the server the forms start with the profile that needs none', () => {
  assert.equal(defaults('compendium', { ...options, llm_configured: false }).preset, 'llm-free');
  assert.notEqual(defaults('compendium', options).preset_b, defaults('compendium', options).preset);
});
