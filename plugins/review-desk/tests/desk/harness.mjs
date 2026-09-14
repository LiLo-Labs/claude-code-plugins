// Loads a built desk in Chromium with window.claude stubbed, so the page's code
// runs outside the claude.ai host.
//
// The stub is written from the runtime's db.d.ts and artifact.d.ts, not observed
// on the host, so it can drift. Two things keep it honest:
// - Everything it hands the page is deep-frozen, as the real store's snapshots
//   are. Code that mutates what it read throws here as it does on the host.
// - A member the page reaches for that the stub does not implement is recorded
//   in missing() and thrown, so a new call cannot pass silently against a stub
//   that ignores it. afterEach in the tests asserts missing() is empty.
import {chromium} from 'playwright';
import {execFileSync} from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {fileURLToPath} from 'node:url';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const ORIGIN = 'https://desk.test';

export function payload(extra = {}){
  return {repo: 'LiLo-Labs/claude-code-plugins', number: 42, title: 'Harness desk',
    url: 'https://github.com/LiLo-Labs/claude-code-plugins/pull/42', summary: '2 files',
    body: '## What it does\n\nA plain description.\n', documents: [], openers: [],
    ...extra};
}

// The real build, not a copy of it: the harness runs build_desk.py.
export function build(data, title = 'Harness Desk'){
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'desk-'));
  const src = path.join(dir, 'payload.json'), out = path.join(dir, 'desk.html');
  fs.writeFileSync(src, JSON.stringify(data));
  execFileSync('python3', [path.join(ROOT, 'build_desk.py'), src, title, '--out', out]);
  const html = fs.readFileSync(out, 'utf8');
  fs.rmSync(dir, {recursive: true, force: true});
  return html;
}

// Runs in the page before any of its scripts. Serialised by Playwright, so it
// may use only its argument.
function installStub({seed, capabilities, publishError, getDelay, getFailures, leases: held}){
  const frozen = v => {
    if (v && typeof v === 'object'){ Object.values(v).forEach(frozen); Object.freeze(v); }
    return v;
  };
  const clone = v => JSON.parse(JSON.stringify(v));
  const store = new Map(Object.entries(seed || {}).map(([k, v]) => [k, clone(v)]));
  // `leases` maps a document path to the ms left on a lease another view holds.
  const leases = new Map(Object.entries(held || {}).map(([p, ms]) =>
    [p, {holder: 'another-view', expires: Date.now() + ms}]));
  const docSubs = new Map(), colSubs = new Map();
  const log = [], rings = [], missing = [];
  let version = 0, failuresLeft = getFailures || 0;

  const fail = (code, message) => Object.assign(new Error(message), {code});
  const segments = p => {
    if (typeof p !== 'string' || !p) throw new TypeError('path must be a non-empty string');
    const s = p.split('/');
    if (s.some(x => !/^[A-Za-z0-9_\-.~:@+]{1,200}$/.test(x) || x === '.' || x === '..'))
      throw new TypeError('bad path segment in ' + p);
    return s;
  };
  const parentOf = p => p.split('/').slice(0, -1).join('/');

  // Unknown members throw and are recorded. `then` stays undefined so awaiting
  // the namespace does not mistake it for a promise.
  const strict = (name, target) => new Proxy(target, {
    get(t, key){
      if (key in t || typeof key === 'symbol' || key === 'then' || key === 'toJSON') return t[key];
      missing.push(name + '.' + String(key));
      throw new TypeError('stub has no ' + name + '.' + String(key));
    },
  });

  const docSnap = p => frozen({id: p.split('/').pop(), exists: store.has(p),
    data: (d => () => d)(store.has(p) ? frozen(clone(store.get(p))) : undefined),
    metadata: {fromCache: false, hasPendingWrites: false}});
  const colSnap = c => {
    const docs = [...store.keys()].filter(k => parentOf(k) === c).sort()
      .map(k => docSnap(k));
    return frozen({docs, size: docs.length, empty: !docs.length,
      docChanges: () => { missing.push('QuerySnapshot.docChanges'); throw new TypeError('stub has no docChanges'); },
      metadata: {fromCache: false, hasPendingWrites: false}});
  };
  const notify = p => {
    (docSubs.get(p) || []).forEach(cb => cb(docSnap(p)));
    const c = parentOf(p);
    (colSubs.get(c) || []).forEach(cb => cb(colSnap(c)));
  };
  const put = (p, data, who) => {
    if (data === null) store.delete(p); else store.set(p, clone(data));
    log.push({op: data === null ? 'delete' : 'set', path: p, by: who, data: data && clone(data)});
    setTimeout(() => notify(p), 0);
  };
  const subscribe = (map, key, cb, snap) => {
    const list = map.get(key) || []; map.set(key, list); list.push(cb);
    setTimeout(() => list.includes(cb) && cb(snap()), 0);
    return () => { const i = list.indexOf(cb); if (i >= 0) list.splice(i, 1); };
  };

  const docRef = p => {
    if (segments(p).length % 2) throw new TypeError('document path needs an even number of segments: ' + p);
    return strict('doc', {
      id: p.split('/').pop(), path: p,
      // getDelay holds every document read; getFailures rejects the first N of
      // them with `unavailable`, the code db.d.ts calls transient. The snapshot
      // is taken when the read is made, so a write landing during the delay is
      // missing from what comes back, as it would be on a real round trip.
      get: async () => {
        log.push({op: 'get', path: p});
        const snap = docSnap(p);
        if (getDelay) await new Promise(r => setTimeout(r, getDelay));
        if (failuresLeft > 0){ failuresLeft--; throw fail('unavailable', 'stubbed unavailable'); }
        return snap;
      },
      set: async data => {
        if (!data || typeof data !== 'object' || Array.isArray(data))
          throw fail('invalid_argument', 'body must be an object');
        put(p, data, 'page');
      },
      update: async data => {
        if (!store.has(p)) throw fail('invalid_argument', 'update needs an existing document');
        put(p, {...store.get(p), ...clone(data)}, 'page');
      },
      delete: async () => put(p, null, 'page'),
      // db.d.ts: set-if-not-busy, ttlMs clamped to [1000, 600000] with 0 or
      // absent meaning 30000, busy resolves {acquired: false} with only the
      // expiry, and a grant merges `data` into the body.
      acquire: async ({holder, ttlMs, data} = {}) => {
        if (typeof holder !== 'string' || !holder) throw fail('invalid_argument', 'holder is required');
        const now = Date.now(), held = leases.get(p);
        log.push({op: 'acquire', path: p, holder});
        if (held && held.expires > now && held.holder !== holder)
          return {acquired: false, expiresAt: new Date(held.expires).toISOString()};
        const expires = now + Math.min(Math.max(ttlMs || 30000, 1000), 600000);
        leases.set(p, {holder, expires});
        if (data) put(p, {...(store.get(p) || {}), ...clone(data)}, 'page');
        return {acquired: true, version: ++version, holder,
          expiresAt: new Date(expires).toISOString()};
      },
      onSnapshot: (next, error) => subscribe(docSubs, p, next, () => docSnap(p)),
      collection: sub => colRef(p + '/' + sub),
    });
  };
  const colRef = c => {
    if (!(segments(c).length % 2)) throw new TypeError('collection path needs an odd number of segments: ' + c);
    return strict('collection', {
      path: c,
      doc: id => docRef(c + '/' + (id || Math.random().toString(36).slice(2, 12))),
      get: async () => colSnap(c),
      onSnapshot: (next, error) => subscribe(colSubs, c, next, () => colSnap(c)),
    });
  };

  const db = strict('db', {doc: docRef, collection: colRef});
  const artifact = strict('artifact', {
    publish: async files => {
      if (publishError) throw fail(publishError, 'stubbed ' + publishError);
      if (typeof files === 'string' || !files || typeof files !== 'object')
        throw fail('invalid_content', 'the stub accepts only the files form; an html publish would reload the page');
      const ring = {files: Object.keys(files)};
      if (typeof files['doorbell.json'] === 'string') ring.doorbell = JSON.parse(files['doorbell.json']);
      rings.push(ring);
      log.push({op: 'publish', ring});
      return {version: 'v' + (++version)};
    },
  });

  window.__desk = {
    store: () => Object.fromEntries([...store].map(([k, v]) => [k, clone(v)])),
    log: () => clone(log), rings: () => clone(rings), missing: () => missing.slice(),
    // A write from outside the page, as the session's write_db lands.
    write: (p, data) => put(p, data, 'session'),
  };
  window.claude = strict('claude', {
    use: async name => (capabilities.includes(name) ? {db, artifact}[name] || null : null),
  });
}

