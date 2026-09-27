/**
 * Redirects: a hop that leaves the GeoLens origin carries no credentials or
 * client headers, only Range and the If-* preconditions; hops on the origin
 * keep them all. Two local servers on different ports stand in for the
 * GeoLens API and a storage host, and record every request they receive.
 *
 * Run: node --test test/redirects.test.mjs
 */
import { test, before, after } from 'node:test';
import assert from 'node:assert/strict';
import http from 'node:http';
import { randomUUID } from 'node:crypto';
import { createGeolensClient } from '../dist/auth.js';
import { RedirectError, notModified } from '../dist/index.js';
import { downloadCogDatasetsDatasetIdDownloadCogGet as downloadCog } from '../dist/client/sdk.gen.js';

const BODY = new Uint8Array([0x49, 0x49, 0x2a, 0x00, 1, 2, 3, 4]); // TIFF marker + filler

function recordingServer() {
  const server = {
    seen: [],
    respond: (req, res) => res.end(BODY),
  };
  server.http = http.createServer((req, res) => {
    server.seen.push({ method: req.method, url: req.url, headers: req.headers });
    server.respond(req, res);
  });
  return server;
}

const api = recordingServer();
const storage = recordingServer();

function origin(server) {
  return `http://127.0.0.1:${server.http.address().port}`;
}

function redirect(res, location, status = 302) {
  res.writeHead(status, { location });
  res.end();
}

before(async () => {
  await Promise.all(
    [api, storage].map((s) => new Promise((resolve) => s.http.listen(0, '127.0.0.1', resolve))),
  );
});

after(() => {
  api.http.close();
  storage.http.close();
});

function reset() {
  api.seen = [];
  storage.seen = [];
  api.respond = (req, res) => res.end(BODY);
  storage.respond = (req, res) => res.end(BODY);
}

function client(auth, customHeader) {
  const sdk = createGeolensClient({ baseUrl: origin(api), ...auth });
  sdk.client.setConfig({ headers: { 'X-Custom-Header': customHeader } });
  return sdk.client;
}

function assertNoneOf(headers, secrets) {
  for (const name of ['authorization', 'x-api-key', 'x-custom-header', 'cookie']) {
    assert.equal(headers[name], undefined, `${name} reached the other origin`);
  }
  const joined = Object.values(headers).join(' ');
  for (const secret of secrets) {
    assert.ok(!joined.includes(secret), 'a secret reached the other origin');
  }
}

async function bytes(blob) {
  return new Uint8Array(await blob.arrayBuffer());
}

for (const [mode, auth] of [
  ['bearer', (secret) => ({ bearerToken: secret })],
  ['API key', (secret) => ({ apiKey: secret })],
]) {
  test(`${mode}: a cross-origin 302 reaches the target with no credentials or client headers`, async () => {
    reset();
    const [credential, custom] = [randomUUID(), randomUUID()];
    api.respond = (req, res) => redirect(res, `${origin(storage)}/bucket/cog.tif?X-Amz-Signature=abc`);

    const result = await downloadCog({ client: client(auth(credential), custom), path: { dataset_id: 'd1' } });

    assert.equal(result.error, undefined);
    assert.deepEqual(await bytes(result.data), BODY);
    // The GeoLens request carried both, so their absence below is the SDK's doing.
    const sent = Object.values(api.seen[0].headers).join(' ');
    assert.ok(sent.includes(credential) && sent.includes(custom));
    assert.equal(storage.seen.length, 1);
    assert.equal(storage.seen[0].url, '/bucket/cog.tif?X-Amz-Signature=abc');
    assertNoneOf(storage.seen[0].headers, [credential, custom]);
  });
}

