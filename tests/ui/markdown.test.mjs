// The markdown of the service as the review page reads it: a tree of plain values, never markup (D66).
import { test } from 'node:test';
import assert from 'node:assert/strict';

import { inlineText, parseInline, parseMarkdown, sectionize } from '../../app/ui/static/markdown.mjs';

const text = (value) => ({ type: 'text', value });

test('the frontmatter is set apart and the body starts after it', () => {
  const { frontmatter, blocks } = parseMarkdown('---\ntopic: Optik\nparts:\n- world\n---\n\n# Kompendium: Optik\n');

  assert.equal(frontmatter, 'topic: Optik\nparts:\n- world');
  assert.deepEqual(blocks, [{ type: 'heading', level: 1, children: [text('Kompendium: Optik')] }]);
});

test('without a frontmatter the whole text is the body', () => {
  const { frontmatter, blocks } = parseMarkdown('Nur ein Satz.');

  assert.equal(frontmatter, null);
  assert.deepEqual(blocks, [{ type: 'paragraph', children: [text('Nur ein Satz.')] }]);
});

test('paragraphs end at a blank line and join their lines with a space', () => {
  const { blocks } = parseMarkdown('Erste Zeile\nzweite Zeile.\n\nNeuer Absatz.');

  assert.deepEqual(blocks, [
    { type: 'paragraph', children: [text('Erste Zeile zweite Zeile.')] },
    { type: 'paragraph', children: [text('Neuer Absatz.')] },
  ]);
});

test('an evidence number becomes a citation, a link to a web address a link', () => {
  const nodes = parseInline('Licht breitet sich geradlinig aus. [3] Mehr bei [Optik](https://de.wikipedia.org/wiki/Optik).');

  assert.deepEqual(nodes, [
    text('Licht breitet sich geradlinig aus. '),
    { type: 'cite', number: 3 },
    text(' Mehr bei '),
    { type: 'link', href: 'https://de.wikipedia.org/wiki/Optik', children: [text('Optik')] },
    text('.'),
  ]);
});

test('a link target in angle brackets keeps its parentheses', () => {
  const [link] = parseInline('[Linse](<https://de.wikipedia.org/wiki/Linse_(Optik)>)');

  assert.equal(link.href, 'https://de.wikipedia.org/wiki/Linse_(Optik)');
});

test('a balanced pair of parentheses stays in a plain link target', () => {
  const [link] = parseInline('[Optik](https://de.wikipedia.org/wiki/Optik_(Begriffskl%C3%A4rung))');

  assert.equal(link.href, 'https://de.wikipedia.org/wiki/Optik_(Begriffskl%C3%A4rung)');
});

test('a link to anything but a web address keeps only its words', () => {
  for (const target of ['javascript:alert(1)', 'data:text/html,x', '//evil.example/x', 'JaVaScRiPt:alert(1)']) {
    assert.deepEqual(parseInline(`[klick](${target})`), [text('klick')], target);
  }
});

test('markup in the text stays text: no tag, no comment of another kind', () => {
  assert.deepEqual(parseInline('<script>alert(1)</script> und <img src=x onerror=alert(1)>'), [
    text('<script>alert(1)</script> und <img src=x onerror=alert(1)>'),
  ]);
  assert.deepEqual(parseInline('vorher <!-- verborgen --> nachher'), [text('vorher  nachher')]);
});

test('escapes show the sign they stand for', () => {
  assert.deepEqual(parseInline('\\[τέχνη\\] \\- 1905\\. \\*nicht kursiv\\*'), [text('[τέχνη] - 1905. *nicht kursiv*')]);
});

test('strong, emphasis and code spans', () => {
  assert.deepEqual(parseInline('**fett**, *kursiv* und `wikipedia_de.zim`'), [
    { type: 'strong', children: [text('fett')] },
    text(', '),
    { type: 'em', children: [text('kursiv')] },
    text(' und '),
    { type: 'code', value: 'wikipedia_de.zim' },
  ]);
});

test('a lone asterisk between words is no emphasis', () => {
  assert.deepEqual(parseInline('5 * 3 * 2 = 30'), [text('5 * 3 * 2 = 30')]);
});

test('a link may carry strong or emphasised words', () => {
  assert.deepEqual(parseInline('[**Optik**](https://example.org/optik)'), [
    { type: 'link', href: 'https://example.org/optik', children: [{ type: 'strong', children: [text('Optik')] }] },
  ]);
});

test('a sentence of model knowledge is marked, with its label', () => {
  const nodes = parseInline('Belegt. [1] <!-- f: Evidenzgrad=Modellwissen -->Ergänzt. [Modellwissen]<!-- /f --> Weiter. [2]');

  assert.deepEqual(nodes, [
    text('Belegt. '),
    { type: 'cite', number: 1 },
    text(' '),
    { type: 'mark', grade: 'Modellwissen', children: [text('Ergänzt. '), { type: 'label', value: 'Modellwissen' }] },
    text(' Weiter. '),
    { type: 'cite', number: 2 },
  ]);
});

