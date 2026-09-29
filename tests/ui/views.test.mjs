// The views and forms of the review page as elements, under the stand-in document (D66): headings keep their order,
// the colours of a view have words beside them, an error box stays silent, and every help text belongs to its field.
import { resolveObjectURL } from 'node:buffer';
import { test } from 'node:test';
import assert from 'node:assert/strict';

import { installDocument } from './dom_stub.mjs';
import { fact, shown } from './saved_answers.mjs';
import { buildForm } from '../../app/ui/static/fields.mjs';
import { errorBox, resolutionFacts } from '../../app/ui/static/panels.mjs';
import { renderResults, stopped, stoppedSummary } from '../../app/ui/static/results.mjs';
import { renderEntities } from '../../app/ui/static/view_entities.mjs';
import { renderKnowledge } from '../../app/ui/static/view_knowledge.mjs';
import { renderQa } from '../../app/ui/static/view_qa.mjs';

const PRESETS = ['llm-free', 'balanced', 'best-quality', 'best-quality-generated'];
const OPTIONS = {
  preset_default: 'balanced',
  llm_configured: true,
  facets_visible: false,
  empty_note: false,
  presets: PRESETS.map((id) => ({ id, switches: { article_choice: 'rule-based', matcher: 'hybrid_light', extraction: 'rule-based', generation: 'rule-based', enrichment: 'sources-only', curriculum_check: 'rule-based' } })),
  switches: { article_choice: ['rule-based', 'llm'], matcher: ['hybrid_light', 'llm'], extraction: ['rule-based'], generation: ['rule-based', 'llm'], enrichment: ['sources-only'], curriculum_check: ['rule-based', 'llm'] },
  parts: ['world', 'curricula', 'collection'],
  templates: [{ id: 'sc26', name: 'SC26', slots: 13 }],
  subjects: ['Physik'],
  entities: { methods: ['ner', 'dictionary', 'llm'], link_checks: ['rule-based', 'llm'], link_check_default: 'rule-based', profiles: Object.fromEntries(PRESETS.map((id) => [id, ['ner']])) },
  qa: { methods: ['rule-based', 'llm'], profiles: Object.fromEntries(PRESETS.map((id) => [id, 'rule-based'])) },
  lehrplan: { modes: ['keyword', 'topic'] },
  limits: {},
  examples: { compendium: [{ label: 'Optik', values: { topic: 'Optik' } }] },
};
const run = (path, body) => ({ request: { method: 'POST', path, body }, requestId: 'r1' });
const all = (element, holds) => element.descendants().filter(holds);

test('an article of the knowledge texts is a heading, its sections the levels below it', () => {
  installDocument();
  const article = {
    title: 'Optik',
    origin: 'topic',
    project: 'wikipedia',
    chars: 9,
    url: 'https://de.wikipedia.org/wiki/Optik',
    is_primary: true,
    sections: [
      { level: 2, heading: 'Geschichte', text: 'Früh.' },
      { level: 3, heading: 'Antike', text: 'Alt.' },
    ],
  };

  const { body } = renderKnowledge({ topic: 'Optik', chars: 9, articles: [article] }, run('api/v2/knowledge', { topic: 'Optik' }));

  const headings = all(body, (node) => /^H[1-6]$/.test(node.tagName)).map((node) => [node.tagName, node.textContent]);
  assert.deepEqual(headings, [['H2', 'Wissenstexte: Optik'], ['H3', 'Optik'], ['H4', 'Geschichte'], ['H5', 'Antike']]);
});

test('the colours of the entities in the text have their kinds in words beside them', () => {
  installDocument();
  const text = 'Humboldt reiste nach Quito.';
  const entities = [
    { text: 'Humboldt', kind: 'PER', start: 0, end: 8, source: 'ner' },
    { text: 'Quito', kind: 'LOC', start: 21, end: 26, source: 'ner' },
  ];

  const { body } = renderEntities({ text, entities, methods: ['ner'] }, run('api/v2/entities', { text }));

  const [legend] = all(body, (node) => node.classList.contains('legend'));
  assert.deepEqual(legend.children.map((item) => [item.getAttribute('class'), item.textContent]), [['kind-PER', 'Person'], ['kind-LOC', 'Ort']]);
});

test('the pairs of a topic stand in order with their level, and say which method was asked and which wrote them', () => {
  const results = shown('qa_llm');

  const pairs = all(results, (node) => node.tagName === 'OL' && node.classList.contains('qa-list'))[0].children;
  assert.deepEqual(pairs.map((pair) => pair.children.map((line) => line.textContent)), [
    ['Was untersucht die Optik?', 'Das Licht und seine Ausbreitung.', 'Stufe: Sek I'],
    ['Was bricht Licht?', 'Eine Linse.', 'Stufe: Sek I'],
  ]);
  assert.equal(fact(results, 'Methode und Vorlage', 'Angefragt'), 'wie im Profil');
  assert.equal(fact(results, 'Methode und Vorlage', 'Verwendet'), 'KI');
  assert.match(all(results, (node) => node.classList.contains('lead-note'))[0].textContent, /^Die KI hat Fragen und Antworten/);
});

test('a method of the pairs the page does not know leaves the lead empty, also one named like a property of every object', () => {
  installDocument();

  for (const method of ['constructor', 'neu']) {
    const { body } = renderQa({ method, pairs: [] }, run('api/v2/qa', { text: 'x' }));
    const [lead] = all(body, (node) => node.classList.contains('lead-note'));
    assert.equal(lead.textContent, '', method);
  }
});