test('an anonymous client: a custom header does not reach the cross-origin target', async () => {
  reset();
  const custom = randomUUID();
  api.respond = (req, res) => redirect(res, `${origin(storage)}/cog.tif`);

  const result = await downloadCog({ client: client({}, custom), path: { dataset_id: 'd1' } });

  assert.deepEqual(await bytes(result.data), BODY);
  assert.equal(api.seen[0].headers['x-custom-header'], custom);
  assertNoneOf(storage.seen[0].headers, [custom]);
});

test('a same-origin 307 keeps the credentials', async () => {
  reset();
  const credential = randomUUID();
  api.respond = (req, res) => {
    if (req.url.startsWith('/files/')) {
      res.writeHead(req.headers['x-api-key'] === credential ? 200 : 401);
      res.end(BODY);
      return;
    }
    redirect(res, '/files/cog.tif', 307);
  };

  const result = await downloadCog({ client: client({ apiKey: credential }, 'c'), path: { dataset_id: 'd1' } });

  assert.equal(result.error, undefined);
  assert.deepEqual(await bytes(result.data), BODY);
  assert.equal(api.seen[1].url, '/files/cog.tif');
  assert.equal(api.seen[1].headers['x-api-key'], credential);
});

// A caller's fetch wrapper that adds a credential to everything it sends.
function addingAuthorization(secret, calls) {
  return (input, init) => {
    const request = new Request(input, init);
    calls.push(request.url);
    request.headers.set('Authorization', `Bearer ${secret}`);
    return fetch(request);
  };
}

test("a client fetch that adds credentials isn't used once a redirect leaves the origin", async () => {
  reset();
  const [credential, added] = [randomUUID(), randomUUID()];
  api.respond = (req, res) => redirect(res, `${origin(storage)}/cog.tif`);
  const calls = [];
  const sdk = client({ apiKey: credential }, 'c');
  sdk.setConfig({ fetch: addingAuthorization(added, calls) });

  const result = await downloadCog({ client: sdk, path: { dataset_id: 'd1' } });

  assert.deepEqual(await bytes(result.data), BODY);
  assert.equal(api.seen[0].headers.authorization, `Bearer ${added}`);
  assert.equal(calls.length, 1);
  assertNoneOf(storage.seen[0].headers, [credential, added]);
});

test('after leaving the origin, a redirect back to it carries no credentials', async () => {
  reset();
  const [credential, added] = [randomUUID(), randomUUID()];
  api.respond = (req, res) =>
    req.url.startsWith('/files/') ? res.end(BODY) : redirect(res, `${origin(storage)}/cog.tif`);
  storage.respond = (req, res) => redirect(res, `${origin(api)}/files/cog.tif`);
  const calls = [];
  const sdk = client({ apiKey: credential }, 'c');
  sdk.setConfig({ fetch: addingAuthorization(added, calls) });

  const result = await downloadCog({ client: sdk, path: { dataset_id: 'd1' } });

  assert.deepEqual(await bytes(result.data), BODY);
  assert.equal(api.seen.length, 2);
  assert.equal(calls.length, 1);
  assertNoneOf(api.seen[1].headers, [credential, added]);
});

test('a caller interceptor that rebuilds the request cannot turn following back on', async () => {
  reset();
  const credential = randomUUID();
  api.respond = (req, res) => redirect(res, `${origin(storage)}/cog.tif`);
  const sdk = client({ apiKey: credential }, 'c');
  sdk.interceptors.request.use((req) => new Request(req.url, { method: req.method, headers: req.headers }));

  const result = await downloadCog({ client: sdk, path: { dataset_id: 'd1' } });

  assert.deepEqual(await bytes(result.data), BODY);
  assert.equal(api.seen[0].headers['x-api-key'], credential);
  assertNoneOf(storage.seen[0].headers, [credential]);
});

