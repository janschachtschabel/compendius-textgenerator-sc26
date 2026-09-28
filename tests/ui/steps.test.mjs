// Which method each step of a compendium asked for, which it used, and whether it fell back to the rules (D66).
import { test } from 'node:test';
import assert from 'node:assert/strict';

import { stepsAccount } from '../../app/ui/static/steps.mjs';
import { formatCount } from '../../app/ui/static/stats.mjs';

const options = {
  presets: [
    { id: 'llm-free', switches: { article_choice: 'rule-based', matcher: 'hybrid_light', extraction: 'rule-based', generation: 'rule-based', enrichment: 'sources-only', curriculum_check: 'rule-based' } },
    { id: 'best-quality-generated', switches: { article_choice: 'llm-thorough', matcher: 'llm', extraction: 'rule-based', generation: 'llm', enrichment: 'model-knowledge', curriculum_check: 'llm' } },
  ],
};
const byStep = (rows) => Object.fromEntries(rows.map((row) => [row.step, row]));

test('a count reads in the singular for one', () => {
  assert.equal(formatCount(1, 'Satz', 'Sätze'), '1 Satz');
  assert.equal(formatCount(11, 'Satz', 'Sätze'), '11 Sätze');
  assert.equal(formatCount(1200, 'Satz', 'Sätze'), '1.200 Sätze');
});

test('the rules of llm-free are asked and used, nothing falls back', () => {
  const answer = { extraction: 'rule-based', generation: 'rule-based', enrichment: 'sources-only', audit: { matcher: 'hybrid_light', llm: null } };
  const rows = stepsAccount(answer, { parts: ['world', 'curricula'] }, 'llm-free', options);

  assert.ok(rows.every((row) => row.applies && !row.fellBack && row.used === row.asked));
});

test('the article choice the LLM made counts as the method asked for, however thorough', () => {
  const answer = {
    extraction: 'rule-based',
    generation: 'llm',
    enrichment: 'model-knowledge',
    audit: { llm: { article_choice: { requested: 'llm-thorough', used: 'llm', articles_found: ['Optik'] }, matching: { requested: 'llm', used: 'llm', answered: 35, paragraphs: 35 } } },
  };
  const rows = byStep(stepsAccount(answer, { parts: ['world'] }, 'best-quality-generated', options));

  assert.equal(rows.article_choice.used, 'llm-thorough');
  assert.equal(rows.article_choice.fellBack, false);
  assert.equal(rows.matcher.used, 'llm');
});

test('a step whose part was not asked for did not run, and did not fall back either', () => {
  const answer = { extraction: 'rule-based', generation: 'llm', enrichment: 'model-knowledge', audit: { llm: { curriculum_check: { requested: 'llm', used: 'rule-based' } } } };
  const rows = byStep(stepsAccount(answer, { parts: ['world'] }, 'best-quality-generated', options));

  assert.equal(rows.curriculum_check.applies, false);
  assert.equal(rows.curriculum_check.fellBack, false);
  const withoutWorld = byStep(stepsAccount(answer, { parts: ['curricula'] }, 'best-quality-generated', options));
  assert.deepEqual(['matcher', 'extraction', 'generation', 'enrichment'].map((step) => withoutWorld[step].applies), [false, false, false, false]);
});

test('a step the LLM was asked for and the rules did falls back', () => {
  const answer = {
    extraction: 'rule-based',
    generation: 'rule-based',
    enrichment: 'sources-only',
    audit: {
      matcher: 'llm',
      llm: {
        article_choice: { requested: 'llm-thorough', used: 'rule-based', fallback: 'b-api nicht erreichbar' },
        matching: { requested: 'llm', used: 'rule-based', answered: 0, paragraphs: 35 },
        curriculum_check: { requested: 'llm', used: 'rule-based', fallback: 'Budget erschöpft' },
      },
    },
  };
  const rows = byStep(stepsAccount(answer, { parts: ['world', 'curricula'] }, 'best-quality-generated', options));

  assert.deepEqual(
    Object.fromEntries(Object.entries(rows).map(([step, row]) => [step, [row.used, row.fellBack]])),
    {
      article_choice: ['rule-based', true],
      matcher: ['hybrid_light', true],
      extraction: ['rule-based', false],
      generation: ['rule-based', true],
      enrichment: ['sources-only', true],
      curriculum_check: ['rule-based', true],
    },
  );
  assert.match(rows.curriculum_check.note, /Budget erschöpft/);
});

test('a switch the request set wins over its profile', () => {
  const answer = { extraction: 'llm', generation: 'rule-based', enrichment: 'sources-only', audit: { matcher: 'bm25', llm: { extraction: { requested: 'llm', used: 'llm' } } } };
  const rows = byStep(stepsAccount(answer, { parts: ['world'], matcher: 'bm25', extraction: 'llm' }, 'llm-free', options));

  assert.equal(rows.matcher.asked, 'bm25');
  assert.equal(rows.matcher.used, 'bm25');
  assert.equal(rows.extraction.asked, 'llm');
  assert.equal(rows.extraction.fellBack, false);
});
