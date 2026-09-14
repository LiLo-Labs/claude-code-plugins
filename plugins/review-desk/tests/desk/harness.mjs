// Loads a built desk in Chromium, or WebKit (see launch), with window.claude
// stubbed, so the page's code runs outside the claude.ai host.
//
// The stub is written from the runtime's db.d.ts and artifact.d.ts, not observed
// on the host, so it can drift. Three things keep it honest:
// - Everything it hands the page is deep-frozen, as the real store's snapshots
//   are. Code that mutates what it read throws here as it does on the host.
// - A member the page reaches for that the stub does not implement is recorded
//   in missing() and thrown, so a new call cannot pass silently against a stub
//   that ignores it. afterEach in the tests asserts missing() is empty.
// - An onSnapshot with no error callback is recorded in missing() too. db.d.ts:
//   without one a terminal error still kills the listener, only silently.
// - Page writes obey the rules build_desk.py prints for the desk, as db.d.ts
//   describes them: a write below a path's write level rejects invalid_argument.
//   The page writes as `level`, 'interact' unless a test says otherwise: rules never
//   limit the owner, so a page that passed only as the owner would fail for anyone
//   the desk is shared with. The session's writes (desk.write) are the owner's.
//
// Known gaps, each something the page does not depend on today: rules that set
// `read` or use {self} are refused at open() rather than half-enforced; the 64
// subscription cap is not enforced; an unchanged document is a new object on
// each delivery, where db.d.ts promises the same one; and the skeleton below lacks
// the host's small reset, [hidden]{display:none!important} included, so an element
// the page hides with `hidden` but styles with its own display stays visible here.
import {chromium, webkit} from 'playwright';
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

// The real build, not a copy of it: the harness runs build_desk.py, and takes the
// capabilities object from the line it prints, which is what the session
// publishes the desk with.
export function built(data, title = 'Harness Desk'){
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'desk-'));
  const src = path.join(dir, 'payload.json'), out = path.join(dir, 'desk.html');
  fs.writeFileSync(src, JSON.stringify(data));
  const printed = execFileSync('python3', [path.join(ROOT, 'build_desk.py'), src, title, '--out', out],
    {encoding: 'utf8'});
  const html = fs.readFileSync(out, 'utf8');
  fs.rmSync(dir, {recursive: true, force: true});
  const line = printed.split('\n').find(l => l.startsWith('capabilities: '));
  if (!line) throw new Error('build_desk.py printed no capabilities line:\n' + printed);
  return {html, capabilities: JSON.parse(line.slice('capabilities: '.length))};
}
export const build = (data, title) => built(data, title).html;

// Approve is two presses: #ok opens the confirm step, and Confirm records.
export async function approve(desk){
  await desk.page.click('#ok');
  await desk.page.click('#approveConfirm');
}

const LEVELS = ['view', 'interact', 'admin', 'owner'];
// artifact.d.ts, ArtifactErrorCode.
const PUBLISH_CODES = ['conflict', 'not_writer', 'not_declared', 'too_large', 'invalid_content',
  'read_only_path', 'rate_limited', 'consent_required', 'upstream_error', 'not_granted',
  'capability_disabled', 'capability_removed', 'transform_error'];

