// The page as a whole (D66): main.mjs on the elements of index.html under the stand-in document, with a server that
// answers when a test says so - two runs of one mode in a race, a stop, and where the focus goes when a run ends.
import { test } from 'node:test';
import assert from 'node:assert/strict';

import { installDocument } from './dom_stub.mjs';
import { OPTIONS, saved } from './saved_answers.mjs';

let pages = 0;

// Every promise the page chains on one that settled has run; no timer of the page is waited for
async function settle() {
  for (let turn = 0; turn < 20; turn += 1) await new Promise((resolve) => setImmediate(resolve));
}

/** The elements of index.html that main.mjs works with, main.mjs started on them, and the requests it sends: each
 * waits until the test answers it, and a stop rejects it as fetch does. */
async function openPage({ options = OPTIONS, stacked = false } = {}) {
  const doc = installDocument();
  const element = (tag, id, ...children) => {
    const node = doc.createElement(tag);
    node.setAttribute('id', id);
    node.append(...children);
    return node;
  };
  const keyBox = element('div', 'key-box', element('input', 'api-key'));
  keyBox.hidden = true;
  doc.body.append(element('p', 'server-note'), element('fieldset', 'modes'), element('div', 'form-slot'), keyBox, element('main', 'ergebnis', element('p', 'status'), element('div', 'results')));
  globalThis.window = { matchMedia: () => ({ matches: stacked }) };
  const requests = [];
  globalThis.fetch = (url, init = {}) => {
    if (url === 'options.json') return Promise.resolve(new Response(JSON.stringify(options)));
    return new Promise((resolve, reject) => {
      init.signal?.addEventListener('abort', () => reject(new DOMException('The operation was aborted.', 'AbortError')));
      const answer = (status, body) => resolve(new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } }));
      requests.push({ url: String(url), init, answer });
    });
  };
  await import(`../../app/ui/static/main.mjs?page=${(pages += 1)}`);
  await settle();
  const byId = (id) => doc.getElementById(id);
  const form = () => byId('form-slot').children[0];
  return {
    doc,
    byId,
    form,
    requests,
    field: (name) => form().descendants().find((node) => node.getAttribute('name') === name),
    button: (text) => doc.body.descendants().find((node) => node.tagName === 'BUTTON' && node.textContent === text),
    async submit() {
      form().listeners.submit[0]({ preventDefault() {} });
      await settle();
    },
  };
}

const COMPENDIUM = saved('compendium_topic').run.data;

test('a second run of a mode takes over from the first: the first stops, and only the answer of the second shows', async () => {
  const page = await openPage();
  page.field('topic').value = 'Optik';
  await page.submit();
  page.field('topic').value = 'Licht';
  await page.submit();

  page.requests[1].answer(200, COMPENDIUM);
  await settle();

  assert.equal(page.requests.length, 2);
  assert.equal(page.requests[0].init.signal.aborted, true, 'the first run stopped');
  assert.match(page.requests[1].init.body, /"topic":"Licht"/);
  assert.equal(page.byId('results').descendants().filter((node) => node.tagName === 'ARTICLE').length, 1);
  assert.match(page.byId('status').textContent, /^Kompendium fertig: /);
  assert.equal(page.form().getAttribute('aria-busy'), 'false');
});

test('a stopped run leaves what the mode showed before, says so, and keeps the focus on the answers', async () => {
  const page = await openPage();
  page.field('topic').value = 'Optik';
  await page.submit();

  const stop = page.button('Abbrechen');
  stop.focus();
  stop.click();
  await settle();

  assert.equal(page.requests[0].init.signal.aborted, true);
  assert.ok(page.byId('results').children[0].classList.contains('empty'), 'the introduction of the mode, as before the run');
  assert.match(page.byId('status').textContent, /^Abgebrochen; die vorige Anzeige bleibt\./);
  assert.equal(page.doc.activeElement, page.byId('ergebnis'), 'the focus was on "Abbrechen", which is gone');
});
