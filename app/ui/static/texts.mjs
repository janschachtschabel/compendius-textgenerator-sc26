// The words the page uses for the values of the service, in one place, so a value reads the same everywhere.
// A value without an entry shows as the service names it: a new switch or stage appears, just less friendly.

export const MODES = {
  compendium: 'Kompendium',
  knowledge: 'Wissenstexte',
  lehrplan: 'Lehrplan',
  entities: 'Entitäten',
  qa: 'Fragen & Antworten',
};

export const PROFILE_NAMES = {
  'llm-free': 'llm-free · ohne KI',
  balanced: 'balanced · ausgewogen',
  'best-quality': 'best-quality · beste Qualität',
  'best-quality-generated': 'best-quality-generated · von der KI formuliert',
  'best-coverage-generated': 'best-coverage-generated · von der KI vollständig zum Thema geschrieben',
};

// What a profile does at each endpoint, in the words of the decision paper (D53, D55, D57, D58, D62, D63)
export const PROFILE_ABOUT = {
  compendium: {
    'llm-free': 'Regeln wählen die Artikel und ordnen die Absätze zu; der Text bleibt wörtlich. Schnell, keine Tokens. ' +
      'Nur für Themen mit eigenem Artikel.',
    balanced: 'Die KI nennt die passenden Artikel eines Themas; der Text bleibt wörtlich. Schnell, wenige Tokens. ' +
      'Für Themen mit eigenem Artikel.',
    'best-quality': 'Die KI wählt die Artikel, ordnet jeden Absatz zu und prüft die Lehrplanelemente; der Text ' +
      'bleibt wörtlich. Langsamer, viele Tokens.',
    'best-quality-generated': 'Wie best-quality; dazu schreibt die KI jeden Baustein neu und darf eigenes Wissen ' +
      'ergänzen, höchstens für die Hälfte der Sätze, gekennzeichnet als [Modellwissen]. Gut lesbar; für Themen mit ' +
      'eigenem Artikel.',
    'best-coverage-generated': 'Wie best-quality-generated, aber die KI schreibt jeden Baustein genau zum angefragten ' +
      'Thema und füllt ihn vollständig: aus den Quellen, wo sie das Thema treffen, sonst aus eigenem Wissen ' +
      '([Modellwissen]). Für Sammelthemen („Dichter aus dem Mittelalter“) und Themen mit Aspekt („OER-Förderungen“): ' +
      'nur dieses Profil bleibt dort beim angefragten Thema. Die längsten Texte, die meisten Tokens.',
  },
  knowledge: {
    'llm-free': 'Regeln wählen die Artikel. Keine Tokens.',
    balanced: 'Die KI nennt Übersichtsartikel und Teile des Themas und entscheidet, wo die Regeln unsicher sind.',
    'best-quality': 'Wie balanced; die KI prüft auch sichere Entscheidungen bei mehrdeutigen Wörtern.',
    'best-quality-generated': 'Hier wie best-quality.',
    'best-coverage-generated': 'Hier wie best-quality.',
  },
  lehrplan: {
    'llm-free': 'Stichwortregeln finden und bewerten die Elemente. Keine Tokens.',
    balanced: 'Wie llm-free; beim Suchen nach einem Thema nennt die KI seine Teile.',
    'best-quality': 'Die KI bewertet jedes gefundene Element und lässt weg, was nicht passt.',
    'best-quality-generated': 'Hier wie best-quality.',
    'best-coverage-generated': 'Hier wie best-quality.',
  },
  entities: {
    'llm-free': 'Namenserkennung (spaCy) und das Wörterbuch der Artikeltitel. Keine Tokens.',
    balanced: 'Die KI nennt die Entitäten des Textes.',
    'best-quality': 'Die KI nennt die Entitäten des Textes.',
    'best-quality-generated': 'Die KI nennt die Entitäten des Textes.',
    'best-coverage-generated': 'Die KI nennt die Entitäten des Textes.',
  },
  qa: {
    'llm-free': 'Regeln bilden Fragen aus dem Satzbau. Keine Tokens.',
    balanced: 'Regeln bilden Fragen aus dem Satzbau. Keine Tokens.',
    'best-quality': 'Die KI schreibt die Paare und kann Bildungsstufen zuordnen.',
    'best-quality-generated': 'Die KI schreibt die Paare und kann Bildungsstufen zuordnen.',
    'best-coverage-generated': 'Die KI schreibt die Paare und kann Bildungsstufen zuordnen.',
  },
};

// The steps of a compendium a request can set apart from its profile, in the order they run
export const STEPS = {
  article_choice: {
    name: 'Artikelwahl',
    values: { 'rule-based': 'Regeln', llm: 'KI, wo die Regeln unsicher sind', 'llm-thorough': 'KI, auch bei mehrdeutigen Wörtern' },
  },
  matcher: {
    name: 'Zuordnung der Absätze',
    values: {
      hybrid_light: 'Regeln, kombiniert (hybrid_light)',
      bm25: 'Regeln, Stichwortgewicht (bm25)',
      char_tfidf: 'Regeln, Zeichenfolgen (char_tfidf)',
      lexicon_only: 'nur Überschriften-Lexikon',
      llm: 'KI ordnet jeden Absatz zu',
    },
  },
  extraction: { name: 'Auswahl der Sätze', values: { 'rule-based': 'Regeln', llm: 'KI wählt Sätze, Wortlaut bleibt' } },
  generation: {
    name: 'Formulierung',
    values: { 'rule-based': 'wörtlich aus den Quellen', 'llm-fast': 'KI formuliert die Hauptbausteine', llm: 'KI formuliert jeden Baustein' },
  },
  enrichment: {
    name: 'Eigenes Wissen der KI',
    values: {
      'sources-only': 'nein, nur Quellen',
      'model-knowledge': 'ja, gekennzeichnet',
      'model-knowledge-full': 'ja, füllt jeden Baustein zum angefragten Thema',
    },
  },
  curriculum_check: { name: 'Prüfung der Lehrplanelemente', values: { 'rule-based': 'Stichwortregeln', llm: 'KI bewertet jedes Element' } },
};