// Runs in every frame before any of its scripts. Serialised by Playwright, so it
// may use only its argument.
function installStub({seed, capabilities, publishError, getDelay, getFailures, leases: held,
    subscribeFailures, setFailures, setDelay, rules, level, levels}){
  const frozen = v => {
    if (v && typeof v === 'object'){ Object.values(v).forEach(frozen); Object.freeze(v); }
    return v;
  };
  const clone = v => JSON.parse(JSON.stringify(v));
  // One store per browser page. In openPair() each view is a frame of the same
  // page, so the frames find the top window's store and share it, as two open
  // views of one desk share the real one.
  let shared = window !== window.top && window.top.__deskShared;
  if (!shared){
    shared = window.__deskShared = {
      store: new Map(Object.entries(seed || {}).map(([k, v]) => [k, clone(v)])),
      // `leases` maps a document path to the ms left on a lease another view holds.
      leases: new Map(Object.entries(held || {}).map(([p, ms]) =>
        [p, {holder: 'another-view', expires: Date.now() + ms}])),
      docSubs: new Map(), colSubs: new Map(), log: [], counter: {version: 0},
      // `setFailures` maps a document path to the codes its next sets are refused
      // with, one code per set, from any view. failSets() adds to it mid-test.
      setRefusals: new Map(Object.entries(setFailures || {}).map(([p, c]) => [p, c.slice()])),
      // `publishError` is a code every publish is refused with, or a list of codes
      // for the next publishes in turn (null lets one through), after which they land.
      publishRefusals: Array.isArray(publishError) ? publishError.slice() : [],
    };
  }
  const {store, leases, docSubs, colSubs, log, counter, setRefusals, publishRefusals} = shared;
  const view = window === window.top ? 'page' : window.name;
  const rings = [], missing = [];
  let failuresLeft = getFailures || 0;
  // `subscribeFailures` maps a path to the codes its next subscribes die with,
  // one code per subscribe, before any snapshot is delivered.
  const refusals = new Map(Object.entries(subscribeFailures || {}).map(([p, c]) => [p, c.slice()]));

  const fail = (code, message) => Object.assign(new Error(message), {code});
  const segments = p => {
    if (typeof p !== 'string' || !p) throw new TypeError('path must be a non-empty string');
    const s = p.split('/');
    if (s.some(x => !/^[A-Za-z0-9_\-.~:@+]{1,200}$/.test(x) || x === '.' || x === '..'))
      throw new TypeError('bad path segment in ' + p);
    return s;
  };
  const parentOf = p => p.split('/').slice(0, -1).join('/');

  // db.d.ts, ACCESS RULES: a rule covers its path and everything below it, the
  // deepest rule that sets a level wins, the root defaults to write "interact",
  // and a write below the minimum rejects invalid_argument.
  const writeLevel = p => {
    let depth = -1, write = 'interact';
    for (const r of rules){
      const d = r.path === '' ? 0 : r.path.split('/').length;
      if (r.write && d > depth && (r.path === '' || p === r.path || p.startsWith(r.path + '/'))){
        depth = d; write = r.write;
      }
    }
    return write;
  };
  const guard = (p, op) => {
    const needs = writeLevel(p);
    if (levels.indexOf(level) >= levels.indexOf(needs)) return;
    log.push({op: 'refused', path: p, code: 'invalid_argument', by: 'rules', view, at: Date.now()});
    throw fail('invalid_argument', op + ' on ' + p + ' needs ' + needs + ', this view is ' + level);
  };
  const isObject = v => !!v && typeof v === 'object' && !Array.isArray(v);
  // db.d.ts, update: nested objects merge recursively; anything else, arrays
  // included, replaces that field wholesale.
  const merge = (into, from) => {
    const out = {...into};
    for (const [k, v] of Object.entries(from)) out[k] = isObject(out[k]) && isObject(v) ? merge(out[k], v) : v;
    return out;
  };

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
    (docSubs.get(p) || []).slice().forEach(s => s.next(docSnap(p)));
    const c = parentOf(p);
    (colSubs.get(c) || []).slice().forEach(s => s.next(colSnap(c)));
  };
  // db.d.ts: a document body is at most 256 KiB serialized, and an oversize
  // write rejects invalid_argument.
  const MAX_BODY = 256 * 1024;
  const put = (p, data, who) => {
    if (data !== null && new TextEncoder().encode(JSON.stringify(data)).length > MAX_BODY)
      throw fail('invalid_argument', 'document body over 256 KiB');
    if (data === null) store.delete(p); else store.set(p, clone(data));
    log.push({op: data === null ? 'delete' : 'set', path: p, by: who, view, data: data && clone(data),
      at: Date.now()});
    setTimeout(() => notify(p), 0);
  };
  const subscribe = (map, key, next, error, snap) => {
    log.push({op: 'subscribe', path: key, view});
    if (typeof error !== 'function') missing.push('onSnapshot without an error callback: ' + key);
    const codes = refusals.get(key);
    if (codes && codes.length){
      const code = codes.shift();
      setTimeout(() => error && error({code, message: 'stubbed ' + code}), 0);
      return () => {};
    }
    const sub = {next, error};
    const list = map.get(key) || []; map.set(key, list); list.push(sub);
    setTimeout(() => list.includes(sub) && next(snap()), 0);
    return () => { const i = list.indexOf(sub); if (i >= 0) list.splice(i, 1); };
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
        log.push({op: 'get', path: p, view});
        const snap = docSnap(p);
        if (getDelay) await new Promise(r => setTimeout(r, getDelay));
        if (failuresLeft > 0){ failuresLeft--; throw fail('unavailable', 'stubbed unavailable'); }
        return snap;
      },
      set: async data => {
        guard(p, 'set');
        const refused = (setRefusals.get(p) || []).shift();
        if (refused){
          log.push({op: 'refused', path: p, code: refused, view, at: Date.now()});
          throw fail(refused, 'stubbed ' + refused);
        }
        if (!data || typeof data !== 'object' || Array.isArray(data))
          throw fail('invalid_argument', 'body must be an object');
        // setDelay holds a set the store accepts before it lands, so a refusal of
        // another set can arrive while this one is still on its way.
        if (setDelay){
          const body = clone(data);
          await new Promise(r => setTimeout(r, setDelay));
          return put(p, body, 'page');
        }
        put(p, data, 'page');
      },
      update: async data => {
        guard(p, 'update');
        if (!isObject(data)) throw fail('invalid_argument', 'body must be an object');
        if (!store.has(p)) throw fail('invalid_argument', 'update needs an existing document');
        put(p, merge(clone(store.get(p)), clone(data)), 'page');
      },
      delete: async () => { guard(p, 'delete'); put(p, null, 'page'); },
      // db.d.ts: set-if-not-busy, ttlMs clamped to [1000, 600000] with 0 or
      // absent meaning 30000, busy resolves {acquired: false} with only the
      // expiry, and a grant merges `data` into the body.
      acquire: async ({holder, ttlMs, data} = {}) => {
        if (typeof holder !== 'string' || !holder) throw fail('invalid_argument', 'holder is required');
        // Counted as a write to the document: a grant sets its version.
        guard(p, 'acquire');
        const now = Date.now(), lease = leases.get(p);
        const busy = !!lease && lease.expires > now && lease.holder !== holder;
        log.push({op: 'acquire', path: p, holder, view, acquired: !busy, at: now});
        if (busy) return {acquired: false, expiresAt: new Date(lease.expires).toISOString()};
        const expires = now + Math.min(Math.max(ttlMs || 30000, 1000), 600000);
        leases.set(p, {holder, expires});
        if (data) put(p, {...(store.get(p) || {}), ...clone(data)}, 'page');
        return {acquired: true, version: ++counter.version, holder,
          expiresAt: new Date(expires).toISOString()};
      },
      onSnapshot: (next, error) => subscribe(docSubs, p, next, error, () => docSnap(p)),
      collection: sub => colRef(p + '/' + sub),
    });
  };
  const colRef = c => {
    if (!(segments(c).length % 2)) throw new TypeError('collection path needs an odd number of segments: ' + c);
    return strict('collection', {
      path: c,
      doc: id => docRef(c + '/' + (id || Math.random().toString(36).slice(2, 12))),
      get: async () => colSnap(c),
      onSnapshot: (next, error) => subscribe(colSubs, c, next, error, () => colSnap(c)),
    });
  };

  const db = strict('db', {doc: docRef, collection: colRef});
  const artifact = strict('artifact', {
    publish: async files => {
      const code = Array.isArray(publishError) ? publishRefusals.shift() : publishError;
      if (code){
        log.push({op: 'publish refused', code, view, at: Date.now()});
        throw fail(code, 'stubbed ' + code);
      }
      if (typeof files === 'string' || !files || typeof files !== 'object')
        throw fail('invalid_content', 'the stub accepts only the files form; an html publish would reload the page');
      const ring = {files: Object.keys(files)};
      if (typeof files['doorbell.json'] === 'string') ring.doorbell = JSON.parse(files['doorbell.json']);
      rings.push(ring);
      log.push({op: 'publish', ring, view, at: Date.now()});
      return {version: 'v' + (++counter.version)};
    },
  });

  window.__desk = {
    store: () => Object.fromEntries([...store].map(([k, v]) => [k, clone(v)])),
    log: () => clone(log), rings: () => clone(rings), missing: () => missing.slice(),
    // A write from outside the page, as the session's write_db lands.
    write: (p, data) => put(p, data, 'session'),
    failSets: (p, codes) => {
      const queue = setRefusals.get(p) || [];
      setRefusals.set(p, queue);
      queue.push(...codes);
    },
    // Ends every live subscription on a document or collection path with one
    // terminal error, as db.d.ts describes: the error callback fires once and
    // the listener receives nothing more.
    kill: (p, code) => {
      for (const map of [docSubs, colSubs]){
        const list = map.get(p) || [];
        map.set(p, []);
        list.forEach(s => setTimeout(() => s.error && s.error({code, message: 'stubbed ' + code}), 0));
      }
    },
  };
  window.claude = strict('claude', {
    use: async name => (capabilities.includes(name) ? {db, artifact}[name] || null : null),
  });
}

