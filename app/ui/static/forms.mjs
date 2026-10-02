// The forms of the review page as data (D66): their fields, their starting values, the requests they make and what
// they refuse before sending. The endpoints check everything again; the checks here only say it in plain words and
// before a request costs anything. fields.mjs turns the fields into controls.

import { label, LEHRPLAN_MODES, LINK_CHECKS, QA_METHODS } from './texts.mjs';

const NODE_ID = /[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}/;
export const COMPENDIUM_STEPS = ['article_choice', 'matcher', 'extraction', 'generation', 'enrichment', 'model_knowledge_check', 'curriculum_check'];

// One field for a collection or a material (D77; Jan, 2026-10-02: "vielleicht reicht ein feld für die nodeid der
// sammlung"): the page reads the node (GET /api/v2/nodes/{id}) and says under the field what it is and does
const NODE = { name: 'node', type: 'node', label: 'Sammlung oder Material', optional: true, help: 'ID oder Link aus dem Repository, etwa 9e7ae956-e9df-430f-bace-f3db4b910013.' };
const REPOSITORY = { name: 'repository', type: 'text', label: 'Repository der Sammlung oder des Materials', advanced: true, placeholder: 'leer: das des Servers' };

// The host of a repository address, or the address as typed where it is none
function hostOf(value) {
  try {
    return new URL(text(value)).hostname;
  } catch {
    return text(value).toLowerCase();
  }
}

// A node named with another repository than the server's (options.repository) is an input only: part 3 and the source
// read the server's repository, so a collection there goes as node_id (app/compendium/repository.py)
export const fromAnotherRepository = (v, options) => Boolean(text(v.repository)) && hostOf(v.repository) !== options?.repository;
/** A collection of the server's repository, as reading it showed: part 3 and the source can use it. */
export const asCollection = (v, options) => v.node_kind === 'collection' && !fromAnotherRepository(v, options);
const asSource = (v, options) => asCollection(v, options) && Boolean(v.knowledge_source);
const SUBJECT = { name: 'subject', type: 'subject', label: 'Fach', optional: true, help: 'Entscheidet mehrdeutige Wörter und grenzt die Lehrpläne ein.' };
const PRESET = { name: 'preset', type: 'preset', label: 'Profil' };