export const PARTS = { world: 'Teil 1 · Weltwissen', curricula: 'Teil 2 · Lehrplanbezüge', collection: 'Teil 3 · Sammlung' };

// A block of part 1 by its status in the markers of the document (app/domain/models.py, SectionStatus)
export const KINDS = {
  extract: { name: 'Wörtlich aus den Quellen', hint: 'Absätze der Artikel, unverändert übernommen' },
  selected: { name: 'Von der KI ausgewählt', hint: 'Wortlaut der Quellen; die KI hat Sätze oder Absätze gewählt' },
  written: { name: 'Von der KI formuliert', hint: 'Die KI hat den Baustein aus den belegten Stellen neu geschrieben' },
  assembled: { name: 'Automatisch zusammengestellt', hint: 'Aus den Artikeln gebaut: Akteure, Quellen, Glossar' },
  reviewed: { name: 'Redaktionell geprüft', hint: 'Aus einem früheren, geprüften Text übernommen' },
  empty: { name: 'Leer', hint: 'Die Quellen enthalten nichts dazu' },
  unknown: { name: 'Herkunft nicht angegeben', hint: '' },
};

export const PROJECTS = { wikipedia: 'Wikipedia', klexikon: 'Klexikon', wlo_material: 'Material der Sammlung' };

export const ORIGINS = {
  primary: 'Hauptartikel',
  same_topic: 'Gleiches Thema, anderes Lexikon',
  linked: 'Vom Hauptartikel verlinkt',
  search: 'Volltexttreffer',
  named: 'Von der KI genannt',
  node: 'Artikel des Materials',
  lookup: 'Nachgeschlagen',
};

export const RESOLUTION = {
  title: 'exakter Titel',
  variant: 'abgewandelte Form',
  disambiguation: 'Begriffsklärung',
  suggestion: 'Titelvorschlag',
  search: 'Volltextsuche',
  llm: 'von der KI entschieden',
};

export const STAGES = {
  resolve: 'Thema auflösen',
  extract: 'Sätze auswählen (KI)',
  corpus: 'Artikel laden',
  hit_check: 'Treffer prüfen',
  knowledge: 'Wissens-Sammlung lesen',
  segment: 'Absätze bilden',
  match: 'Absätze zuordnen',
  synthesize: 'Text bauen',
  curricula: 'Lehrpläne suchen',
  collection: 'Sammlung lesen',
  assemble: 'Zusammensetzen',
};

export const ENTITY_KINDS = { PER: 'Person', ORG: 'Organisation', LOC: 'Ort', MISC: 'Sonstiges' };
export const ENTITY_METHODS = { ner: 'Namenserkennung', dictionary: 'Wörterbuch', llm: 'KI' };
export const QA_METHODS = { 'rule-based': 'Regeln aus dem Satzbau', llm: 'KI' };
export const LEHRPLAN_MODES = { keyword: 'Stichwort, wie eingegeben', topic: 'Thema, wie Teil 2 eines Kompendiums' };
export const PART_STATUS = { ok: 'vollständig', empty: 'nichts gefunden', incomplete: 'unvollständig', unavailable: 'nicht verfügbar' };
export const LINK_CHECKS = { 'rule-based': 'Regeln', llm: 'KI prüft jede Verknüpfung' };
export const MATCHED_IN = { label: 'Element nennt das Thema', parent: 'nur die Überschrift nennt das Thema' };
// The notes of the LLM check of part 2 (app/knowledge/curriculum_check.py, D58); a 0 leaves the list
export const RATINGS = { 2: 'passt zum Thema', 1: 'streift das Thema', 0: 'passt nicht' };

export const ERRORS = {
  0: 'Keine Verbindung zum Server.',
  key: 'Der API-Schlüssel enthält ein Zeichen, das sich nicht senden lässt – etwa ein Leerzeichen oder ein unsichtbares Zeichen aus dem Kopieren. Bitte links unten neu eintragen.',
  401: 'Der Server verlangt einen API-Schlüssel. Bitte links unten eintragen.',
  404: 'Nicht gefunden.',
  413: 'Die Anfrage ist zu groß.',
  422: 'Die Eingaben passen nicht.',
  429: 'Zu viele Anfragen in kurzer Zeit. Bitte kurz warten und noch einmal versuchen.',
  500: 'Interner Fehler des Servers. Bitte die Anfrage-ID melden.',
  502: 'Das Repository antwortet nicht.',
  503: 'Dafür fehlt dem Server etwas.',
  504: 'Der Server hat zu lange gebraucht.',
};

export function label(table, value) {
  return (table && Object.hasOwn(table, value) ? table[value] : null) ?? String(value ?? '');
}