export async function launch(){
  return chromium.launch();
}

// Opens a desk. `seed` is the store as it stands before the page loads.
export async function open(browser, {data = payload(), title, seed = {},
    capabilities = ['db', 'artifact'], publishError = null, getDelay = 0, getFailures = 0,
    leases = {}} = {}){
  const html = build(data, title);
  const context = await browser.newContext();
  const page = await context.newPage();
  const errors = [];
  page.on('pageerror', e => errors.push(e.message));
  await page.addInitScript(installStub, {seed, capabilities, publishError, getDelay, getFailures, leases});
  // Nothing leaves the machine: fonts, highlight.js and mermaid are refused, which
  // the page is built to survive (it loses colour and drawings, nothing else).
  await page.route('**/*', route => {
    if (route.request().url() === ORIGIN + '/') {
      // The host wraps the file in this skeleton.
      return route.fulfill({contentType: 'text/html', body: '<!doctype html><html><head>'
        + '<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
        + '</head><body>' + html});
    }
    return route.abort();
  });
  await page.goto(ORIGIN + '/');
  const pr = 'review/pr-' + data.number;
  const desk = {
    page, errors, pr, html,
    store: () => page.evaluate(() => window.__desk.store()),
    log: () => page.evaluate(() => window.__desk.log()),
    rings: () => page.evaluate(() => window.__desk.rings()),
    missing: () => page.evaluate(() => window.__desk.missing()),
    write: (p, v) => page.evaluate(([p, v]) => window.__desk.write(p, v), [p, v]),
    reply: (turn, text, status = 'done') =>
      desk.write(pr + '/replies/' + turn, {turn, status, text, at: new Date().toISOString()}),
    presence: (id, resume) => desk.write(pr + '/presence/' + id, resume ? {resume} : {}),
    context: (name, v) => desk.write(pr + '/context/' + name, v),
    document: (id, name, text) => desk.write(pr + '/documents/' + id, {name, text}),
    // Resolves once fn(store, arg) is truthy, polling the page's store from here.
    until: async (fn, arg, timeout = 5000) => {
      const end = Date.now() + timeout;
      for (;;){
        const store = await desk.store();
        if (fn(store, arg)) return store;
        if (Date.now() > end) throw new Error('store never matched ' + fn + '\n' + JSON.stringify(store));
        await new Promise(r => setTimeout(r, 50));
      }
    },
    close: () => context.close(),
  };
  return desk;
}