export const FORMS = {
  compendium: {
    submit: 'Kompendium erzeugen',
    fields: [
      { name: 'topic', type: 'text', label: 'Thema', placeholder: 'z. B. Optik' },
      NODE,
      { name: 'knowledge_source', type: 'check', label: 'Ihre Materialien als Quelle für Teil 1', when: asCollection },
      { name: 'knowledge_fulltext', type: 'check', label: 'Volltexte der Materialien lesen, nicht nur ihre Beschreibungen', when: asSource },
      { name: 'knowledge_depth', type: 'number', label: 'Untersammlungen mitlesen (Ebenen)', when: asSource, help: '0: nur die Sammlung selbst.' },
      SUBJECT,
      { name: 'parts', type: 'parts', label: 'Teile' },
      PRESET,
      { name: 'facets_visible', type: 'check', label: 'Facetten im Text zeigen', option: true },
      { name: 'empty_note', type: 'check', label: 'Leere Bausteine mit Hinweis zeigen', option: true },
      { name: 'model_knowledge_label', type: 'check', label: 'Vermerk [Modellwissen] im Text zeigen', option: true },
      REPOSITORY,
      { name: 'steps', type: 'steps', label: 'Methode je Schritt', advanced: true, steps: COMPENDIUM_STEPS },
      { name: 'target_length', type: 'number', label: 'Ziellänge in Zeichen', advanced: true, help: 'Eine Richtgröße: Wörtliche Texte werden so lang, wie die Quellen tragen; in best-coverage-generated ist sie eine Untergrenze.' },
      { name: 'max_articles', type: 'number', label: 'Höchstens Artikel', advanced: true },
      { name: 'template_id', type: 'template', label: 'Vorlage', advanced: true },
    ],
  },
  knowledge: {
    submit: 'Wissenstexte holen',
    fields: [
      { name: 'topic', type: 'text', label: 'Thema', placeholder: 'z. B. Optik' },
      NODE,
      SUBJECT,
      PRESET,
      REPOSITORY,
      { name: 'steps', type: 'steps', label: 'Methode', advanced: true, steps: ['article_choice'] },
      { name: 'max_articles', type: 'number', label: 'Höchstens Artikel', advanced: true },
      { name: 'max_chars', type: 'number', label: 'Höchstens Zeichen', advanced: true },
    ],
  },
  lehrplan: {
    submit: 'Lehrpläne durchsuchen',
    fields: [
      { name: 'q', type: 'text', label: 'Stichwort oder Thema', placeholder: 'z. B. Optik' },
      { ...SUBJECT, help: 'Grenzt die Suche auf die Lehrpläne eines Fachs ein.' },
      { name: 'mode', type: 'select', label: 'Suche nach', choices: (options) => labelled(options.lehrplan?.modes, LEHRPLAN_MODES) },
      PRESET,
      { name: 'steps', type: 'steps', label: 'Methode', advanced: true, steps: ['curriculum_check'] },
      { name: 'limit', type: 'number', label: 'Höchstens Elemente', advanced: true },
    ],
  },
  entities: {
    submit: 'Entitäten erkennen',
    fields: [
      { name: 'text', type: 'textarea', label: 'Text', placeholder: 'Ein Satz oder Absatz mit Namen, Orten, Begriffen' },
      { ...NODE, label: 'Oder eine Sammlung oder ein Material' },
      PRESET,
      { name: 'link', type: 'check', label: 'Artikel in den Archiven nachschlagen', option: true },
      REPOSITORY,
      { name: 'methods', type: 'methods', label: 'Wege der Erkennung', advanced: true },
      { name: 'link_check', type: 'select', label: 'Prüfung der Artikel', advanced: true, profile: true, choices: (options) => labelled(options.entities?.link_checks, LINK_CHECKS) },
      { name: 'max_entities', type: 'number', label: 'Höchstens Entitäten', advanced: true },
    ],
  },
  qa: {
    submit: 'Fragen und Antworten bilden',
    fields: [
      { name: 'topic', type: 'text', label: 'Thema', placeholder: 'z. B. Optik' },
      NODE,
      { name: 'text', type: 'textarea', label: 'Oder ein eigener Text', optional: true },
      SUBJECT,
      PRESET,
      { name: 'count', type: 'number', label: 'Anzahl der Paare' },
      REPOSITORY,
      { name: 'method', type: 'select', label: 'Methode', advanced: true, profile: true, choices: (options) => labelled(options.qa?.methods, QA_METHODS) },
      { name: 'levels', type: 'text', label: 'Bildungsstufen', advanced: true, placeholder: 'z. B. Sek I, Sek II', help: 'Durch Kommas getrennt; nur die KI ordnet Stufen zu.' },
      { name: 'max_answer_length', type: 'number', label: 'Höchstens Zeichen je Antwort', advanced: true },
    ],
  },
};

// The values the server offers (options.json), each in the page's words, or under its own name where it has none
function labelled(values, words) {
  return Object.fromEntries((values ?? []).map((value) => [value, label(words, value)]));
}

/** The bounds of a field as the endpoint declares them (options.limits): of a number, of the length of a text. */
export function bounds(mode, name, options) {
  return options.limits?.[mode]?.[name] ?? {};
}

/** The id in a value - a link that holds one works too - or the value as typed when it holds none. */
export function nodeIdOf(value) {
  const text = String(value ?? '').trim();
  return NODE_ID.exec(text)?.[0] ?? text;
}

/** The whole id in a value - typed or in a link -, or '' while it holds none, as when typing it has not ended. */
export function wholeNodeId(value) {
  const found = nodeIdOf(value);
  return NODE_ID.test(found) ? found : '';
}