for (const [label, ifMatch, status] of [
  ['matching', '"v1"', 206],
  ['stale', '"v0"', 412],
]) {
  test(`a cross-origin target gets Range and a ${label} If-Match, and nothing else`, async () => {
    reset();
    const [credential, custom] = [randomUUID(), randomUUID()];
    api.respond = (req, res) => redirect(res, `${origin(storage)}/cog.tif`);
    storage.respond = (req, res) => {
      if (req.headers['if-match'] !== '"v1"') {
        res.writeHead(412);
        res.end();
        return;
      }
      res.writeHead(206, { 'Content-Range': `bytes 2-5/${BODY.length}` });
      res.end(BODY.slice(2, 6));
    };

    const result = await downloadCog({
      client: client({ apiKey: credential }, custom),
      path: { dataset_id: 'd1' },
      headers: { Range: 'bytes=2-5', 'If-Match': ifMatch },
    });

    assert.equal(result.response.status, status);
    if (status === 206) {
      assert.deepEqual(await bytes(result.data), BODY.slice(2, 6));
    }
    assert.equal(storage.seen[0].headers.range, 'bytes=2-5');
    assert.equal(storage.seen[0].headers['if-match'], ifMatch);
    assertNoneOf(storage.seen[0].headers, [credential, custom]);
  });
}

test('aborting while a hop off the origin is in flight stops it', async () => {
  reset();
  const controller = new AbortController();
  api.respond = (req, res) => redirect(res, `${origin(storage)}/cog.tif`);
  storage.respond = (req, res) => {
    controller.abort();
    const late = setTimeout(() => res.end(BODY), 500);
    res.on('close', () => clearTimeout(late));
  };

  const result = await downloadCog({
    client: client({ apiKey: randomUUID() }, 'c'),
    path: { dataset_id: 'd1' },
    signal: controller.signal,
  });

  assert.equal(result.error?.name, 'AbortError');
  assert.equal(storage.seen.length, 1);
});

test('a streaming POST answered with a cross-origin 307 is not followed', async () => {
  reset();
  api.respond = (req, res) => redirect(res, `${origin(storage)}/stream`, 307);
  const errors = [];
  const sdk = client({ apiKey: randomUUID() }, 'c');

  const { stream } = await sdk.sse.post({
    url: '/ai/chat/stream',
    body: { message: 'hi' },
    sseMaxRetryAttempts: 1,
    onSseError: (error) => errors.push(error),
  });
  for await (const _event of stream) {
    // Drain: the stream ends after its one failed attempt.
  }

  assert.match(String(errors[0]), /307/);
  assert.equal(storage.seen.length, 0);
});

test('a same-origin hop goes through the client fetch', async () => {
  reset();
  api.respond = (req, res) =>
    req.url.startsWith('/files/') ? res.end(BODY) : redirect(res, '/files/cog.tif', 307);
  const calls = [];
  const sdk = client({ apiKey: randomUUID() }, 'c');
  sdk.setConfig({
    fetch: (input, init) => {
      const request = new Request(input, init);
      calls.push(new URL(request.url).pathname);
      return fetch(request);
    },
  });

  const result = await downloadCog({ client: sdk, path: { dataset_id: 'd1' } });

  assert.deepEqual(await bytes(result.data), BODY);
  assert.deepEqual(calls, ['/datasets/d1/download/cog', '/files/cog.tif']);
});

test("a same-origin hop keeps the caller's credentials mode, and a hop off the origin omits them", async () => {
  reset();
  api.respond = (req, res) =>
    req.url.startsWith('/files/')
      ? redirect(res, `${origin(storage)}/cog.tif`)
      : redirect(res, '/files/cog.tif', 307);
  const [onOrigin, offOrigin] = [[], []];
  const realFetch = globalThis.fetch;
  const sdk = client({ apiKey: randomUUID() }, 'c');
  sdk.setConfig({
    fetch: (input, init) => {
      const request = new Request(input, init);
      onOrigin.push(request.credentials);
      return realFetch(request);
    },
  });
  globalThis.fetch = (request) => {
    offOrigin.push(request.credentials);
    return realFetch(request);
  };

  let result;
  try {
    result = await downloadCog({ client: sdk, path: { dataset_id: 'd1' }, credentials: 'include' });
  } finally {
    globalThis.fetch = realFetch;
  }

  assert.deepEqual(await bytes(result.data), BODY);
  assert.deepEqual(onOrigin, ['include', 'include']);
  assert.deepEqual(offOrigin, ['omit']);
});