// DESK_BROWSER=webkit runs a suite in WebKit, the engine every iPad browser uses.
export async function launch(){
  const name = process.env.DESK_BROWSER || 'chromium';
  const type = {chromium, webkit}[name];
  if (!type) throw new Error('DESK_BROWSER must be chromium or webkit, not ' + name);
  return type.launch();
}

// The host wraps the file in this skeleton.
const skeleton = html => '<!doctype html><html><head>'
  + '<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
  + '</head><body>' + html;

// `capabilities` is what this view is granted: ['db', 'artifact'], ['db'] for a
// view that cannot ring, [] for one that cannot reach the store. `declared` is the
// capabilities object build_desk.py printed, whose db rules the stub enforces.
function stubOptions({seed = {}, capabilities = ['db', 'artifact'], publishError = null,
    getDelay = 0, getFailures = 0, leases = {}, subscribeFailures = {}, setFailures = {}, setDelay = 0,
    level = 'interact'}, declared){
  const unknown = capabilities.filter(c => !['db', 'artifact'].includes(c));
  if (unknown.length) throw new Error('the stub grants only db and artifact, not ' + unknown);
  const codes = publishError === null ? [] : [].concat(publishError).filter(c => c !== null);
  const bad = codes.filter(c => !PUBLISH_CODES.includes(c));
  if (bad.length) throw new Error('not an artifact.d.ts publish code: ' + bad);
  if (!LEVELS.includes(level)) throw new Error('level must be one of ' + LEVELS);
  const rules = (declared.db && declared.db.rules) || [];
  for (const r of rules){
    const extra = Object.keys(r).filter(k => k !== 'path' && k !== 'write');
    if (extra.length || r.path.includes('{self}') || !LEVELS.includes(r.write))
      throw new Error('the stub enforces only path and write levels, not ' + JSON.stringify(r));
  }
  return {seed, capabilities, publishError, getDelay, getFailures, leases, subscribeFailures, setFailures,
    setDelay, rules, level, levels: LEVELS};
}