/** The values a form starts with. Without an LLM on the server only llm-free answers, so it starts there. */
export function defaults(mode, options) {
  const ids = (options.presets ?? []).map((preset) => preset.id);
  const preset = options.llm_configured ? options.preset_default : 'llm-free';
  const common = { preset, compare: false, preset_b: ids.find((id) => id !== preset) ?? preset, subject: '', node: '', node_kind: '', repository: '' };
  switch (mode) {
    case 'compendium':
      return {
        ...common,
        topic: '',
        knowledge_source: false,
        knowledge_depth: '',
        knowledge_fulltext: false,
        parts: ['world', 'curricula'],
        facets_visible: Boolean(options.facets_visible), // FACETS_VISIBLE of the server, as a request without it
        empty_note: Boolean(options.empty_note), // as the default template keeps empty blocks, as a request without it
        model_knowledge_label: false, // the default of the API since D76
        ...Object.fromEntries(COMPENDIUM_STEPS.map((step) => [step, ''])),
        target_length: '',
        max_articles: '',
        template_id: '',
      };
    case 'knowledge':
      return { ...common, topic: '', article_choice: '', max_articles: '', max_chars: '' };
    case 'lehrplan':
      return { ...common, q: '', mode: 'keyword', curriculum_check: '', limit: '' };
    case 'entities':
      return { ...common, text: '', link: true, methods: [], link_check: '', max_entities: '' };
    case 'qa':
      return { ...common, topic: '', text: '', count: '', method: '', levels: '', max_answer_length: '' };
    default:
      throw new Error(`unknown mode ${mode}`);
  }
}

// What an example asks about. Loading one changes only the fields it holds, not profile, comparison, steps, subject
// or numbers (Jan, 2026-09-29, U11) - with one exception: the input of its mode goes together. A topic left from an
// earlier example would win over the node of a material, and /qa refuses a text next to a topic, so an example sets
// all of its input, empty where it has none. The source of a collection, its depth and full texts go with it: left
// over from an earlier one, they would hold back an example without that collection.
const EXAMPLE_INPUT = {
  compendium: ['topic', 'node', 'node_kind', 'knowledge_source', 'knowledge_depth', 'knowledge_fulltext', 'repository'],
  knowledge: ['topic', 'node', 'node_kind', 'repository'],
  lehrplan: ['q'],
  entities: ['text', 'node', 'node_kind', 'repository'],
  qa: ['topic', 'text', 'node', 'node_kind', 'repository'],
};

/** The fields an example sets: its values, numbers as a number field holds them, and the rest of its input empty.
 * The examples speak the API (app/ui/options.py); its three ids go into the one field of the page (D77): a collection
 * as it is, its materials as a source with the box, a material or another node to be read. */
export function fromExample(mode, example) {
  const values = Object.fromEntries((EXAMPLE_INPUT[mode] ?? []).map((name) => [name, '']));
  const { collection_id: collection, knowledge_collection_id: source, node_id: node, ...rest } = example.values;
  for (const [name, value] of Object.entries(rest)) values[name] = typeof value === 'number' ? String(value) : value;
  if (collection || source) Object.assign(values, { node: collection || source, node_kind: 'collection', knowledge_source: Boolean(source) });
  else if (node) values.node = node;
  return values;
}

/** The requests a form makes: one, or one per profile when it compares two. A comparison leaves every step to the
 * profiles, so the two answers differ by their profile and nothing else. */
export function buildRequests(mode, values, options) {
  const presets = values.compare ? [values.preset, values.preset_b] : [values.preset];
  return presets.map((preset) => ({ preset, request: BUILDERS[mode]({ ...values, preset }, !values.compare, options) }));
}