test('a paragraph of nothing but a marked sentence stays a paragraph', () => {
  const { blocks } = parseMarkdown('<!-- f: Evidenzgrad=Modellwissen -->Nur ergänzt. [Modellwissen]<!-- /f -->');

  assert.deepEqual(blocks, [
    {
      type: 'paragraph',
      children: [{ type: 'mark', grade: 'Modellwissen', children: [text('Nur ergänzt. '), { type: 'label', value: 'Modellwissen' }] }],
    },
  ]);
});

test('a marker that never closes marks nothing', () => {
  assert.deepEqual(parseInline('<!-- f: Evidenzgrad=Modellwissen -->Satz.'), [text('Satz.')]);
});

test('headings, lists with nesting and continuation lines', () => {
  const { blocks } = parseMarkdown('#### Person\n\n- **A** — erster\n  - Unterpunkt\n  weiter\n- B\n\n1. eins\n2. zwei');

  assert.deepEqual(blocks, [
    { type: 'heading', level: 4, children: [text('Person')] },
    {
      type: 'list',
      ordered: false,
      items: [
        {
          children: [{ type: 'strong', children: [text('A')] }, text(' — erster')],
          lists: [{ type: 'list', ordered: false, items: [{ children: [text('Unterpunkt weiter')], lists: [] }] }],
        },
        { children: [text('B')], lists: [] },
      ],
    },
    {
      type: 'list',
      ordered: true,
      items: [
        { children: [text('eins')], lists: [] },
        { children: [text('zwei')], lists: [] },
      ],
    },
  ]);
});

test('a table with its alignment, escaped pipes and a citation cell', () => {
  const { blocks } = parseMarkdown(
    '| Beleg | Quelle | Auszug |\n| :---: | :--- | ---: |\n| [1] | [Optik](https://example.org/o) | a \\| b |\n| [2] | X |',
  );

  assert.deepEqual(blocks, [
    {
      type: 'table',
      align: ['center', 'left', 'right'],
      head: [[text('Beleg')], [text('Quelle')], [text('Auszug')]],
      rows: [
        [[{ type: 'cite', number: 1 }], [{ type: 'link', href: 'https://example.org/o', children: [text('Optik')] }], [text('a | b')]],
        [[{ type: 'cite', number: 2 }], [text('X')], []],
      ],
    },
  ]);
});

test('a comment on a line of its own is a marker, not text, and ends a paragraph', () => {
  const { blocks } = parseMarkdown('Zeile\n<!-- f: Bundesland=Bayern -->\n\nText\n<!-- /f -->');

  assert.deepEqual(blocks, [
    { type: 'paragraph', children: [text('Zeile')] },
    { type: 'comment', text: 'f: Bundesland=Bayern' },
    { type: 'paragraph', children: [text('Text')] },
    { type: 'comment', text: '/f' },
  ]);
});

test('the marker of a block carries its id, status and facets', () => {
  const { blocks } = parseMarkdown(
    '<!-- kompendium:section id=sc26_1 status=maschinell-extraktiv facets="Bildungsstufe=Primar|Sek I" hash=60544fd6be69 -->',
  );

  assert.deepEqual(blocks, [
    {
      type: 'section',
      attrs: { id: 'sc26_1', status: 'maschinell-extraktiv', facets: 'Bildungsstufe=Primar|Sek I', hash: '60544fd6be69' },
    },
  ]);
});

test('a block runs from the heading before its marker to the next block or part', () => {
  const { blocks } = parseMarkdown([
    '## Teil 1 · Weltwissen',
    '### 1 · Themendefinition',
    '<!-- kompendium:section id=sc26_1 status=maschinell-extraktiv -->',
    'Satz. [1]',
    '### 12 · Quellen',
    '<!-- kompendium:section id=sc26_12 status=maschinell-generiert -->',
    'Liste',
    '### Belegstellen',
    'Tabelle',
    '## Teil 2 · Lehrplanbezüge',
    'Element',
  ].join('\n'));

  const parts = sectionize(blocks);

  assert.equal(parts.length, 5);
  assert.equal(parts[0].type, 'heading');
  assert.equal(parts[1].type, 'section');
  assert.equal(parts[1].attrs.id, 'sc26_1');
  assert.equal(inlineText(parts[1].heading.children), '1 · Themendefinition');
  assert.equal(parts[1].blocks.length, 1);
  assert.equal(parts[2].attrs.id, 'sc26_12');
  assert.deepEqual(parts[2].blocks.map((b) => b.type), ['paragraph', 'heading', 'paragraph']);
  assert.equal(parts[3].type, 'heading');
  assert.equal(parts[4].type, 'paragraph');
});

test('inlineText reads the words of a tree, citations as their numbers', () => {
  assert.equal(inlineText(parseInline('**A** und [B](https://b.example) [4]')), 'A und B [4]');
});

test('windows line ends read as plain ones', () => {
  assert.deepEqual(parseMarkdown('# T\r\n\r\nSatz.').blocks.length, 2);
});
