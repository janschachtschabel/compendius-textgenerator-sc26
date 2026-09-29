// Question and answer pairs (D66): each pair with its level, and how the pairs came about - asked by the rules
// from the sentences of the text, or written by the LLM.

import { h, link } from './dom.mjs';
import { facts, infoPart, resolutionFacts, technical } from './panels.mjs';
import { formatNumber } from './stats.mjs';
import { label, QA_METHODS } from './texts.mjs';

const HOW = {
  'rule-based': 'Die Regeln bilden die Fragen aus dem Satzbau des Textes; jede Antwort ist ein Satz des Textes.',
  llm: 'Die KI hat Fragen und Antworten aus dem Text formuliert.',
};

export function renderQa(answer, run) {
  const pairs = answer.pairs ?? [];
  const body = h(
    'div',
    { class: 'document' },
    h('h2', {}, answer.topic ? `Fragen und Antworten zu „${answer.topic}“` : 'Fragen und Antworten zum Text'),
    h('p', { class: 'lead-note' }, Object.hasOwn(HOW, answer.method) ? HOW[answer.method] : ''),
    answer.note ? h('p', { class: 'note' }, answer.note) : null,
    h(
      'ol',
      { class: 'qa-list' },
      pairs.map((pair) =>
        h(
          'li',
          {},
          h('p', { class: 'question' }, pair.question),
          h('p', { class: 'answer' }, pair.answer),
          pair.level ? h('p', { class: 'level' }, `Stufe: ${pair.level}`) : null,
        ),
      ),
    ),
  );
  const asked = run.request.body?.method;
  const info = h(
    'section',
    { class: 'info' },
    h('h2', {}, 'Wie kamen die Paare zustande?'),
    infoPart(
      'Methode und Vorlage',
      facts([
        ['Angefragt', asked ? label(QA_METHODS, asked) : 'wie im Profil'],
        ['Verwendet', label(QA_METHODS, answer.method)],
        ['Zeichen der Vorlage', formatNumber(answer.chars ?? 0)],
        ['Knoten', answer.node ? link(answer.node.render_url, answer.node.title) : null],
      ]),
    ),
    answer.resolution ? infoPart('Thema und Artikel', facts(resolutionFacts(answer))) : null,
    technical(run),
  );
  return { body, info };
}