/** What keeps the form from being sent, by field, in plain words; empty when nothing does. */
export function problems(mode, values, options) {
  const found = {};
  CHECKS[mode](values, found, options);
  for (const field of FORMS[mode].fields) {
    if (field.when && !field.when(values, options)) continue; // hidden, and not sent either
    if (['id', 'node'].includes(field.type) && text(values[field.name]) && !NODE_ID.test(nodeIdOf(values[field.name]))) {
      found[field.name] = 'Das ist keine ID. Eine ID sieht so aus: 9e7ae956-e9df-430f-bace-f3db4b910013 – ein Link, der sie enthält, geht auch.';
    }
    if (field.type === 'number') numberProblem(values[field.name], bounds(mode, field.name, options), field.name, found);
    if (field.type === 'text') lengthProblem(values[field.name], bounds(mode, field.name, options), field.name, found);
  }
  if (text(values.repository) && !text(values.node)) found.repository = 'Ein Repository gilt nur für eine Sammlung oder ein Material.';
  if (values.compare && values.preset_b === values.preset) found.preset_b = 'Bitte ein anderes Profil als das erste wählen.';
  return found;
}

const BUILDERS = {
  compendium(v, withSteps, options) {
    const body = {};
    put(body, 'topic', text(v.topic));
    put(body, 'subject', text(v.subject));
    collectionOrNode(body, v, options);
    body.parts = [...v.parts];
    body.preset = v.preset;
    if (withSteps) for (const step of COMPENDIUM_STEPS) put(body, step, v[step]);
    put(body, 'target_length', number(v.target_length));
    put(body, 'max_articles', number(v.max_articles));
    put(body, 'template_id', text(v.template_id));
    body.facets_visible = Boolean(v.facets_visible);
    // Either way: a template keeps empty blocks or leaves them out by its own policy, which the box would not show
    body.empty_slot_policy = v.empty_note ? 'note' : 'omit';
    if (v.model_knowledge_label) body.model_knowledge_label = true;
    return { method: 'POST', path: 'api/v2/compendium', body };
  },
  knowledge(v, withSteps) {
    const body = {};
    put(body, 'topic', text(v.topic));
    put(body, 'subject', text(v.subject));
    node(body, v);
    body.preset = v.preset;
    if (withSteps) put(body, 'article_choice', v.article_choice);
    put(body, 'max_articles', number(v.max_articles));
    put(body, 'max_chars', number(v.max_chars));
    return { method: 'POST', path: 'api/v2/knowledge', body };
  },
  lehrplan(v, withSteps) {
    const query = { q: text(v.q) };
    put(query, 'subject', text(v.subject));
    query.mode = v.mode;
    put(query, 'limit', number(v.limit));
    query.preset = v.preset;
    if (withSteps) put(query, 'curriculum_check', v.curriculum_check);
    return { method: 'GET', path: 'api/v2/lehrplan/search', query };
  },
  entities(v, withSteps) {
    const body = {};
    put(body, 'text', v.text?.trim() ? v.text : '');
    node(body, v);
    body.preset = v.preset;
    body.link = Boolean(v.link);
    if (withSteps && v.methods?.length) body.methods = [...v.methods];
    if (withSteps) put(body, 'link_check', v.link_check);
    put(body, 'max_entities', number(v.max_entities));
    return { method: 'POST', path: 'api/v2/entities', body };
  },
  qa(v, withSteps) {
    const body = {};
    put(body, 'text', v.text?.trim() ? v.text : '');
    put(body, 'topic', text(v.topic));
    node(body, v);
    put(body, 'subject', text(v.subject));
    body.preset = v.preset;
    if (withSteps) put(body, 'method', v.method);
    put(body, 'count', number(v.count));
    const levels = String(v.levels ?? '').split(',').map((level) => level.trim()).filter(Boolean);
    if (levels.length) body.levels = levels;
    put(body, 'max_answer_length', number(v.max_answer_length));
    return { method: 'POST', path: 'api/v2/qa', body };
  },
};

