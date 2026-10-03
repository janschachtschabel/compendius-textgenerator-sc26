// Which method each step of a compendium asked for, which it used, and whether it fell back to the rules (D66).
import { test } from 'node:test';
import assert from 'node:assert/strict';

import { stepsAccount } from '../../app/ui/static/steps.mjs';
import { formatCount } from '../../app/ui/static/stats.mjs';

const options = {
  presets: [
    { id: 'llm-free', switches: { article_choice: 'rule-based', matcher: 'hybrid_light', extraction: 'rule-based', generation: 'rule-based', enrichment: 'sources-only', model_knowledge_check: 'rule-based', curriculum_check: 'rule-based' } },
    { id: 'best-quality-generated', switches: { article_choice: 'llm-thorough', matcher: 'llm', extraction: 'rule-based', generation: 'llm', enrichment: 'model-knowledge', model_knowledge_check: 'rule-based', curriculum_check: 'llm' } },
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
      model_knowledge_check: ['rule-based', false],
      curriculum_check: ['rule-based', true],
    },
  );
  assert.equal(rows.curriculum_check.note, 'Budget erschöpft', 'the model was asked nothing, so there is nothing to count');
});

const checkRow = (check, curricula = { available: true, entries: [] }) =>
  byStep(stepsAccount({ extraction: 'rule-based', generation: 'llm', enrichment: 'model-knowledge', curricula, audit: { llm: { curriculum_check: check } } }, { parts: ['world', 'curricula'] }, 'best-quality-generated', options)).curriculum_check;

test('a check of the curricula with no element to rate is no fallback: it had nothing to check', () => {
  // The service asks the model only about elements the rules found (app/sources/lehrplan/part.py); without any, or
  // without curricula, it asks nothing, and the audit says rule-based without a reason (app/compendium/llm_report.py)
  const nothing = { requested: 'llm', used: 'rule-based', rated: 0, answered: 0, dropped: 0, fallbacks: {}, fallback: null };

  assert.deepEqual([checkRow(nothing).fellBack, checkRow(nothing).note], [false, 'nichts zu prüfen: kein Lehrplanelement gefunden']);
  assert.deepEqual([checkRow(nothing, { available: false }).fellBack, checkRow(nothing, { available: false }).note], [false, 'nichts zu prüfen: Lehrpläne nicht verfügbar']);
});

test('a check whose elements the model rated none of falls back, and says why', () => {
  const row = checkRow({ requested: 'llm', used: 'rule-based', rated: 3, answered: 0, dropped: 0, fallbacks: { 'Token-Budget der Anfrage erschöpft': 3 }, fallback: null });

  assert.equal(row.fellBack, true);
  assert.equal(row.note, '0 von 3 bewertet, 0 entfernt; Token-Budget der Anfrage erschöpft');
});

test('a check the model did answers says how many elements it rated and dropped', () => {
  const row = checkRow({ requested: 'llm', used: 'llm', rated: 4, answered: 3, dropped: 1, fallbacks: { 'nicht bewertet': 1 }, fallback: null });

  assert.deepEqual([row.used, row.fellBack, row.note], ['llm', false, '3 von 4 bewertet, 1 entfernt; nicht bewertet']);
});

const balanced = { presets: [...options.presets, { id: 'balanced', switches: { ...options.presets[0].switches, article_choice: 'llm' } }] };
const choiceRow = (block, parts = ['world'], note = undefined) =>
  byStep(stepsAccount({ extraction: 'rule-based', generation: 'rule-based', enrichment: 'sources-only', audit: { llm: { article_choice: block, note } } }, { parts }, 'balanced', balanced)).article_choice;

test('the article choice runs only for part 1 or 2, which need an article', () => {
  const row = choiceRow({ requested: 'llm', used: 'rule-based', needed: false }, ['collection']);

  assert.equal(row.applies, false);
  assert.equal(row.fellBack, false);
  assert.deepEqual(row.parts, ['world', 'curricula']);
  assert.equal(choiceRow({ requested: 'llm', used: 'llm', needed: true }, ['curricula']).applies, true);
});

test('the article choice falls back only with a reason, and says it', () => {
  const outage = choiceRow({ requested: 'llm', used: 'rule-based', needed: true, asked: false }, ['world'], 'b-api nicht erreichbar; Regelmodus verwendet');
  const cut = choiceRow({ requested: 'llm', used: 'rule-based', needed: true, articles_fallback: 'Budget erschöpft' });

  assert.equal(outage.fellBack, true);
  assert.match(outage.note, /b-api nicht erreichbar/);
  assert.equal(cut.fellBack, true);
  assert.match(cut.note, /Budget erschöpft/);
});

