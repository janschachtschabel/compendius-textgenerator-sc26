// How the steps of a compendium ran (D66): the method each asked for - the request's own switch, else its profile's
// -, the method it used, and whether the LLM was asked and the rules did the work. A step whose part was not asked
// for did not run at all, which is no fallback.

import { COMPENDIUM_STEPS } from './forms.mjs';
import { formatCount, formatNumber } from './stats.mjs';

// The methods of the rules: using one where the LLM was asked for is a fallback
const RULES = new Set(['rule-based', 'hybrid_light', 'sources-only']);
// The part a step works on; the article choice runs for every part
const PART_OF = { matcher: 'world', extraction: 'world', generation: 'world', enrichment: 'world', curriculum_check: 'curricula' };

/** One row per step: step, asked, used, applies, part, fellBack and a note of what the LLM did there. */
export function stepsAccount(answer, request, preset, options) {
  const llm = answer?.audit?.llm ?? {};
  const switches = options.presets.find((profile) => profile.id === preset)?.switches ?? {};
  const parts = request?.parts ?? [];
  return COMPENDIUM_STEPS.map((step) => {
    const asked = request?.[step] ?? switches[step];
    const part = PART_OF[step] ?? null;
    const applies = !part || parts.includes(part);
    const used = applies ? USED[step](answer ?? {}, llm, asked) : null;
    const fellBack = Boolean(applies && used && used !== asked && RULES.has(used) && !RULES.has(asked));
    return { step, asked, used, applies, part, fellBack, note: applies ? NOTES[step](llm) : null };
  });
}

const USED = {
  // The audit says llm or rule-based; llm is whichever of the LLM's ways the request asked for
  article_choice: (answer, llm, asked) => (llm.article_choice?.used === 'rule-based' ? 'rule-based' : asked),
  // Where the model assigned nothing, hybrid_light decided (the help of matcher in app/domain/requests.py)
  matcher: (answer, llm, asked) => (llm.matching?.requested === 'llm' && llm.matching.used !== 'llm' ? 'hybrid_light' : asked),
  extraction: (answer) => answer.extraction,
  generation: (answer) => answer.generation,
  enrichment: (answer) => answer.enrichment,
  curriculum_check: (answer, llm, asked) => (llm.curriculum_check?.requested === 'llm' ? llm.curriculum_check.used : asked),
};

const NOTES = {
  article_choice: (llm) => choiceNote(llm.article_choice),
  matcher: (llm) => (llm.matching?.requested === 'llm' ? `${formatNumber(llm.matching.answered ?? 0)} von ${formatCount(llm.matching.paragraphs ?? 0, 'Absatz', 'Absätzen')} von der KI zugeordnet` : null),
  extraction: () => null,
  generation: (llm) => (llm.generation?.sections?.length ? `${formatCount(llm.generation.sections.length, 'Baustein', 'Bausteine')} geschrieben, ${formatCount(llm.generation.dropped_sentences ?? 0, 'Satz', 'Sätze')} verworfen` : null),
  enrichment: (llm) => (llm.generation?.marked_sentences ? `${formatCount(llm.generation.marked_sentences, 'Satz', 'Sätze')} gekennzeichnet` : null),
  curriculum_check(llm) {
    const check = llm.curriculum_check;
    if (check?.requested !== 'llm') return null;
    return [`${formatNumber(check.rated ?? 0)} bewertet, ${formatNumber(check.dropped ?? 0)} entfernt`, check.fallback].filter(Boolean).join('; ');
  },
};

function choiceNote(block) {
  if (!block) return null;
  const parts = [];
  if (block.articles_found?.length) parts.push(`KI nannte: ${block.articles_found.join(', ')}`);
  if (block.chosen) parts.push(`gewählt: ${block.chosen}`);
  if (block.hits_dropped?.length) parts.push(`verworfen: ${block.hits_dropped.join(', ')}`);
  if (block.fallback) parts.push(`Regeln, weil: ${block.fallback}`);
  if (!parts.length && block.requested !== 'rule-based' && !block.needed) parts.push('die Regeln waren sicher');
  return parts.join('; ') || null;
}