const CHECKS = {
  compendium(v, found, options) {
    if (!text(v.topic) && !text(v.node)) found.topic = 'Bitte ein Thema eingeben oder eine Sammlung bzw. ein Material.';
    if (!v.parts?.length) found.parts = 'Bitte mindestens einen Teil wählen.';
    else if (v.parts.length === 1 && v.parts[0] === 'collection') {
      if (!text(v.node)) found.node = 'Teil 3 braucht eine Sammlung.';
      else if (v.node_kind === 'material') found.node = 'Teil 3 braucht eine Sammlung; das ist ein Material.';
    }
    if (asSource(v, options) && !v.parts?.includes('world')) found.knowledge_source = 'Die Materialien als Quelle speisen Teil 1 – bitte Teil 1 wählen.';
  },
  knowledge(v, found) {
    if (!text(v.topic) && !text(v.node)) found.topic = 'Bitte ein Thema eingeben oder eine Sammlung bzw. ein Material.';
  },
  lehrplan(v, found) {
    if (!text(v.q)) found.q = 'Bitte ein Stichwort oder Thema eingeben.';
  },
  entities(v, found) {
    const hasText = Boolean(v.text?.trim());
    if (hasText && text(v.node)) found.text = 'Entweder ein Text oder eine Sammlung bzw. ein Material – nicht beides.';
    else if (!hasText && !text(v.node)) found.text = 'Bitte einen Text eingeben oder eine Sammlung bzw. ein Material.';
    // A comparison leaves the check to the profiles and sends none, whatever the locked field still holds
    if (!v.compare && v.link_check === 'llm' && !v.link) found.link_check = 'Die Prüfung durch die KI braucht das Nachschlagen der Artikel.';
  },
  qa(v, found) {
    const hasText = Boolean(v.text?.trim());
    const hasTopic = Boolean(text(v.topic) || text(v.node));
    if (hasText && hasTopic) found.text = 'Entweder ein eigener Text oder ein Thema bzw. eine Sammlung oder ein Material – nicht beides.';
    else if (!hasText && !hasTopic) found.topic = 'Bitte ein Thema oder einen eigenen Text eingeben.';
    if (hasText && text(v.subject)) found.subject = 'Das Fach gilt nur für ein Thema; ein eigener Text wird so abgefragt, wie er ist.';
  },
};

// A text the endpoint would refuse for its length; an empty one the checks of the form speak of
function lengthProblem(value, { min_length: min, max_length: max }, name, found) {
  const length = text(value).length;
  if (max !== undefined && length > max) found[name] = `Bitte kürzen: höchstens ${formatWhole(max)} Zeichen, eingegeben sind ${formatWhole(length)}.`;
  else if (length && min !== undefined && length < min) found[name] = `Bitte mindestens ${formatWhole(min)} Zeichen eingeben.`;
}

function numberProblem(value, { min, max }, name, found) {
  const typed = text(value);
  if (!typed) return;
  const number = Number(typed);
  if (Number.isInteger(number) && (min === undefined || number >= min) && (max === undefined || number <= max)) return;
  const range = max === undefined ? `ab ${formatWhole(min)}` : `von ${formatWhole(min)} bis ${formatWhole(max)}`;
  found[name] = `Bitte eine ganze Zahl ${range} eingeben.`;
}

function formatWhole(n) {
  return new Intl.NumberFormat('de-DE').format(n);
}

function node(body, v) {
  const nodeId = id(v.node);
  put(body, 'node_id', nodeId);
  if (nodeId) put(body, 'repository', text(v.repository));
}

// A collection read as one of the server's repository is collection_id, its materials as a source knowledge_collection_id;
// anything else goes as node_id, where the service takes a collection of its repository for part 3 all the same (D77)
function collectionOrNode(body, v, options) {
  if (!asCollection(v, options) || !id(v.node)) {
    node(body, v);
    return;
  }
  body.collection_id = id(v.node);
  if (!asSource(v, options)) return;
  body.knowledge_collection_id = body.collection_id;
  put(body, 'knowledge_depth', number(v.knowledge_depth));
  if (v.knowledge_fulltext) body.knowledge_fulltext = true;
}

function put(target, name, value) {
  if (value !== '' && value !== null && value !== undefined) target[name] = value;
}

function text(value) {
  return String(value ?? '').trim();
}

function id(value) {
  return text(value) ? nodeIdOf(value) : '';
}

function number(value) {
  return text(value) ? Number(text(value)) : '';
}
