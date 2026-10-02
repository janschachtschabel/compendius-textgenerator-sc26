// The field of a collection or a material (D77): it reads the node through the page, says under the field what it is
// and does, and offers the materials of a collection as a source only once reading showed a collection.
import { test } from 'node:test';
import assert from 'node:assert/strict';

import { installDocument } from './dom_stub.mjs';
import { OPTIONS } from './saved_answers.mjs';
import { ApiError } from '../../app/ui/static/api.mjs';
import { buildForm } from '../../app/ui/static/fields.mjs';
import { defaults, fromExample } from '../../app/ui/static/forms.mjs';

const COLLECTION = '9e7ae956-e9df-430f-bace-f3db4b910013';
const MATERIAL = 'ac66224b-42b0-4676-a53d-71b058dc780b';
const UNKNOWN = '00000000-0000-4000-8000-000000000000';
const READ = { description: '', keywords: [], repository: 'https://repository.staging.openeduhub.net/edu-sharing/rest', render_url: 'https://x' };
const OPTIK = { ...READ, node_id: COLLECTION, kind: 'collection', title: 'Optik', subjects: ['Physik'], educational_contexts: ['Sekundarstufe I'], topic: 'Optik' };
const STATION = { ...READ, node_id: MATERIAL, kind: 'material', title: 'Stationsarbeit zur Optik', subjects: ['Physik'], educational_contexts: [], topic: 'Optik' };

async function settle() {
  for (let turn = 0; turn < 10; turn += 1) await new Promise((resolve) => setImmediate(resolve));
}

/** A compendium form whose reader of nodes answers when the test says so, and the readings it asked for. */
function compendiumForm() {
  installDocument();
  const asked = [];
  const lookup = (id, repository) =>
    new Promise((resolve, reject) => asked.push({ id, repository, answer: (data) => resolve({ data }), fail: (error) => reject(error) }));
  const form = buildForm('compendium', OPTIONS, { onSubmit() {}, onExample() {}, lookup });
  form.write(defaults('compendium', OPTIONS));
  const byClass = (name) => form.element.descendants().find((node) => node.classList.contains(name));
  const control = (name) => form.element.descendants().find((node) => node.getAttribute('name') === name);
  // The wrapper the form hides while a field does not apply
  const shows = (name) => !form.element.descendants().find((node) => node.classList.contains('check') && node.contains(control(name))).hidden;
  return { form, asked, byClass, shows };
}

test('a collection read through the page says what it is and does, and offers its materials as a source', async () => {
  const { form, asked, byClass, shows } = compendiumForm();
  assert.equal(shows('knowledge_source'), false, 'no node, no source');

  form.write({ node: `https://repository.staging.openeduhub.net/edu-sharing/components/collections?id=${COLLECTION}` });
  assert.deepEqual(asked.map(({ id, repository }) => [id, repository]), [[COLLECTION, '']]);
  assert.equal(byClass('node-status').textContent, 'Wird gelesen …');
  asked[0].answer(OPTIK);
  await settle();

  assert.equal(byClass('node-status').textContent, 'Sammlung „Optik“ · Physik · Sekundarstufe I');
  assert.deepEqual(byClass('node-uses').children.map((item) => item.textContent), [
    'Thema: „Optik“, der Titel der Sammlung.',
    'Dazu kommen die Stufe Sekundarstufe I und das Fach Physik.',
    'Teil 3 entsteht nur, wenn unter „Teile“ die Sammlung angehakt ist.',
  ]);
  assert.equal(form.read().node_kind, 'collection');
  assert.equal(shows('knowledge_source'), true);
  assert.equal(shows('knowledge_fulltext'), false, 'the full texts only with the source');
  form.write({ knowledge_source: true });
  assert.equal(shows('knowledge_fulltext'), true);
});

test('a material offers no source, and a node the repository does not have says so', async () => {
  const { form, asked, byClass, shows } = compendiumForm();
  form.write({ node: MATERIAL });
  asked[0].answer(STATION);
  await settle();

  assert.equal(form.read().node_kind, 'material');
  assert.equal(shows('knowledge_source'), false);

  form.write({ node: UNKNOWN });
  asked[1].fail(new ApiError(404, { message: 'nicht gefunden' }, 'r-1'));
  await settle();

  assert.equal(byClass('node-status').textContent, 'Keine öffentliche Sammlung und kein Material mit dieser ID im Repository.');
  assert.equal(form.read().node_kind, '');
  assert.deepEqual(byClass('node-uses').children, []);
});

test('an id typed only in part asks nothing, and an answer for an id no longer in the field changes nothing', async () => {
  const { form, asked, byClass } = compendiumForm();
  form.write({ node: '9e7ae956-e9df' });
  assert.equal(asked.length, 0);

  form.write({ node: COLLECTION });
  form.write({ node: MATERIAL });
  asked[0].answer(OPTIK);
  await settle();

  assert.equal(byClass('node-status').textContent, 'Wird gelesen …');
  assert.equal(form.read().node_kind, '');
  asked[1].answer(STATION);
  await settle();
  assert.equal(form.read().node_kind, 'material');
});

test('an example of a collection counts as one before reading it, so its source holds', () => {
  const { form, asked, shows } = compendiumForm();
  const example = OPTIONS.examples.compendium.find((each) => each.values.knowledge_collection_id && !each.values.knowledge_depth);

  form.write(fromExample('compendium', example));

  assert.equal(asked.length, 1);
  assert.equal(form.read().node_kind, 'collection');
  assert.equal(form.read().knowledge_source, true);
  assert.equal(shows('knowledge_source'), true);
});