for (const [label, conditional, reported] of [
  ['an If-None-Match read', { 'If-None-Match': '"remote-etag"' }, true],
  ['an If-Modified-Since read', { 'If-Modified-Since': 'Wed, 01 Jan 2025 00:00:00 GMT' }, true],
  ['an unconditional read', {}, false],
]) {
  test(`a 304 from the target of ${label} is ${reported ? '' : 'not '}reported as not modified`, async () => {
    reset();
    api.respond = (req, res) => redirect(res, `${origin(storage)}/cog.tif`);
    storage.respond = (req, res) => {
      res.writeHead(304);
      res.end();
    };

    const result = await downloadCog({
      client: client({ apiKey: randomUUID() }, 'c'),
      path: { dataset_id: 'd1' },
      headers: conditional,
    });

    assert.equal(result.response.status, 304);
    assert.equal(result.data, undefined);
    assert.equal(notModified(result), reported);
  });
}

test('a 3xx without a Location from the target is an error', async () => {
  reset();
  api.respond = (req, res) => redirect(res, `${origin(storage)}/cog.tif`);
  storage.respond = (req, res) => {
    res.writeHead(302);
    res.end();
  };

  const result = await downloadCog({ client: client({ apiKey: randomUUID() }, 'c'), path: { dataset_id: 'd1' } });

  assert.equal(result.response.status, 302);
  assert.notEqual(result.error, undefined);
  assert.equal(result.data, undefined);
  assert.equal(storage.seen.length, 1);
});

test('a non-http(s) Location is refused', async () => {
  reset();
  api.respond = (req, res) => redirect(res, 'data:application/octet-stream,not-the-cog');

  const result = await downloadCog({ client: client({ apiKey: randomUUID() }, 'c'), path: { dataset_id: 'd1' } });

  assert.ok(result.error instanceof RedirectError, `expected a RedirectError, got ${result.error}`);
  assert.match(result.error.message, /unsupported URL scheme: data:/);
});

test('a 21st redirect is refused', async () => {
  reset();
  // Stops redirecting on its own after 30 hops, so a missing limit fails
  // the test instead of hanging it.
  api.respond = (req, res) => (api.seen.length > 30 ? res.end(BODY) : redirect(res, `/hop/${api.seen.length}`));

  const result = await downloadCog({ client: client({ apiKey: randomUUID() }, 'c'), path: { dataset_id: 'd1' } });

  assert.ok(result.error instanceof RedirectError, `expected a RedirectError, got ${result.error}`);
  assert.equal(api.seen.length, 21);
});

test('a redirect answering a POST is returned unfollowed', async () => {
  reset();
  api.respond = (req, res) => redirect(res, `${origin(storage)}/elsewhere`, 307);
  const sdk = client({ apiKey: randomUUID() }, 'c');

  const result = await sdk.post({ url: '/things', body: { name: 'x' } });

  assert.equal(result.response.status, 307);
  assert.equal(storage.seen.length, 0);
});

for (const policy of ['error', 'manual']) {
  for (const [where, configure] of [
    ['per call', () => ({ redirect: policy })],
    [
      'on the client',
      (sdk) => {
        sdk.setConfig({ redirect: policy });
        return {};
      },
    ],
  ]) {
    test(`redirect: '${policy}' set ${where} gets what fetch gives`, async () => {
      reset();
      api.respond = (req, res) => redirect(res, `${origin(storage)}/cog.tif`);
      const sdk = client({ apiKey: randomUUID() }, 'c');
      const perCall = configure(sdk);

      const result = await downloadCog({ client: sdk, path: { dataset_id: 'd1' }, ...perCall });

      if (policy === 'error') {
        assert.ok(result.error instanceof TypeError, `expected a TypeError, got ${result.error}`);
        assert.equal(result.response, undefined, 'fetch rejects without exposing the redirect');
      } else {
        assert.equal(result.response.status, 302);
        assert.equal(result.response.headers.get('location'), `${origin(storage)}/cog.tif`);
      }
      assert.equal(storage.seen.length, 0);
    });
  }
}