// Everything a test does to one view. `frame` is a Page for a lone desk, or the
// view's Frame in openPair(); both answer the calls the tests make.
function deskFor(frame, {page, errors, pr, html, close}){
  const desk = {
    page: frame, errors, pr, html,
    store: () => frame.evaluate(() => window.__desk.store()),
    log: () => frame.evaluate(() => window.__desk.log()),
    rings: () => frame.evaluate(() => window.__desk.rings()),
    missing: () => frame.evaluate(() => window.__desk.missing()),
    write: (p, v) => frame.evaluate(([p, v]) => window.__desk.write(p, v), [p, v]),
    failSets: (p, codes) => frame.evaluate(([p, c]) => window.__desk.failSets(p, c), [p, codes]),
    // Loads this view again, as another view's ring does on the host. In
    // openPair() the store is the top window's, so it survives the reload.
    reload: async () => {
      await frame.goto(frame.url());
      await frame.waitForFunction(() => !!window.__desk);
    },
    kill: (p, code = 'unavailable') => frame.evaluate(([p, c]) => window.__desk.kill(p, c), [p, code]),
    subscribes: async p => (await desk.log()).filter(e => e.op === 'subscribe' && e.path === p).length,
    reply: (turn, text, status = 'done') =>
      desk.write(pr + '/replies/' + turn, {turn, status, text, at: new Date().toISOString()}),
    presence: (id, resume) => desk.write(pr + '/presence/' + id, resume ? {resume} : {}),
    context: (name, v) => desk.write(pr + '/context/' + name, v),
    document: (id, name, text, extra = {}) => desk.write(pr + '/documents/' + id, {name, text, ...extra}),
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
    browserPage: page,
    close,
  };
  return desk;
}

