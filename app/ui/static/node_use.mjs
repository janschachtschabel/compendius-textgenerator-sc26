// What a collection or a material does in a request of the review page, told under its field (D77; Jan, 2026-10-02:
// "sichtbar machen was passiert wenn jemand z.b. statt dem thema nur die sammlungsid als input gibt (oder beides)"):
// one line per use, from the node as GET /api/v2/nodes/{id} reads it and the other inputs of the form. The rules are
// the service's: collection_id and node_id in app/domain/requests.py, the wording of a topic in
// app/knowledge/topic_wording.py (D72), the levels of the pairs in app/api/v2/qa.py.

const WRITING = new Set(['best-quality-generated', 'best-coverage-generated']);
const FOREIGN = 'Aus einem anderen Repository: Teil 3 und Quelle lesen nur das Repository des Servers.';

const text = (value) => String(value ?? '').trim();
const joined = (values) => (values ?? []).join(', ');
// "die Stufe Sek I" or "die Stufen Sek I, Sek II"
const named = (one, many, values) => `${values.length > 1 ? many : one} ${joined(values)}`;

/** The line under the field: what the node is, with its subjects and levels. */
export function nodeLine(node) {
  const kind = node.kind === 'collection' ? 'Sammlung' : 'Material';
  return [`${kind} „${node.title}“`, joined(node.subjects), joined(node.educational_contexts)].filter(Boolean).join(' · ');
}

/** What the node does in a request of `mode` with the form's `values`, one line per use. `foreign`: it comes from
 * another repository than the server's, so it is an input only - part 3 and the source read the server's. */
export function nodeUses(mode, values, node, { foreign = false } = {}) {
  if (!node) return [];
  if (mode === 'entities') return [`Text: Titel, Beschreibung und Schlagwörter ${node.kind === 'collection' ? 'der Sammlung' : 'des Materials'}.`];
  const lines = [topicLine(mode, values, node), contextLine(values, node)];
  if (mode === 'compendium') lines.push(...(foreign ? [FOREIGN] : [partLine(values, node), sourceLine(values, node)]));
  if (mode === 'qa') lines.push(levelsLine(values, node));
  return lines.filter(Boolean);
}

// A topic sent along leads; without one a collection's title is the topic, a material's the article of its title and
// description - the rules' in llm-free, the model's where the profile lets the LLM choose articles (D47)
function topicLine(mode, values, node) {
  const topic = text(values.topic);
  if (topic) {
    const along = node.kind === 'material' ? '; das Material kommt als Quelle dazu, wenn sein Artikel mit dem Hauptartikel verlinkt ist' : '';
    return `Thema: „${topic}“ wie eingegeben${along}.`;
  }
  if (node.kind === 'collection') {
    const worded = mode === 'compendium' && WRITING.has(values.preset) ? '; die KI formuliert es zuerst aus Titel, Fächern, Schlagwörtern und Beschreibung' : '';
    return `Thema: „${node.title}“, der Titel der Sammlung${worded}.`;
  }
  if (values.preset !== 'llm-free') {
    return `Thema: der Artikel aus Titel und Beschreibung des Materials; die KI nennt ihn (die Regeln fänden ${node.topic ? `„${node.topic}“` : 'keinen'}).`;
  }
  return node.topic
    ? `Thema: der Artikel aus Titel und Beschreibung des Materials, nach den Regeln „${node.topic}“.`
    : 'Thema: Die Regeln finden in Titel und Beschreibung keinen Artikel – bitte ein Thema eingeben.';
}

// The node's levels become context words; its subjects count where the form names none
function contextLine(values, node) {
  const levels = node.educational_contexts ?? [];
  const subjects = text(values.subject) ? [] : node.subjects ?? [];
  const items = [levels.length && named('die Stufe', 'die Stufen', levels), subjects.length && named('das Fach', 'die Fächer', subjects)].filter(Boolean);
  if (!items.length) return null;
  const plural = items.length > 1 || levels.length > 1 || subjects.length > 1;
  const chosen = text(values.subject) && node.subjects?.length ? '; das Fach ist gewählt' : '';
  return `Dazu ${plural ? 'kommen' : 'kommt'} ${items.join(' und ')}${chosen}.`;
}

function partLine(values, node) {
  const asked = (values.parts ?? []).includes('collection');
  if (node.kind !== 'collection') return asked ? 'Teil 3 fällt weg: Es braucht eine Sammlung.' : null;
  return asked ? 'Teil 3 beschreibt die Sammlung.' : 'Teil 3 entsteht nur, wenn unter „Teile“ die Sammlung angehakt ist.';
}

function sourceLine(values, node) {
  if (node.kind !== 'collection' || !values.knowledge_source) return null;
  const depth = Number(text(values.knowledge_depth) || 0);
  const read = values.knowledge_fulltext ? 'mit ihren Volltexten' : 'ihre Beschreibungen';
  const deeper = depth > 0 ? `${values.knowledge_fulltext ? ' und' : ', mit'} den Untersammlungen bis Ebene ${depth}` : '';
  return `Quelle für Teil 1: die Materialien der Sammlung, ${read}${deeper}.`;
}

// Without levels of its own a request spreads the pairs the model writes over the node's (app/api/v2/qa.py)
function levelsLine(values, node) {
  const levels = node.educational_contexts ?? [];
  if (text(values.levels) || !levels.length) return null;
  return `Bildet die KI die Paare, verteilt sie sie auf ${named('die Stufe', 'die Stufen', levels)}.`;
}
