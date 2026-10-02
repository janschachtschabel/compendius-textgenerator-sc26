// What a collection or a material does in a request, as the page tells it under the field (D77; Jan, 2026-10-02:
// "sichtbar machen was passiert wenn jemand z.b. statt dem thema nur die sammlungsid als input gibt (oder beides)").
import { test } from 'node:test';
import assert from 'node:assert/strict';

import { nodeLine, nodeUses } from '../../app/ui/static/node_use.mjs';

const OPTIK = { kind: 'collection', title: 'Optik', subjects: ['Physik'], educational_contexts: ['Sekundarstufe I'], topic: 'Optik' };
const STATION = { kind: 'material', title: 'Stationsarbeit zur Optik', subjects: ['Physik'], educational_contexts: [], topic: 'Optik' };
const compendium = (values) => ({ topic: '', subject: '', preset: 'balanced', parts: ['world', 'curricula', 'collection'], ...values });

test('the line under the field says what the node is', () => {
  assert.equal(nodeLine(OPTIK), 'Sammlung „Optik“ · Physik · Sekundarstufe I');
  assert.equal(nodeLine(STATION), 'Material „Stationsarbeit zur Optik“ · Physik');
});

test('a collection without a topic gives the topic, its level and subject, and part 3', () => {
  assert.deepEqual(nodeUses('compendium', compendium({}), OPTIK), [
    'Thema: „Optik“, der Titel der Sammlung.',
    'Dazu kommen die Stufe Sekundarstufe I und das Fach Physik.',
    'Teil 3 beschreibt die Sammlung.',
  ]);
});

test('in a writing profile the model words the topic from the collection first', () => {
  const [topic] = nodeUses('compendium', compendium({ preset: 'best-coverage-generated' }), OPTIK);

  assert.equal(topic, 'Thema: „Optik“, der Titel der Sammlung; die KI formuliert es zuerst aus Titel, Fächern, Schlagwörtern und Beschreibung.');
});

test('a topic sent along leads, the collection adds level and subject, and part 3 needs its box', () => {
  assert.deepEqual(nodeUses('compendium', compendium({ topic: 'Licht', subject: 'Physik', parts: ['world'] }), OPTIK), [
    'Thema: „Licht“ wie eingegeben.',
    'Dazu kommt die Stufe Sekundarstufe I; das Fach ist gewählt.',
    'Teil 3 entsteht nur, wenn unter „Teile“ die Sammlung angehakt ist.',
  ]);
});

test('the materials of the collection as a source say how much of them part 1 reads', () => {
  const uses = nodeUses('compendium', compendium({ knowledge_source: true, knowledge_fulltext: true, knowledge_depth: '1' }), OPTIK);

  assert.equal(uses.at(-1), 'Quelle für Teil 1: die Materialien der Sammlung, mit ihren Volltexten und den Untersammlungen bis Ebene 1.');
  const plain = nodeUses('compendium', compendium({ knowledge_source: true }), OPTIK);
  assert.equal(plain.at(-1), 'Quelle für Teil 1: die Materialien der Sammlung, ihre Beschreibungen.');
});

test('a material gives the article of its title and description, and no part 3', () => {
  assert.deepEqual(nodeUses('compendium', compendium({ preset: 'llm-free' }), STATION), [
    'Thema: der Artikel aus Titel und Beschreibung des Materials, nach den Regeln „Optik“.',
    'Dazu kommt das Fach Physik.',
    'Teil 3 fällt weg: Es braucht eine Sammlung.',
  ]);
  const unknown = nodeUses('compendium', compendium({ preset: 'llm-free' }), { ...STATION, topic: null });
  assert.equal(unknown[0], 'Thema: Die Regeln finden in Titel und Beschreibung keinen Artikel – bitte ein Thema eingeben.');
});

test('with the LLM choosing articles the model names the article of a material (D47)', () => {
  const [topic] = nodeUses('compendium', compendium({}), STATION);
  const [none] = nodeUses('compendium', compendium({}), { ...STATION, topic: null });

  assert.equal(topic, 'Thema: der Artikel aus Titel und Beschreibung des Materials; die KI nennt ihn (die Regeln fänden „Optik“).');
  assert.equal(none, 'Thema: der Artikel aus Titel und Beschreibung des Materials; die KI nennt ihn (die Regeln fänden keinen).');
});

test('a material beside a topic adds its article as a source when it links with the main article', () => {
  const [topic] = nodeUses('compendium', compendium({ topic: 'Geometrische Optik' }), STATION);

  assert.equal(topic, 'Thema: „Geometrische Optik“ wie eingegeben; das Material kommt als Quelle dazu, wenn sein Artikel mit dem Hauptartikel verlinkt ist.');
});

test('the other modes tell their own use: the topic of knowledge and pairs, the text of entities', () => {
  assert.deepEqual(nodeUses('knowledge', { topic: '', subject: '' }, OPTIK), ['Thema: „Optik“, der Titel der Sammlung.', 'Dazu kommen die Stufe Sekundarstufe I und das Fach Physik.']);
  assert.deepEqual(nodeUses('qa', { topic: '', subject: '', levels: '' }, OPTIK).at(-1), 'Bildet die KI die Paare, verteilt sie sie auf die Stufe Sekundarstufe I.');
  assert.deepEqual(nodeUses('entities', { text: '' }, STATION), ['Text: Titel, Beschreibung und Schlagwörter des Materials.']);
});

test('a node of another repository is an input only: part 3 and the source read the repository of the server', () => {
  const uses = nodeUses('compendium', compendium({ knowledge_source: true }), OPTIK, { foreign: true });

  assert.equal(uses.at(-1), 'Aus einem anderen Repository: Teil 3 und Quelle lesen nur das Repository des Servers.');
  assert.ok(!uses.some((line) => line.startsWith('Teil 3 beschreibt') || line.startsWith('Quelle für Teil 1')));
});
