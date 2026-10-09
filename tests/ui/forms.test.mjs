// What the review page sends for its forms, and what it refuses before sending (D66).
import { test } from 'node:test';
import assert from 'node:assert/strict';

import { buildRequests, defaults, FORMS, fromExample, nodeIdOf, problems } from '../../app/ui/static/forms.mjs';

const COLLECTION = '9e7ae956-e9df-430f-bace-f3db4b910013';
const MATERIAL = 'ac66224b-42b0-4676-a53d-71b058dc780b';
const options = {
  preset_default: 'balanced',
  llm_configured: true,
  repository: 'repository.staging.openeduhub.net',
  presets: [{ id: 'llm-free' }, { id: 'balanced' }, { id: 'best-quality' }, { id: 'best-quality-generated' }],
  lehrplan: { modes: ['keyword', 'topic'] },
  entities: { methods: ['ner', 'dictionary', 'llm'], link_checks: ['rule-based', 'llm'] },
  qa: { methods: ['rule-based', 'llm'] },
  limits: {
    compendium: { topic: { max_length: 300 }, target_length: { default: 30000, min: 2000, max: 60000 }, max_articles: { default: null, min: 1, max: 50 }, knowledge_depth: { default: 0, min: 0, max: 5 } },
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
      node: `https://example.org/x?id=${COLLECTION}`,
      node_kind: 'collection',
      knowledge_source: true,
      knowledge_depth: '2',
      knowledge_fulltext: true,
      parts: ['world', 'curricula', 'collection'],
      preset: 'best-quality',
      matcher: 'bm25',
      generation: 'llm-fast',
      target_length: '8000',
      max_articles: '5',
      template_id: 'standard',
      facets_visible: true,
      empty_note: true,
      model_knowledge_label: true,
    }),
    options,
  );

  assert.deepEqual(run.request.body, {
    topic: 'Optik',
    subject: 'Physik',
    collection_id: COLLECTION,
    knowledge_collection_id: COLLECTION,
    knowledge_depth: 2,
    knowledge_fulltext: true,
    parts: ['world', 'curricula', 'collection'],
    preset: 'best-quality',
    matcher: 'bm25',
    generation: 'llm-fast',
    target_length: 8000,
    max_articles: 5,
    template_id: 'standard',
    facets_visible: true,
    empty_slot_policy: 'note',
    model_knowledge_label: true,
  });
});

test('the label of model knowledge starts off and goes out only when the box is ticked (D76)', () => {
  assert.equal(defaults('compendium', options).model_knowledge_label, false);
  const [plain] = buildRequests('compendium', form('compendium', { topic: 'Optik' }), options);
  const [labelled] = buildRequests('compendium', form('compendium', { topic: 'Optik', model_knowledge_label: true }), options);

  assert.equal('model_knowledge_label' in plain.request.body, false);
  assert.equal(labelled.request.body.model_knowledge_label, true);
});

test('a comparison asks twice, once per profile, and leaves the steps to the profiles', () => {
  const runs = buildRequests('compendium', form('compendium', { topic: 'Optik', compare: true, preset: 'llm-free', preset_b: 'best-quality', matcher: 'llm' }), options);

  assert.deepEqual(runs.map((run) => run.preset), ['llm-free', 'best-quality']);
  assert.deepEqual(runs.map((run) => run.request.body.preset), ['llm-free', 'best-quality']);
  assert.ok(runs.every((run) => !('matcher' in run.request.body)));
});

test('the box beside the profile has the AI choose the sentences in any profile, in a comparison in both', () => {
  const [single] = buildRequests('compendium', form('compendium', { topic: 'Optik', preset: 'llm-free', extraction: 'llm' }), options);
  const runs = buildRequests('compendium', form('compendium', { topic: 'Optik', compare: true, preset: 'balanced', preset_b: 'best-quality', extraction: 'llm', matcher: 'llm' }), options);

  assert.equal(single.request.body.extraction, 'llm');
  assert.deepEqual(runs.map((run) => run.request.body.extraction), ['llm', 'llm']);
  assert.ok(runs.every((run) => !('matcher' in run.request.body)), 'the other steps stay with the profiles');
});

test('unticked the profile chooses the sentences; the box follows the profile and left "Erweitert"', () => {
  const [run] = buildRequests('compendium', form('compendium', { topic: 'Optik' }), options);
  const names = FORMS.compendium.fields.map((field) => field.name);
  const steps = FORMS.compendium.fields.find((field) => field.type === 'steps').steps;

  assert.equal('extraction' in run.request.body, false);
  assert.equal(names.indexOf('extraction'), names.indexOf('preset') + 1);
  assert.equal(steps.includes('extraction'), false);
});

