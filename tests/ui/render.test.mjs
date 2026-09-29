// The markdown of an answer as elements of the page, under the stand-in document (D66): whatever the text holds,
// it becomes text - no tag of it an element, no link of it more than a web address -, headings go one level down,
// and a number of the evidence opens its box.
import { test } from 'node:test';
import assert from 'node:assert/strict';

import { installDocument } from './dom_stub.mjs';
import { parseMarkdown } from '../../app/ui/static/markdown.mjs';
import { renderBlocks, renderContext } from '../../app/ui/static/render.mjs';
import { renderCompendium } from '../../app/ui/static/view_compendium.mjs';

const OPTIK = 'https://de.wikipedia.org/wiki/Optik';
const EVIDENCE = { number: 1, source_id: 'wikipedia:Optik', source_title: 'Optik', source_url: OPTIK, section_heading: 'Einleitung', snippet: 'Die Optik ist die Lehre vom Licht.' };

function rendered(markdown, ctx = renderContext('t')) {
  const host = document.createElement('div');
  host.append(renderBlocks(parseMarkdown(markdown).blocks, ctx));
  return host;
}

test('whatever the text of an answer holds becomes text, and a link only leads to a web address', () => {
  installDocument();
  const hostile = [
    '# Titel <img src=x onerror=alert(1)>',
    '',
    'Satz mit <script>alert(1)</script>, [klick](javascript:alert(1)) und [Optik](https://de.wikipedia.org/wiki/Optik).',
    '',
    '| Spalte | <b>fett</b> |',
    '| --- | --- |',
    '| <iframe src=x> | [2] |',
  ].join('\n');

  const host = rendered(hostile);

  const tags = new Set(host.descendants().map((node) => node.tagName));
  assert.deepEqual([...tags].filter((tag) => !['H2', 'P', 'A', 'SPAN', 'DIV', 'TABLE', 'THEAD', 'TBODY', 'TR', 'TH', 'TD'].includes(tag)), []);
  assert.deepEqual(host.descendants().filter((node) => node.tagName === 'A').map((node) => node.getAttribute('href')), [OPTIK]);
  assert.match(host.textContent, /<script>alert\(1\)<\/script>/);
  assert.match(host.textContent, /<iframe src=x>/);
});

test('headings go one level down, so the page keeps its h1, and the contents collect them', () => {
  installDocument();
  const ctx = renderContext('t');

  const host = rendered('# Kompendium\n\n###### Ganz unten', ctx);

  assert.deepEqual(host.children.map((node) => [node.tagName, node.textContent]), [['H2', 'Kompendium'], ['H6', 'Ganz unten']]);
  assert.deepEqual(ctx.headings, [{ level: 1, id: 't-h0', text: 'Kompendium' }, { level: 6, id: 't-h1', text: 'Ganz unten' }]);
});

test('a number with its evidence opens one box however often it occurs; one without stays a number in brackets', () => {
  installDocument();
  const ctx = renderContext('t', { citations: new Map([[1, EVIDENCE]]) });

  const host = rendered('Die Optik ist die Lehre vom Licht. [1] Sie ist alt. [1] Mehr steht nirgends. [2]', ctx);

  const buttons = host.descendants().filter((node) => node.tagName === 'BUTTON');
  assert.deepEqual(buttons.map((node) => node.getAttribute('popovertarget')), ['t-beleg-1', 't-beleg-1']);
  assert.equal(ctx.popoverHost.children.length, 1);
  assert.match(ctx.popoverHost.textContent, /Die Optik ist die Lehre vom Licht\./);
  assert.equal(host.descendants().filter((node) => node.classList.contains('cite-ref')).at(-1).textContent, '[2]');
});

test('a block whose status is named like a property of every object shows as one of unknown origin', () => {
  for (const status of ['constructor', 'toString', '__proto__']) {
    installDocument();
    const answer = { markdown: `### 1 · X\n<!-- kompendium:section id=s1 status=${status} -->\nSatz.`, sections: [], sources: [] };

    const { body } = renderCompendium(answer, 'k');

    const [block] = body.descendants().filter((node) => node.tagName === 'SECTION');
    assert.ok(block.classList.contains('kind-unknown'), status);
    assert.match(block.textContent, /Herkunft nicht angegeben/, status);
  }
});

test('a compendium shows each block with how it came about and each paragraph with where it comes from', () => {
  installDocument();
  const answer = {
    markdown: [
      '## Teil 1 · Weltwissen',
      '### 1 · Themendefinition',
      '<!-- kompendium:section id=sc26_1 status=maschinell-extraktiv -->',
      'Die Optik ist die Lehre vom Licht. [1]',
      '',
      '<!-- f: Evidenzgrad=Modellwissen -->Licht ist schnell. [Modellwissen]<!-- /f -->',
    ].join('\n'),
    sections: [{ slot_id: 'sc26_1', status: 'maschinell-extraktiv', citations: [EVIDENCE] }],
    sources: [{ source_id: 'wikipedia:Optik', project: 'wikipedia', title: 'Optik', url: OPTIK }],
  };

  const { body, headings } = renderCompendium(answer, 'k');

  const [block] = body.descendants().filter((node) => node.tagName === 'SECTION');
  assert.equal(block.getAttribute('data-block'), 'sc26_1');
  assert.ok(block.classList.contains('kind-extract'));
  assert.equal(block.descendants().filter((node) => node.classList.contains('origin')).length, 2, 'both paragraphs say where they come from');
  assert.equal(block.descendants().filter((node) => node.classList.contains('mark-modellwissen')).length, 1);
  assert.deepEqual(headings.map((heading) => heading.text), ['Teil 1 · Weltwissen', '1 · Themendefinition']);
});
