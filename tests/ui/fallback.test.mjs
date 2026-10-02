// A compendium the rules wrote although the LLM was asked (Jan, 2026-10-02): with the b-api answering 502 the page
// said "best-coverage-generated · von der KI vollständig zum Thema geschrieben" over a verbatim text. Its head, the
// status line and a box above the text now say what happened, with the reason the service gave.
import { test } from 'node:test';
import assert from 'node:assert/strict';

import { installDocument } from './dom_stub.mjs';
import { OPTIONS, saved } from './saved_answers.mjs';
import { renderResults, summary } from '../../app/ui/static/results.mjs';

const NOTE = 'LLM nicht verfügbar (b-api nicht erreichbar: b-api nach 1 Versuchen nicht erreichbar (HTTP 502)); Regelmodus verwendet';

/** The saved answer of a writing profile as the service gives it when the LLM does not answer: every step by the
 * rules, no token spent, and the note why. */
function withoutLlm() {
  const { run } = saved('compendium_material');
  const llm = {
    ...run.data.audit.llm,
    note: NOTE,
    article_choice: { requested: 'llm', used: 'rule-based', needed: true, asked: false },
    matching: { requested: 'llm', used: 'rule-based', paragraphs: 0, answered: 0 },
    generation: { requested: 'llm', used: 'rule-based', sections: [], marked_sentences: 0 },
  };
  const body = { ...run.request.body, preset: 'best-coverage-generated' };
  const audit = { ...run.data.audit, llm, llm_tokens: null };
  return {
    ...run,
    preset: 'best-coverage-generated',
    request: { ...run.request, body },
    data: { ...run.data, generation: 'rule-based', enrichment: 'sources-only', audit },
  };
}

function shownFor(run) {
  installDocument();
  return renderResults('compendium', [run], { options: OPTIONS, announce() {}, suggest() {} });
}

const textOf = (element, name) => element.descendants().find((node) => node.classList.contains(name))?.textContent ?? null;

test('a compendium the rules wrote although the LLM was asked says so in its head, above its text and in the status', () => {
  const run = withoutLlm();
  const results = shownFor(run);

  assert.equal(textOf(results, 'profile-name'), 'best-coverage-generated · ohne KI');
  assert.doesNotMatch(results.textContent, /von der KI vollständig zum Thema geschrieben/);
  assert.match(textOf(results, 'fallback'), /^Ohne KI erzeugt/);
  assert.match(textOf(results, 'fallback'), /HTTP 502/);
  assert.equal(summary('compendium', [run], OPTIONS), 'Kompendium fertig: best-coverage-generated · ohne KI 1,2 s.');
});

test('a compendium the LLM wrote keeps the name of its profile and gets no box', () => {
  const { run } = saved('compendium_material');
  const results = shownFor(run);

  assert.match(textOf(results, 'profile-name'), /^best-quality-generated · /);
  assert.doesNotMatch(textOf(results, 'profile-name'), /ohne KI/);
  assert.equal(textOf(results, 'fallback'), null);
  assert.doesNotMatch(summary('compendium', [run], OPTIONS), /ohne KI/);
});

test('a step that fell back while the LLM did the others shows as partly without it', () => {
  const { run } = saved('compendium_material');
  const llm = { ...run.data.audit.llm, article_choice: { requested: 'llm', used: 'rule-based', needed: true, asked: true, fallback: 'Antwort unlesbar' } };
  const partly = { ...run, data: { ...run.data, audit: { ...run.data.audit, llm } } };
  const results = shownFor(partly);

  assert.match(textOf(results, 'profile-name'), / · teils ohne KI$/);
  assert.match(textOf(results, 'fallback'), /^Teilweise ohne KI.*Artikelwahl/);
  assert.match(summary('compendium', [partly], OPTIONS), /teils ohne KI 1,2 s\.$/);
});

test('two profiles compared name the one the rules wrote alone as without the LLM in the table as well', () => {
  installDocument();
  const { run } = saved('compendium_material');
  const results = renderResults('compendium', [run, withoutLlm()], { options: OPTIONS, announce() {}, suggest() {} });
  const heads = results.descendants().filter((node) => node.tagName === 'TH' && node.getAttribute('scope') === 'col').map((node) => node.textContent);

  assert.ok(heads.includes('best-coverage-generated · ohne KI'), heads.join(' | '));
});
