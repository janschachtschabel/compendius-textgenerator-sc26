// The requests of the review page (D66): to the endpoints of this server, with the key the reader entered, timed
// from sending until the answer is read. An error answer becomes an ApiError that keeps what the server said.

import { ERRORS } from './texts.mjs';

export class ApiError extends Error {
  constructor(status, detail, requestId) {
    super(ERRORS[status] ?? `Der Server antwortete mit dem Status ${status}.`);
    this.status = status;
    this.detail = detail;
    this.requestId = requestId;
  }
}

/** Send one request of forms.mjs; resolves to the answer, its time in ms and the id the server logged it under. */
export async function send(request, key, signal) {
  const url = new URL(`../${request.path}`, document.baseURI); // the page lives at /ui/, the endpoints at /api/v2/
  for (const [name, value] of Object.entries(request.query ?? {})) url.searchParams.set(name, value);
  const headers = { Accept: 'application/json' };
  if (request.body) headers['Content-Type'] = 'application/json';
  if (key) headers['X-API-Key'] = key;
  const started = performance.now();
  let response;
  try {
    response = await fetch(url, { method: request.method, headers, body: request.body ? JSON.stringify(request.body) : undefined, signal });
  } catch (error) {
    if (error.name === 'AbortError') throw error;
    throw new ApiError(0, String(error.message ?? error), null);
  }
  const requestId = response.headers.get('X-Request-ID');
  const data = await response.json().catch((error) => {
    // A stop while the body comes stays a stop, not an answer without data; a proxy may answer an error with a page
    if (error.name === 'AbortError') throw error;
    return null;
  });
  const elapsedMs = performance.now() - started;
  if (!response.ok) throw new ApiError(response.status, data?.detail ?? null, requestId ?? data?.request_id ?? null);
  return { data, elapsedMs, requestId };
}
