// The knowledge texts of a topic (D66): the articles the corpus of a compendium would use, word for word, each
// saying how it was found, and below them what the article choice asked and decided.

import { h, link } from './dom.mjs';
import { facts, infoPart, nodeArticleFacts, resolutionFacts, technical } from './panels.mjs';
import { formatNumber } from './stats.mjs';
import { label, ORIGINS, PROJECTS, STEPS } from './texts.mjs';

export function renderKnowledge(answer, run) {
  const articles = answer.articles ?? [];
  const body = h(
    'div',
    { class: 'document' },
    h('h2', {}, `Wissenstexte: ${answer.topic}`),
    h('p', { class: 'lead-note' }, `${articles.length} Artikel, ${formatNumber(answer.chars ?? 0)} Zeichen${answer.truncated ? ', am Zeichendeckel gekürzt' : ''}. Die Texte stehen hier wörtlich, wie die Archive sie liefern.`),
    articles.map((article) => card(article)),
  );
  const info = h(
    'section',
    { class: 'info' },
    h('h2', {}, 'Wie kamen diese Artikel zustande?'),
    infoPart('Thema und Artikel', facts([...resolutionFacts(answer), ...nodeArticleFacts(answer.node_article, answer, run.request.body)])),
    choice(answer.article_choice),
    technical(run),
  );
  return { body, info };
}

function card(article) {
  return h(
    'details',
    { class: 'source-article', open: article.is_primary },
    h(
      'summary',
      {},
      h('h3', { class: 'article-title' }, article.title),
      h('span', { class: 'origin-badge' }, label(ORIGINS, article.origin)),
      h('span', { class: 'article-meta' }, `${label(PROJECTS, article.project)} · ${formatNumber(article.chars)} Zeichen`),
    ),
    h('p', { class: 'article-link' }, link(article.url, 'Artikel im Lexikon öffnen')),
    (article.sections ?? []).map((section) => [
      // Under the article's h3: a section of the second level (the first below the title) is an h4
      section.heading ? h(`h${Math.min(Math.max(section.level, 2) + 2, 6)}`, {}, section.heading) : null,
      paragraphs(section.text),
    ]),
  );
}

// Article text as the archive gives it, not markdown: each paragraph set as text
function paragraphs(text) {
  return String(text ?? '')
    .split(/\n\s*\n/)
    .map((paragraph) => paragraph.trim())
    .filter(Boolean)
    .map((paragraph) => h('p', {}, paragraph));
}

function choice(block) {
  if (!block) return infoPart('Artikelwahl', h('p', {}, 'Die Regeln haben allein gewählt; keine Tokens.'));
  const values = STEPS.article_choice.values;
  return infoPart(
    'Artikelwahl',
    facts([
      ['Angefragt', label(values, block.requested)],
      ['Verwendet', label(values, block.used)],
      ['Von der KI genannt', block.articles_found],
      ['Übersichtsartikel', block.articles_overview],
      ['Gewählt', block.chosen],
      ['Verworfen', block.hits_dropped],
      ['Warum die Regeln blieben', block.fallback ?? block.articles_fallback],
      ['Hinweis', block.note],
      ['Tokens', block.tokens ? formatNumber(block.tokens) : null],
    ]),
  );
}
