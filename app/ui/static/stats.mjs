// Quality, time and cost of one answer, per endpoint (D66): what the metrics bar shows and a comparison sets side
// by side. Each item has a key, its dimension, a number to compare (null where there is none) and the words to show.
// Cost is tokens and calls: the service reports no prices, and a price per token differs by model and contract.

import { ENTITY_METHODS, label, QA_METHODS, RESOLUTION } from './texts.mjs';

const NUMBER = new Intl.NumberFormat('de-DE');
const SECONDS = new Intl.NumberFormat('de-DE', { minimumFractionDigits: 1, maximumFractionDigits: 1 });
const SERVICE_MARKERS = /\[(?:\d{1,4}|Modellwissen)\]/g;
const WORD = /[\p{L}\p{N}]+(?:[-'’.][\p{L}\p{N}]+)*/gu;
const MODEL_KNOWLEDGE_OPEN = '<!-- f: Evidenzgrad=Modellwissen -->';

export function formatNumber(value) {
  return NUMBER.format(value);
}

/** A number with its noun: the singular for one, else the plural. */
export function formatCount(n, one, many) {
  return `${NUMBER.format(n)} ${n === 1 ? one : many}`;
}

/** A duration as a reader takes it in: milliseconds under a second, else seconds with one decimal. */
export function formatDuration(ms) {
  return ms < 1000 ? `${NUMBER.format(Math.round(ms))} ms` : `${SECONDS.format(ms / 1000)} s`;
}

/** Words of a text as a reader counts them: without the comments, evidence numbers and labels of the service. */
export function countWords(text) {
  return (withoutComments(String(text ?? '')).replace(SERVICE_MARKERS, ' ').match(WORD) ?? []).length;
}

// The text with a space for each comment, in one pass. A pattern tried the rest of the text again for every "<!--"
// that never closes: 200,000 characters of them took 2.6 s. Such an opener stays text, as it did then
function withoutComments(text) {
  let out = '';
  let at = 0;
  for (let open = text.indexOf('<!--'); open >= 0; open = text.indexOf('<!--', at)) {
    const close = text.indexOf('-->', open + 4);
    if (close < 0) break; // no later opener can close either
    out += `${text.slice(at, open)} `;
    at = close + 3;
  }
  return out + text.slice(at);
}

/** The metrics of one answer of an endpoint, in the order a reader looks for them. */
export function metrics(mode, answer, elapsedMs) {
  const a = answer ?? {};
  return [...MEASURES[mode](a), time('elapsed', 'Dauer', elapsedMs, true), ...(TIMES[mode]?.(a) ?? []), ...COSTS[mode](a)];
}

const MEASURES = {
  compendium(a) {
    const audit = a.audit ?? {};
    const sections = a.sections ?? [];
    const filled = audit.sections_filled ?? 0;
    const items = [
      article(a.resolution),
      quality('sections', 'Bausteine gefüllt', filled, true, `${filled} von ${filled + (audit.sections_empty ?? 0)}`),
      quality('citations', 'Belege', audit.citations ?? 0, true),
      quality('words', 'Wörter in Teil 1', sections.reduce((sum, section) => sum + countWords(section.text), 0)),
      quality('written', 'Von der KI formulierte Bausteine', sections.filter((section) => section.status === 'ki-generiert').length),
      quality('model_knowledge', 'Sätze Modellwissen ohne Beleg', String(a.markdown ?? '').split(MODEL_KNOWLEDGE_OPEN).length - 1),
      quality('sources', 'Quellenartikel', (a.sources ?? []).length),
      quality('lint', 'Hinweise der Prüfung', (audit.lint ?? []).length),
    ];
    if (a.curricula) items.push(quality('curricula', 'Lehrplanelemente', (a.curricula.entries ?? []).length));
    const materials = a.collection?.summary?.materials;
    if (materials !== undefined) {
      const missing = a.collection.summary.missing_descriptions ?? 0;
      items.push(quality('collection', 'Inhalte der Sammlung', materials, false, `${formatNumber(materials)}${missing ? `, davon ${formatNumber(missing)} ohne Beschreibung` : ''}`));
    }
    return items;
  },
  knowledge(a) {
    const chars = a.chars ?? 0;
    return [
      article(a.resolution),
      quality('articles', 'Artikel', (a.articles ?? []).length, true),
      quality('chars', 'Zeichen', chars, true, `${formatNumber(chars)}${a.truncated ? ', gekürzt' : ''}`),
    ];
  },
  lehrplan(a) {
    return [
      quality('hits', 'Treffer', a.total_hits ?? 0, true),
      quality('shown', 'Gezeigt', (a.matches ?? []).length, true),
      quality('cut', 'Jenseits der Suchgrenze', a.cut_hits ?? 0),
      quality('noise', 'Als Rauschen verworfen', a.excluded_noise ?? 0),
    ];
  },
  entities(a) {
    const entities = a.entities ?? [];
    const linked = entities.filter((entity) => entity.linked).length;
    return [
      quality('entities', 'Entitäten', entities.length, true),
      quality('linked', 'Mit Artikel verknüpft', linked, true, `${linked} von ${entities.length}`),
      quality('ways', 'Wege', null, false, (a.methods ?? []).map((method) => label(ENTITY_METHODS, method)).join(', ')),
    ];
  },
  qa(a) {
    return [
      quality('pairs', 'Paare', (a.pairs ?? []).length, true),
      quality('method', 'Methode', null, true, label(QA_METHODS, a.method)),
      quality('chars', 'Zeichen der Vorlage', a.chars ?? 0),
    ];
  },
};

// The server's own account of its time, where it gives one: the stages of a compendium
const TIMES = {
  compendium: (a) => [time('server', 'davon im Dienst', Object.values(a.audit?.timings_ms ?? {}).reduce((sum, ms) => sum + ms, 0), false)],
};

const COSTS = {
  compendium: (a) => llmCost(a.audit?.llm_tokens?.total, a.audit?.llm_tokens?.calls),
  knowledge: (a) => llmCost(a.article_choice?.tokens),
  lehrplan: (a) => llmCost(a.llm_tokens?.total, a.llm_tokens?.calls),
  entities: (a) => llmCost(a.llm?.total_tokens, a.llm?.calls),
  qa: (a) => llmCost(a.llm_tokens?.total, a.llm_tokens?.calls),
};

function llmCost(tokens, calls) {
  const items = [cost('tokens', 'Tokens', tokens ?? 0, true, tokens ? formatNumber(tokens) : 'keine')];
  if (calls) items.push(cost('calls', 'KI-Aufrufe', calls, false));
  return items;
}

function article(resolution) {
  if (!resolution?.title) return quality('article', 'Artikel', null, true, 'keiner');
  const sureness = resolution.confident ? 'sicher' : 'unsicher';
  const way = resolution.method ? `, ${label(RESOLUTION, resolution.method)}` : '';
  return quality('article', 'Artikel', null, true, `${resolution.title} (${sureness}${way})`);
}

function quality(key, text, value, headline = false, display = undefined) {
  return item(key, 'quality', text, value, headline, display);
}

function time(key, text, ms, headline) {
  return item(key, 'time', text, ms, headline, formatDuration(ms));
}

function cost(key, text, value, headline, display = undefined) {
  return item(key, 'cost', text, value, headline, display);
}

function item(key, dimension, text, value, headline, display) {
  return { key, dimension, label: text, value, display: display ?? formatNumber(value ?? 0), headline };
}