test('an error box is no alert: the status line says a run failed, and the box stays silent when its mode comes back', () => {
  installDocument();

  assert.equal(errorBox({ message: 'Zum Thema gibt es keinen Artikel.' }).hasAttribute('role'), false);
});

for (const mode of ['compendium', 'knowledge', 'lehrplan', 'entities', 'qa']) {
  test(`every help text of the ${mode} form is bound to its field, with and without an LLM`, () => {
    for (const llm of [true, false]) {
      installDocument();
      const { element, write } = buildForm(mode, { ...OPTIONS, llm_configured: llm }, { onSubmit() {}, onExample() {} });
      write({ preset: llm ? 'balanced' : 'llm-free' });

      const nodes = element.descendants();
      const ids = new Set(nodes.map((node) => node.id).filter(Boolean));
      const described = new Set(nodes.flatMap((node) => (node.getAttribute('aria-describedby') ?? '').split(' ')).filter(Boolean));
      for (const help of nodes.filter((node) => node.classList.contains('help'))) {
        assert.ok(help.id && described.has(help.id), `${mode} (KI ${llm}): "${help.textContent}" belongs to no field`);
      }
      for (const id of described) assert.ok(ids.has(id), `${mode} (KI ${llm}): ${id} names no element`);
    }
  });
}

test('a stopped comparison keeps the answer that was done, and a run with none done what the mode showed before', () => {
  installDocument();
  const host = { options: OPTIONS, announce() {}, suggest() {} };
  const done = {
    preset: 'llm-free',
    request: { method: 'POST', path: 'api/v2/qa', body: { text: 'Das Licht bricht sich.', preset: 'llm-free' } },
    data: { method: 'rule-based', pairs: [{ question: 'Was bricht sich?', answer: 'Das Licht.' }], chars: 22 },
    elapsedMs: 800,
    requestId: 'r1',
  };
  const before = document.createElement('div');

  const kept = stopped('qa', [done], before, host);

  assert.ok(kept.classList.contains('results'));
  assert.match(kept.textContent, /Was bricht sich\?/);
  assert.equal(stopped('qa', [], before, host), before);
  assert.match(stoppedSummary('qa', [done]), /^Abgebrochen; Fragen & Antworten fertig: llm-free/);
  assert.match(stoppedSummary('qa', []), /^Abgebrochen; die vorige Anzeige bleibt\./);
});

test('a template is named once with its count of blocks, which many names already hold', () => {
  installDocument();
  const templates = [
    { id: 'sc26', name: 'SC26 (13 Bausteine)', slots: 13 },
    { id: 'eigen', name: 'Eigene Vorlage', slots: 4 },
  ];

  const { element } = buildForm('compendium', { ...OPTIONS, templates }, { onSubmit() {}, onExample() {} });

  const choices = element.descendants().filter((node) => node.tagName === 'OPTION' && ['sc26', 'eigen'].includes(node.getAttribute('value')));
  assert.deepEqual(choices.map((node) => node.textContent), ['SC26 (13 Bausteine)', 'Eigene Vorlage (4 Bausteine)']);
});

test('how a topic was found reads alike in every view, with the words that decided and the kind of node', () => {
  installDocument();
  const answer = {
    resolution: { query: 'Linse', title: 'Linse (Optik)', project: 'wikipedia', method: 'title', confident: false, context: ['Physik'] },
    node: { title: 'Optik', kind: 'collection', render_url: 'https://repository.staging.openeduhub.net/x' },
  };

  const rows = Object.fromEntries(resolutionFacts(answer).map(([name, value]) => [name, value?.textContent ?? value]));

  assert.deepEqual(rows['Kontextwörter'], ['Physik']);
  assert.equal(rows['Knoten'], 'Optik (Sammlung)');
});

test('a compendium saves its markdown as a file named for its topic and profile', async () => {
  const doc = installDocument();
  const markdown = ['---', 'topic: Optik', '---', '', '# Kompendium: Optik', '', 'Die Optik ist die Lehre vom Licht.', ''].join('\n');
  const one = {
    preset: 'balanced',
    request: { method: 'POST', path: 'api/v2/compendium', body: { topic: 'Optik', preset: 'balanced' } },
    data: { topic: 'Optik', markdown, sections: [], sources: [], audit: {} },
    elapsedMs: 1200,
    requestId: 'r1',
  };

  const results = renderResults('compendium', [one], { options: OPTIONS, announce() {}, suggest() {} });
  const button = results.descendants().find((node) => node.tagName === 'BUTTON' && node.textContent === 'Markdown speichern');
  button.click();

  const [saved] = doc.downloads;
  assert.match(saved.name, /^kompendium-optik-balanced-\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2}\.md$/);
  const file = resolveObjectURL(saved.href);
  assert.match(file.type, /^text\/markdown/);
  assert.equal(await file.text(), markdown);

  const other = { ...one, preset: 'llm-free', data: { ...one.data, topic: 'Grüne Gentechnik & Ethik?' } };
  const button2 = renderResults('compendium', [other], { options: OPTIONS, announce() {}, suggest() {} })
    .descendants()
    .find((node) => node.tagName === 'BUTTON' && node.textContent === 'Markdown speichern');
  button2.click();
  assert.match(doc.downloads[1].name, /^kompendium-grüne-gentechnik-ethik-llm-free-.+\.md$/);
});