test("mode: 'same-origin' rejects a redirect to another origin", async () => {
  reset();
  api.respond = (req, res) => redirect(res, `${origin(storage)}/cog.tif`);

  const result = await downloadCog({
    client: client({}, 'c'),
    path: { dataset_id: 'd1' },
    mode: 'same-origin',
  });

  assert.ok(result.error instanceof TypeError, `expected a TypeError, got ${result.error}`);
  assert.equal(storage.seen.length, 0);
});

test("mode: 'same-origin' still follows a redirect on the same origin", async () => {
  reset();
  api.respond = (req, res) =>
    req.url.startsWith('/files/') ? res.end(BODY) : redirect(res, '/files/cog.tif', 307);

  const result = await downloadCog({
    client: client({}, 'c'),
    path: { dataset_id: 'd1' },
    mode: 'same-origin',
  });

  assert.equal(result.error, undefined);
  assert.deepEqual(await bytes(result.data), BODY);
});

test('keepalive, the referrer and its policy are kept on every request', async () => {
  reset();
  api.respond = (req, res) =>
    req.url.startsWith('/files/')
      ? redirect(res, `${origin(storage)}/cog.tif`)
      : redirect(res, '/files/cog.tif', 307);
  const referrer = `${origin(api)}/maps/m1`;
  const seen = [];
  const realFetch = globalThis.fetch;
  const record = (request) => {
    seen.push([request.keepalive, request.referrer, request.referrerPolicy]);
    return realFetch(request);
  };
  const sdk = client({ apiKey: randomUUID() }, 'c');
  sdk.setConfig({ fetch: record });
  globalThis.fetch = record;

  let result;
  try {
    result = await downloadCog({
      client: sdk,
      path: { dataset_id: 'd1' },
      keepalive: true,
      referrer,
      referrerPolicy: 'unsafe-url',
    });
  } finally {
    globalThis.fetch = realFetch;
  }

  assert.deepEqual(await bytes(result.data), BODY);
  assert.deepEqual(seen, [
    [true, referrer, 'unsafe-url'],
    [true, referrer, 'unsafe-url'],
    [true, referrer, 'unsafe-url'],
  ]);
});

test("cache: 'no-store' is kept on a hop to another origin", async () => {
  reset();
  api.respond = (req, res) => redirect(res, `${origin(storage)}/cog.tif`);

  const result = await downloadCog({
    client: client({ apiKey: randomUUID() }, 'c'),
    path: { dataset_id: 'd1' },
    cache: 'no-store',
  });

  assert.deepEqual(await bytes(result.data), BODY);
  // Node's fetch sends these for a no-store request; the header allowlist
  // doesn't carry them, so they come from the hop's own cache mode.
  assert.equal(storage.seen[0].headers['cache-control'], 'no-cache');
  assert.equal(storage.seen[0].headers.pragma, 'no-cache');
});

// A browser answers a manual redirect with an opaque response: type
// 'opaqueredirect', status 0, no readable headers. A mock fetch stands in.
function browserFetch(calls) {
  return async (request) => {
    calls.push({ url: request.url, redirect: request.redirect });
    if (request.redirect === 'error') {
      throw new TypeError('Failed to fetch');
    }
    const response = new Response(null);
    Object.defineProperty(response, 'type', { value: 'opaqueredirect' });
    Object.defineProperty(response, 'status', { value: 0 });
    Object.defineProperty(response, 'ok', { value: false });
    return response;
  };
}

