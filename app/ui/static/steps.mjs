// How the steps of a compendium ran (D66): the method each asked for - the request's own switch, else its profile's
// -, the method it used, and whether the LLM was asked for and the rules did the work. A step whose part was not asked
// for did not run at all, which is no fallback.

import { COMPENDIUM_STEPS } from './forms.mjs';
import { formatCount, formatNumber } from './stats.mjs';

// The methods of the rules: using one where the LLM was asked for is a fallback
const RULES = new Set(['rule-based', 'hybrid_light', 'sources-only']);
// The parts a step works for. The article choice runs where a corpus is built, for part 1 or 2; part 3 alone needs
// no article (app/service.py, _needs_corpus)
const PARTS_OF = {
  article_choice: ['world', 'curricula'],
  matcher: ['world'],
  extraction: ['world'],
  generation: ['world'],
  enrichment: ['world'],
  model_knowledge_check: ['world'],
  curriculum_check: ['curricula'],
};

/** One row per step: step, asked, used, applies, parts, fellBack and a note of what the LLM did there. */
export function stepsAccount(answer, request, preset, options) {
  const llm = answer?.audit?.llm ?? {};
  const switches = options.presets.find((profile) => profile.id === preset)?.switches ?? {};
  const requested = request?.parts ?? [];
  return COMPENDIUM_STEPS.map((step) => {
    const asked = request?.[step] ?? switches[step];
    const parts = PARTS_OF[step];
    const applies = parts.some((part) => requested.includes(part));
    if (!applies) return { step, asked, used: null, applies, parts, fellBack: false, note: null };
    const used = USED[step](answer ?? {}, llm, asked);
    if (step === 'article_choice') return { step, asked, used, applies, parts, ...articleChoice(llm, asked, used) };
    if (step === 'curriculum_check') return { step, asked, used, applies, parts, ...curriculumCheck(llm.curriculum_check, answer?.curricula) };
    if (step === 'model_knowledge_check') return { step, asked, used, applies, parts, ...knowledgeCheck(llm.model_knowledge_check) };
    const fellBack = Boolean(used && used !== asked && RULES.has(used) && !RULES.has(asked));
    return { step, asked, used, applies, parts, fellBack, note: NOTES[step](llm) };
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
  model_knowledge_check: (answer, llm, asked) => (llm.model_knowledge_check?.requested === 'llm' ? llm.model_knowledge_check.used : asked),
  curriculum_check: (answer, llm, asked) => (llm.curriculum_check?.requested === 'llm' ? llm.curriculum_check.used : asked),
};

const NOTES = {
  matcher: (llm) => (llm.matching?.requested === 'llm' ? `${formatNumber(llm.matching.answered ?? 0)} von ${formatCount(llm.matching.paragraphs ?? 0, 'Absatz', 'Absätzen')} von der KI zugeordnet` : null),
  extraction: () => null,
  generation: (llm) => (llm.generation?.sections?.length ? `${formatCount(llm.generation.sections.length, 'Baustein', 'Bausteine')} geschrieben, ${formatCount(llm.generation.dropped_sentences ?? 0, 'Satz', 'Sätze')} verworfen` : null),
  enrichment: (llm) => (llm.generation?.marked_sentences ? `${formatCount(llm.generation.marked_sentences, 'Satz', 'Sätze')} gekennzeichnet` : null),
};

/** Whether the LLM check of curriculum elements (D58) fell back to the rules, and a note of what it did, from its block
 * in the audit of a compendium or the answer of the curriculum search; `curricula` is part 2 or that answer.
 *
 * The rules deciding are a fallback only with a reason: the model was not asked (fallback: an unavailable b-api), or
 * elements it was offered stayed unrated (fallbacks, by reason: a spent budget). With no element to rate - none
 * found, or no curricula - the service asks it nothing (app/sources/lehrplan/part.py) and the audit says rule-based
 * all the same (app/compendium/llm_report.py): nothing to check is no fallback. */
export function curriculumCheck(check, curricula) {
  if (check?.requested !== 'llm') return { fellBack: false, note: null };
  if (!check.fallback && !check.rated) {
    return { fellBack: false, note: curricula?.available === false ? 'nichts zu prüfen: Lehrpläne nicht verfügbar' : 'nichts zu prüfen: kein Lehrplanelement gefunden' };
  }
  const reasons = [check.fallback, ...Object.keys(check.fallbacks ?? {})].filter(Boolean);
  const counts = check.rated ? `${formatNumber(check.answered ?? 0)} von ${formatNumber(check.rated)} bewertet, ${formatNumber(check.dropped ?? 0)} entfernt` : null;
  return { fellBack: check.used !== 'llm' && reasons.length > 0, note: [counts, ...reasons].filter(Boolean).join('; ') };
}

/** Whether the check of model knowledge (07, point 12a) fell back, and a note of what it did, from its block in the
 * audit. It reads only sentences marked [Modellwissen]: a text without any had nothing to check, which is no
 * fallback; one is a block whose sentences stayed unchecked, with the reason (fallbacks, by block). */
export function knowledgeCheck(check) {
  if (check?.requested !== 'llm') return { fellBack: false, note: null };
  const reasons = [...new Set(Object.values(check.fallbacks ?? {}))];
  if (!check.checked && !reasons.length) return { fellBack: false, note: 'nichts zu prüfen: kein Satz aus Modellwissen' };
  const counts = check.checked ? `${formatCount(check.checked, 'Satz', 'Sätze')} geprüft, ${formatNumber(check.struck ?? 0)} gestrichen, ${formatNumber(check.corrected ?? 0)} berichtigt` : null;
  return { fellBack: check.used !== 'llm' && reasons.length > 0, note: [counts, ...reasons].filter(Boolean).join('; ') };
}

// The rules keeping the article need not be a fallback: `used` stays rule-based where there was nothing to ask
// (`needed` false) and where the model answered and changed nothing. It is one only with a reason - of the question
// itself, of the articles of the topic (D63), of the check of the side articles, or, when the model was asked nothing,
// the note of the LLM layer, which names an unavailable b-api (app/compendium/assembly.py)
function articleChoice(llm, asked, used) {
  const block = llm.article_choice;
  if (!block) return { fellBack: false, note: null };
  const askedSomething = Boolean(block.asked || block.articles_asked || block.hits_checked);
  const reason = block.fallback ?? block.articles_fallback ?? block.hits_fallback ?? (askedSomething ? null : llm.note ?? null);
  const fellBack = used === 'rule-based' && !RULES.has(asked) && Boolean(reason);
  const parts = [];
  if (block.articles_found?.length) parts.push(`KI nannte: ${block.articles_found.join(', ')}`);
  if (block.chosen) parts.push(`gewählt: ${block.chosen}`);
  if (block.hits_dropped?.length) parts.push(`verworfen: ${block.hits_dropped.join(', ')}`);
  if (fellBack) parts.push(`Regeln, weil: ${reason}`);
  else if (used === 'rule-based' && !RULES.has(asked)) parts.push(!block.needed ? 'die Regeln waren sicher' : askedSomething ? 'die KI änderte nichts an der Wahl der Regeln' : 'die KI wurde nicht gefragt');
  return { fellBack, note: parts.join('; ') || null };
}