// Opens a desk. `seed` is the store as it stands before the page loads.
// `context` is passed to browser.newContext: {hasTouch: true} is a touch screen,
// and makes (pointer: coarse) match in both Chromium and WebKit; {colorScheme:
// 'dark'} is a reviewer in dark mode. `init` is a function run in the page before
// any of its scripts, after the stub, for a test that wraps a browser API to
// count what the page does with it. `clock: true` installs Playwright's clock, so
// a test can fastForward past a wait the page measures in minutes.
export async function open(browser, options = {}){
  const data = options.data || payload();
  const {html, capabilities: declared} = built(data, options.title);
  const stub = stubOptions(options, declared);
  const context = await browser.newContext(options.context || {});
  const page = await context.newPage();
  const errors = [];
  page.on('pageerror', e => errors.push(e.message));
  await page.addInitScript(installStub, stub);
  if (options.init) await page.addInitScript(options.init);
  if (options.clock) await page.clock.install();
  // Nothing leaves the machine: fonts, highlight.js and mermaid are refused, which
  // the page is built to survive (it loses colour and drawings, nothing else).
  await page.route('**/*', route => {
    if (route.request().url() === ORIGIN + '/')
      return route.fulfill({contentType: 'text/html', body: skeleton(html)});
    return route.abort();
  });
  await page.goto(ORIGIN + '/');
  return deskFor(page, {page, errors, pr: 'review/pr-' + data.number, html,
    close: () => context.close()});
}

// Two open views of one desk, as a laptop tab and a tablet, sharing one store.
// Each is a frame of one page, so the stub's store is a single object both reach.
// Neither reloads when the other rings: that is the case where nothing but the
// store keeps them in step (the doorbell's reload fails, or cannot publish).
export async function openPair(browser, options = {}){
  const data = options.data || payload();
  const {html, capabilities: declared} = built(data, options.title);
  const stub = stubOptions(options, declared);
  // Side by side and wholly inside the viewport: the panel button is fixed to
  // its frame's corner, and a frame scrolled out of view cannot be clicked.
  const context = await browser.newContext({viewport: {width: 2000, height: 720}});
  const page = await context.newPage();
  const errors = [];
  page.on('pageerror', e => errors.push(e.message));
  await page.addInitScript(installStub, stub);
  // As in open(): run in every frame, both views, before the page's scripts.
  if (options.init) await page.addInitScript(options.init);
  await page.route('**/*', route => {
    const url = route.request().url();
    const frame = 'style="float:left;border:0;width:1000px;height:720px"';
    if (url === ORIGIN + '/') return route.fulfill({contentType: 'text/html',
      body: '<!doctype html><html><body style="margin:0;overflow:hidden">'
        + '<iframe name="view-a" src="/a" ' + frame + '></iframe>'
        + '<iframe name="view-b" src="/b" ' + frame + '></iframe></body></html>'});
    if (url === ORIGIN + '/a' || url === ORIGIN + '/b')
      return route.fulfill({contentType: 'text/html', body: skeleton(html)});
    return route.abort();
  });
  await page.goto(ORIGIN + '/');
  const frames = ['view-a', 'view-b'].map(name => page.frame({name}));
  await Promise.all(frames.map(f => f.waitForFunction(() => !!window.__desk)));
  const close = () => context.close();
  const pr = 'review/pr-' + data.number;
  return frames.map(f => deskFor(f, {page, errors, pr, html, close}));
}
