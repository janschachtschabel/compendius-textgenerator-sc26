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
    // What holds the focus, by its id or else its tag: comparing elements, assert would print the whole document
    focused: () => doc.activeElement.id || doc.activeElement.tagName,
    button: (text) => doc.body.descendants().find((node) => node.tagName === 'BUTTON' && node.textContent === text),
    async submit() {
      form().listeners.submit[0]({ preventDefault() {} });
      await settle();
    },
    async switchTo(mode) {
      byId(`modus-${mode}`).listeners.change[0]();
      await settle();
    },
  };
}

const REFUSED = { detail: 'Dieser Endpunkt verlangt einen gültigen API-Schlüssel im Header X-API-Key.' };

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
  assert.equal(page.focused(), 'ergebnis', 'the focus was on "Abbrechen", which is gone');
});

test('a server that wants a key the page thought it did not shows the box of the key, which takes the focus', async () => {
  const page = await openPage({ options: { ...OPTIONS, keys_required: false } });
  assert.equal(page.byId('key-box').hidden, true);
  page.field('topic').value = 'Optik';
  page.button('Kompendium erzeugen').focus();
  await page.submit();

  page.requests[0].answer(401, REFUSED);
  await settle();

  assert.equal(page.byId('key-box').hidden, false);
  assert.equal(page.focused(), 'api-key');
});

test('a key no header can carry shows its box and takes the focus as a refused one does', async () => {
  const page = await openPage({ options: { ...OPTIONS, keys_required: true } });
  page.byId('api-key').value = `${'k'.repeat(16)}${String.fromCharCode(0x200b)}${'k'.repeat(16)}`;
  page.field('topic').value = 'Optik';
  page.button('Kompendium erzeugen').focus();

  await page.submit();

  assert.equal(page.requests.length, 0, 'nothing was sent');
  assert.equal(page.focused(), 'api-key');
  assert.match(page.byId('results').textContent, /Der API-Schlüssel enthält ein Zeichen, das sich nicht senden lässt/);
});

test('a refused key takes no focus from a field the reader went on to type in', async () => {
  const page = await openPage();
  page.field('topic').value = 'Optik';
  page.button('Kompendium erzeugen').focus();
  await page.submit();
  const topic = page.field('topic');
  topic.focus(); // the next topic, typed while the first one runs

  page.requests[0].answer(401, REFUSED);
  await settle();

  assert.equal(page.focused(), topic.id);
  assert.equal(page.byId('key-box').hidden, false, 'the box shows all the same');
});

test('a run that ends while another mode is on screen moves no focus', async () => {
  const page = await openPage();
  page.field('topic').value = 'Optik';
  await page.submit();
  await page.switchTo('knowledge');
  page.doc.activeElement = page.doc.body; // the focus nowhere, as after a click beside the controls

  page.requests[0].answer(401, REFUSED);
  await settle();

  assert.equal(page.focused(), 'BODY');
});

test('stacked, the answer takes the focus from the button, but not from a field the reader went on to type in', async () => {
  const page = await openPage({ stacked: true });
  page.field('topic').value = 'Optik';
  page.button('Kompendium erzeugen').focus();
  await page.submit();
  page.requests[0].answer(200, COMPENDIUM);
  await settle();
  assert.equal(page.focused(), 'ergebnis', 'stacked, the answer lies below the form');

  page.button('Kompendium erzeugen').focus();
  await page.submit();
  const topic = page.field('topic');
  topic.focus();
  page.requests[1].answer(200, COMPENDIUM);
  await settle();

  assert.equal(page.focused(), topic.id);
});

test('the note on the server says whether its LLM answered its last check, not only whether one is configured', async () => {
  // Jan, 2026-10-02: "KI verfügbar" stood there while the b-api answered 502 - the page read only llm_configured
  const reason = 'b-api nicht erreichbar: b-api nach 1 Versuchen nicht erreichbar (HTTP 502)';
  const note = async (state) => (await openPage({ options: { ...OPTIONS, llm_configured: true, ...state } })).byId('server-note').textContent;

  assert.match(await note({ llm_available: false, llm_unavailable_reason: reason }), /^KI nicht erreichbar \(b-api nicht erreichbar: .*HTTP 502\)\): Profile mit KI liefern Texte nach den Regeln · Vorgabe des Servers: /);
  assert.match(await note({ llm_available: true, llm_unavailable_reason: null }), /^KI verfügbar · Vorgabe des Servers: /);
  assert.match(await note({ llm_available: null, llm_unavailable_reason: null }), /^KI eingerichtet · Vorgabe des Servers: /);
});

test('the field of a collection reads the node through its endpoint, with the key, and tells what it is (D77)', async () => {
  const page = await openPage();
  const id = '9e7ae956-e9df-430f-bace-f3db4b910013';
  page.field('node').value = `https://repository.staging.openeduhub.net/edu-sharing/components/collections?id=${id}`;
  page.form().listeners.input[0]();
  await settle();

  const reading = page.requests.find((one) => one.url.includes('/api/v2/nodes/'));
  assert.ok(reading.url.endsWith(`/api/v2/nodes/${id}`), reading.url);
  assert.equal(reading.init.method, 'GET');
  reading.answer(200, { node_id: id, kind: 'collection', title: 'Optik', subjects: ['Physik'], educational_contexts: ['Sekundarstufe I'], topic: 'Optik' });
  await settle();

  const status = page.form().descendants().find((node) => node.classList.contains('node-status'));
  assert.equal(status.textContent, 'Sammlung „Optik“ · Physik · Sekundarstufe I');
});