test('the compendium form refuses what the endpoint would refuse, in words a reader understands', () => {
  assert.ok(problems('compendium', form('compendium', {}), options).topic);
  const collection = { node: COLLECTION, node_kind: 'collection' };
  assert.ok(problems('compendium', form('compendium', { topic: 'Optik', node: 'keine-id' }), options).node);
  assert.ok(problems('compendium', form('compendium', { topic: 'Optik', parts: [] }), options).parts);
  assert.ok(problems('compendium', form('compendium', { topic: 'Optik', parts: ['collection'] }), options).node);
  assert.ok(problems('compendium', form('compendium', { topic: 'Optik', parts: ['collection'], node: MATERIAL, node_kind: 'material' }), options).node);
  assert.ok(problems('compendium', form('compendium', { topic: 'Optik', parts: ['curricula'], ...collection, knowledge_source: true }), options).knowledge_source);
  assert.ok(problems('compendium', form('compendium', { topic: 'Optik', ...collection, knowledge_source: true, knowledge_depth: '6' }), options).knowledge_depth);
  // Without the source they are not sent, and their fields do not show
  assert.deepEqual(problems('compendium', form('compendium', { topic: 'Optik', knowledge_depth: '6', knowledge_fulltext: true }), options), {});
  assert.ok(problems('compendium', form('compendium', { topic: 'Optik', repository: 'https://x.example/rest' }), options).repository);
  assert.ok(problems('compendium', form('compendium', { topic: 'Optik', compare: true, preset: 'balanced', preset_b: 'balanced' }), options).preset_b);
  assert.ok(problems('compendium', form('compendium', { topic: 'Optik', target_length: '100' }), options).target_length);
  assert.ok(problems('compendium', form('compendium', { topic: 'Optik', max_articles: 'viele' }), options).max_articles);
  assert.deepEqual(problems('compendium', form('compendium', { topic: 'Optik' }), options), {});
  assert.deepEqual(problems('compendium', form('compendium', { node: COLLECTION }), options), {});
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
  assert.ok(problems('entities', form('entities', { text: 'x', node: MATERIAL }), options).text);
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

test('an example holds its own values, numbers as a number field holds them, and the rest of its input empty', () => {
  const values = fromExample('compendium', { label: 'x', values: { topic: 'Linse', subject: 'Physik', max_articles: 5 } });

  assert.deepEqual(values, {
    topic: 'Linse',
    subject: 'Physik',
    max_articles: '5',
    node: '',
    node_kind: '',
    knowledge_source: '',
    knowledge_depth: '',
    knowledge_fulltext: '',
    repository: '',
  });
});

test('an example in the words of the API fills the one field: a collection with its source, or a material (D77)', () => {
  const STAGING = 'https://repository.staging.openeduhub.net/edu-sharing/rest';
  const both = fromExample('compendium', { label: 'x', values: { topic: 'Optik', collection_id: COLLECTION, knowledge_collection_id: COLLECTION, knowledge_depth: 1, knowledge_fulltext: true } });
  const source = fromExample('compendium', { label: 'x', values: { topic: 'Optik', knowledge_collection_id: COLLECTION } });
  const material = fromExample('compendium', { label: 'x', values: { node_id: MATERIAL, repository: STAGING } });

  assert.deepEqual([both.node, both.node_kind, both.knowledge_source, both.knowledge_depth, both.knowledge_fulltext], [COLLECTION, 'collection', true, '1', true]);
  assert.deepEqual([source.node, source.node_kind, source.knowledge_source], [COLLECTION, 'collection', true]);
  assert.deepEqual([material.node, material.node_kind, material.repository], [MATERIAL, '', STAGING]);
  assert.ok(!('collection_id' in both) && !('knowledge_collection_id' in source) && !('node_id' in material));
});

test('one field for a collection or a material: a collection is collection_id, a material or a node not read yet node_id (D77)', () => {
  const body = (values) => buildRequests('compendium', form('compendium', { topic: 'Optik', ...values }), options)[0].request.body;
  const read = body({ node: COLLECTION, node_kind: 'collection' });
  assert.deepEqual([read.collection_id, read.node_id], [COLLECTION, undefined]);
  assert.equal(body({ node: MATERIAL, node_kind: 'material' }).node_id, MATERIAL);
  assert.equal(body({ node: COLLECTION, node_kind: '' }).node_id, COLLECTION, 'the service takes a collection there as collection_id');
  // The materials as a source come only from a collection read as one, their depth only with them
  assert.ok(!('knowledge_collection_id' in body({ node: MATERIAL, node_kind: 'material', knowledge_source: true })));
  assert.ok(!('knowledge_depth' in body({ node: COLLECTION, node_kind: 'collection', knowledge_depth: '2' })));
  // Another repository: the node is an input only; the server's own named: the collection stays collection_id
  const PRODUCTION = 'https://redaktion.openeduhub.net/edu-sharing/rest';
  const foreign = body({ node: COLLECTION, node_kind: 'collection', repository: PRODUCTION, knowledge_source: true });
  assert.deepEqual([foreign.node_id, foreign.repository, foreign.collection_id, foreign.knowledge_collection_id], [COLLECTION, PRODUCTION, undefined, undefined]);
  const own = body({ node: COLLECTION, node_kind: 'collection', repository: 'https://repository.staging.openeduhub.net/edu-sharing/rest' });
  assert.deepEqual([own.collection_id, own.node_id, own.repository], [COLLECTION, undefined, undefined]);
});

test('the input an example sets is the one of its mode', () => {
  assert.deepEqual(fromExample('qa', { label: 'x', values: { text: 'Ein Satz.' } }), {
    text: 'Ein Satz.',
    topic: '',
    node: '',
    node_kind: '',
    repository: '',
  });
  assert.deepEqual(fromExample('lehrplan', { label: 'x', values: { q: 'Optik', mode: 'topic' } }), { q: 'Optik', mode: 'topic' });
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