for (const [mode, auth] of [
  ['bearer', { bearerToken: randomUUID() }],
  ['API key', { apiKey: randomUUID() }],
]) {
  test(`browser, ${mode}: a redirect of a request with credentials is refused`, async () => {
    const calls = [];
    const sdk = client(auth, 'c');
    sdk.setConfig({ fetch: browserFetch(calls) });

    const result = await downloadCog({ client: sdk, path: { dataset_id: 'd1' } });

    assert.ok(result.error instanceof RedirectError, `expected a RedirectError, got ${result.error}`);
    assert.equal(calls.length, 1);
  });
}

test('browser: a redirect of a request without credentials is sent once more, with only Range and preconditions', async () => {
  const calls = [];
  const resent = [];
  const sdk = client({}, randomUUID());
  sdk.setConfig({ fetch: browserFetch(calls) });
  const realFetch = globalThis.fetch;
  globalThis.fetch = async (request) => {
    resent.push(request);
    return new Response(BODY, { headers: { 'Content-Type': 'image/tiff' } });
  };

  let result;
  try {
    result = await downloadCog({
      client: sdk,
      path: { dataset_id: 'd1' },
      headers: { Range: 'bytes=2-5', 'If-Match': '"v1"' },
    });
  } finally {
    globalThis.fetch = realFetch;
  }

  assert.equal(result.error, undefined);
  assert.deepEqual(await bytes(result.data), BODY);
  assert.deepEqual(calls.map((call) => call.redirect), ['manual']);
  assert.equal(resent.length, 1);
  const [again] = resent;
  assert.equal(again.url, calls[0].url);
  assert.equal(again.redirect, 'follow');
  assert.equal(again.credentials, 'omit');
  assert.deepEqual([...again.headers.keys()].sort(), ['if-match', 'range']);
  assert.equal(again.headers.get('range'), 'bytes=2-5');
});

for (const policy of ['error', 'manual']) {
  test(`browser: redirect: '${policy}' gets what fetch gives`, async () => {
    const calls = [];
    const sdk = client({ apiKey: randomUUID() }, 'c');
    sdk.setConfig({ fetch: browserFetch(calls) });

    const result = await downloadCog({ client: sdk, path: { dataset_id: 'd1' }, redirect: policy });

    assert.deepEqual(calls.map((call) => call.redirect), [policy]);
    if (policy === 'error') {
      assert.ok(result.error instanceof TypeError, `expected a TypeError, got ${result.error}`);
      assert.equal(result.response, undefined, 'fetch rejects without exposing the redirect');
    } else {
      assert.equal(result.response.type, 'opaqueredirect');
      assert.ok(!(result.error instanceof RedirectError), 'a manual redirect is returned, not refused');
    }
    assert.equal(calls.length, 1);
  });
}

test("browser: the resend keeps mode: 'same-origin' and cache: 'no-store'", async () => {
  const calls = [];
  const resent = [];
  const sdk = client({}, 'c');
  sdk.setConfig({ fetch: browserFetch(calls) });
  const realFetch = globalThis.fetch;
  // The browser follows the resend itself and refuses a same-origin
  // request's redirect to another origin.
  globalThis.fetch = async (request) => {
    resent.push(request);
    if (request.mode === 'same-origin') {
      throw new TypeError('Failed to fetch');
    }
    return new Response(BODY, { headers: { 'Content-Type': 'image/tiff' } });
  };

  let result;
  try {
    result = await downloadCog({
      client: sdk,
      path: { dataset_id: 'd1' },
      mode: 'same-origin',
      cache: 'no-store',
    });
  } finally {
    globalThis.fetch = realFetch;
  }

  assert.ok(result.error instanceof TypeError, `expected a TypeError, got ${result.error}`);
  assert.equal(resent.length, 1);
  assert.equal(resent[0].mode, 'same-origin');
  assert.equal(resent[0].cache, 'no-store');
});