test('rules that were sure, or a model that changed nothing, are no fallback', () => {
  const sure = choiceRow({ requested: 'llm', used: 'rule-based', needed: false });
  const agreed = choiceRow({ requested: 'llm', used: 'rule-based', needed: true, asked: true, offered: 3 });

  assert.equal(sure.fellBack, false);
  assert.equal(sure.note, 'die Regeln waren sicher');
  assert.equal(agreed.fellBack, false);
  assert.equal(agreed.note, 'die KI änderte nichts an der Wahl der Regeln');
  assert.equal(choiceRow({ requested: 'llm', used: 'rule-based', needed: true }).note, 'die KI wurde nicht gefragt');
});

test('a model that found no candidate of the rules fitting says so, and what took the place (A01)', () => {
  const overview = choiceRow({ requested: 'llm', used: 'llm', needed: true, asked: true, offered: 5, rejected: true, chosen: 'Funktion (Mathematik)' });

  assert.equal(overview.fellBack, false);
  assert.equal(overview.note, 'keiner der Kandidaten der Regeln passte; gewählt: Funktion (Mathematik)');
});

test('a switch the request set wins over its profile', () => {
  const answer = { extraction: 'llm', generation: 'rule-based', enrichment: 'sources-only', audit: { matcher: 'bm25', llm: { extraction: { requested: 'llm', used: 'llm' } } } };
  const rows = byStep(stepsAccount(answer, { parts: ['world'], matcher: 'bm25', extraction: 'llm' }, 'llm-free', options));

  assert.equal(rows.matcher.asked, 'bm25');
  assert.equal(rows.matcher.used, 'bm25');
  assert.equal(rows.extraction.asked, 'llm');
  assert.equal(rows.extraction.fellBack, false);
});

// The check of model knowledge (07, point 12a): what it read, struck and corrected; nothing to check is no fallback
const knowledgeRow = (block) =>
  byStep(stepsAccount({ extraction: 'rule-based', generation: 'llm', enrichment: 'model-knowledge-full', audit: { llm: { model_knowledge_check: block } } }, { parts: ['world'], model_knowledge_check: 'llm' }, 'best-quality-generated', options)).model_knowledge_check;

test('a check of the model knowledge says what it read, struck and corrected', () => {
  const row = knowledgeRow({ requested: 'llm', used: 'llm', sections: ['sc26_1'], checked: 40, struck: 3, corrected: 2, fallbacks: {} });

  assert.deepEqual([row.used, row.fellBack, row.note], ['llm', false, '40 Sätze geprüft, 3 gestrichen, 2 berichtigt']);
});

test('a check of the model knowledge says how many sentences got no verdict', () => {
  const row = knowledgeRow({ requested: 'llm', used: 'llm', sections: ['sc26_1'], checked: 38, unchecked: 2, struck: 3, corrected: 2, fallbacks: {} });

  assert.equal(row.note, '38 Sätze geprüft, 2 ohne Urteil, 3 gestrichen, 2 berichtigt');
});

test('a check of the model knowledge whose answers gave no verdict fell back and says why (audit 2026-10-03, F06)', () => {
  const reason = 'die Antwort nannte zu keinem Satz ein Urteil';
  const row = knowledgeRow({ requested: 'llm', used: 'rule-based', sections: [], checked: 0, unchecked: 7, struck: 0, corrected: 0, fallbacks: { sc26_3: reason } });

  assert.deepEqual([row.used, row.fellBack, row.note], ['rule-based', true, reason]);
});

test('a check of the model knowledge with no such sentence had nothing to check, which is no fallback', () => {
  const row = knowledgeRow({ requested: 'llm', used: 'rule-based', sections: [], checked: 0, struck: 0, corrected: 0, fallbacks: {} });

  assert.deepEqual([row.fellBack, row.note], [false, 'nichts zu prüfen: kein Satz aus Modellwissen']);
});

test('a check of the model knowledge the model could not do falls back, and says why', () => {
  const row = knowledgeRow({ requested: 'llm', used: 'rule-based', sections: [], checked: 0, struck: 0, corrected: 0, fallbacks: { sc26_1: 'Antwort nicht lesbar' } });

  assert.deepEqual([row.fellBack, row.note], [true, 'Antwort nicht lesbar']);
});
