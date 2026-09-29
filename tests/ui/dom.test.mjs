// The builders of the review page under a stand-in document (D66): links only to web addresses, text always as text,
// and copying that works without the clipboard API, which browsers offer only over https or on localhost.
import { test } from 'node:test';
import assert from 'node:assert/strict';

import { installDocument } from './dom_stub.mjs';
import { copyText, h, link } from '../../app/ui/static/dom.mjs';

test('a link leads only to a web address; any other target leaves its words without a link', () => {
  installDocument();

  const web = link('https://de.wikipedia.org/wiki/Optik', 'Optik');
  assert.equal(web.tagName, 'A');
  assert.equal(web.getAttribute('href'), 'https://de.wikipedia.org/wiki/Optik');
  assert.equal(web.getAttribute('rel'), 'noopener noreferrer');
  for (const target of ['javascript:alert(1)', 'data:text/html,x', 'ms-settings:privacy', '//host/x', '']) {
    const plain = link(target, 'Material');
    assert.equal(plain.tagName, 'SPAN', target);
    assert.equal(plain.hasAttribute('href'), false, target);
    assert.equal(plain.textContent, 'Material');
  }
});

test('text that looks like markup stays text', () => {
  installDocument();

  const paragraph = h('p', {}, '<img src=x onerror=alert(1)>', null, false);

  assert.deepEqual(paragraph.children, []);
  assert.equal(paragraph.textContent, '<img src=x onerror=alert(1)>');
});

test('copying takes the clipboard API where the browser offers it', async () => {
  const written = [];
  const doc = installDocument({ clipboard: { writeText: async (value) => written.push(value) } });

  assert.equal(await copyText('# Kompendium'), true);
  assert.deepEqual(written, ['# Kompendium']);
  assert.deepEqual(doc.commands, []);
});

test('without the clipboard API - plain http - copying selects the text and gives the focus back', async () => {
  const doc = installDocument();
  const button = h('button', {}, 'Markdown kopieren');
  doc.body.append(button);
  button.focus();

  assert.equal(await copyText('# Kompendium'), true);
  assert.deepEqual(doc.commands, [{ command: 'copy', text: '# Kompendium' }]);
  assert.deepEqual(doc.body.children, [button], 'the helping field is gone again');
  assert.equal(doc.activeElement, button);
});

test('copying says so when the browser refuses both ways', async () => {
  const doc = installDocument({ clipboard: { writeText: async () => Promise.reject(new Error('denied')) } });
  doc.copyResult = false;

  assert.equal(await copyText('# Kompendium'), false);
});
