// The requests of the review page (D66): to the server of the page, the key the reader entered only in their header,
// and every way a request can end told apart - an answer, an error answer, no connection, a stop.
import { test } from 'node:test';
import assert from 'node:assert/strict';

import { installDocument } from './dom_stub.mjs';
import { ApiError, send } from '../../app/ui/static/api.mjs';

const KEY = 'k'.repeat(32);
const signal = () => new AbortController().signal;

/** fetch answered by `answer(url, init)`; the calls it got. Its headers are checked as a browser checks them: a sign
 * outside ISO-8859-1 throws before anything is sent. */
function serve(answer) {
  const calls = [];
  globalThis.fetch = async (url, init) => {
    new Headers(init.headers);
    calls.push({ url: String(url), init });
    return answer(url, init);
  };
  return calls;
}

const json = (status, body, headers = {}) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json', ...headers } });

test('a request goes to the server of the page, with the key only in its header', async () => {
  installDocument();
  const calls = serve(() => json(200, { matches: [] }, { 'X-Request-ID': 'r-7' }));

  const got = await send({ method: 'GET', path: 'api/v2/lehrplan/search', query: { q: 'Optik', limit: 5 } }, KEY, signal());
  await send({ method: 'POST', path: 'api/v2/qa', body: { topic: 'Optik' } }, '', signal());

  const [search, qa] = calls;
  assert.equal(search.url, 'https://kompendium.test/api/v2/lehrplan/search?q=Optik&limit=5');
  assert.deepEqual([search.init.method, search.init.headers, search.init.body], ['GET', { Accept: 'application/json', 'X-API-Key': KEY }, undefined]);
  assert.equal(qa.url, 'https://kompendium.test/api/v2/qa');
  assert.deepEqual(qa.init.headers, { Accept: 'application/json', 'Content-Type': 'application/json' }, 'no key, no header');
  assert.equal(qa.init.body, '{"topic":"Optik"}');
  assert.deepEqual([got.data, got.requestId], [{ matches: [] }, 'r-7']);
});

test('behind a proxy that puts a prefix in front, the endpoints resolve below it', async () => {
  installDocument({ baseURI: 'https://schule.example/kompendium/ui/' });
  const calls = serve(() => json(200, {}));

  await send({ method: 'POST', path: 'api/v2/entities', body: { text: 'x' } }, KEY, signal());

  assert.equal(calls[0].url, 'https://schule.example/kompendium/api/v2/entities');
});

test('an error answer keeps what the server said and the id it logged the request under', async () => {
  installDocument();
  serve(() => json(422, { detail: [{ loc: ['body', 'count'], msg: 'zu groß' }] }, { 'X-Request-ID': 'r-9' }));

  await assert.rejects(send({ method: 'POST', path: 'api/v2/qa', body: { count: 99 } }, KEY, signal()), (error) => {
    assert.ok(error instanceof ApiError);
    assert.deepEqual([error.status, error.message, error.requestId, error.detail[0].msg], [422, 'Die Eingaben passen nicht.', 'r-9', 'zu groß']);
    return true;
  });
});

test('an error page of a proxy instead of JSON is an error without details', async () => {
  installDocument();
  serve(() => new Response('<html>Bad Gateway</html>', { status: 502, headers: { 'Content-Type': 'text/html' } }));

  await assert.rejects(send({ method: 'POST', path: 'api/v2/qa', body: {} }, KEY, signal()), (error) => error.status === 502 && error.detail === null);
});

test('a server out of reach is no connection, and a request stopped before its answer stays a stop', async () => {
  installDocument();
  serve(() => Promise.reject(new TypeError('Failed to fetch')));
  await assert.rejects(send({ method: 'POST', path: 'api/v2/qa', body: {} }, KEY, signal()), (error) => error.status === 0 && error.message === 'Keine Verbindung zum Server.');

  serve(() => Promise.reject(new DOMException('The operation was aborted.', 'AbortError')));
  await assert.rejects(send({ method: 'POST', path: 'api/v2/qa', body: {} }, KEY, signal()), { name: 'AbortError' });
});

test('a key no header can carry is named as the problem, and nothing is sent', async () => {
  installDocument();
  const calls = serve(() => json(200, {}));
  const copied = [String.fromCharCode(0x200b), String.fromCharCode(0xa0), ' ', 'ä'].map((sign) => `${KEY.slice(0, 16)}${sign}${KEY.slice(16)}`);

  for (const key of copied) {
    await assert.rejects(send({ method: 'POST', path: 'api/v2/qa', body: {} }, key, signal()), (error) => {
      assert.ok(error instanceof ApiError);
      assert.match(error.message, /^Der API-Schlüssel enthält ein Zeichen, das sich nicht senden lässt/);
      return true;
    });
  }
  assert.equal(calls.length, 0);
});

test('a request stopped while its answer is read stays a stop, not an answer without data', async () => {
  installDocument();
  const controller = new AbortController();
  // The headers are there, the body is still coming when the reader presses "Abbrechen"
  serve((url, init) => ({
    ok: true,
    status: 200,
    headers: new Headers({ 'X-Request-ID': 'r-1' }),
    json: () => new Promise((resolve, reject) => init.signal.addEventListener('abort', () => reject(new DOMException('The operation was aborted.', 'AbortError')))),
  }));

  const pending = send({ method: 'POST', path: 'api/v2/compendium', body: { topic: 'Optik' } }, KEY, controller.signal);
  setTimeout(() => controller.abort(), 0);

  await assert.rejects(pending, { name: 'AbortError' });
});
