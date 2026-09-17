// Behaviour the desk has today, locked in before later changes touch it.
import {test, before, after, afterEach} from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import {launch, open, payload, approve} from './harness.mjs';

let browser, desk;
before(async () => { browser = await launch(); });
after(async () => { await browser.close(); });
afterEach(async () => {
  if (!desk) return;
  assert.deepEqual(await desk.missing(), [], 'the page called something the stub does not implement');
  await desk.close();
  desk = null;
});

const turnsIn = (store, pr) => ((store[pr] && store[pr].threads) || []).flatMap(t => t.turns);

async function typeAndSend(d, text){
  await d.page.click('#fab');
  await d.page.fill('#box', text);
  await d.page.press('#box', 'Enter');
}

test('the stub hands out deep-frozen snapshots', async () => {
  desk = await open(browser, {seed: {'review/pr-42': {threads: [{id: 't1', turns: [{id: 'a'}]}]}}});
  const frozen = await desk.page.evaluate(async () => {
    const db = await claude.use('db');
    const d = (await db.doc('review/pr-42').get()).data();
    return [Object.isFrozen(d), Object.isFrozen(d.threads), Object.isFrozen(d.threads[0].turns),
            Object.isFrozen(d.threads[0].turns[0])];
  });
  assert.deepEqual(frozen, [true, true, true, true]);
});

// The paths build_desk.py declares owner-only are the session's. A page write to
// one is what db.d.ts says the host does with it: rejected invalid_argument.
test('a page write to a session path is refused under the desk rules, and the page save is not', async () => {
  const tryWrites = d => d.page.evaluate(async paths => {
    const db = await claude.use('db');
    const out = {};
    for (const p of paths){
      try { await db.doc(p).set({decision: 'approved', text: 'written by the page'}); out[p] = 'stored'; }
      catch (e){ out[p] = e.code; }
    }
    return out;
  }, ['review/pr-42/context/pickup', 'review/pr-42/replies/m1', 'review/pr-42/presence/1700000000',
    'review/pr-42/documents/d1']);

  desk = await open(browser);
  await desk.page.waitForFunction('restore === "done"');
  assert.deepEqual(Object.values(await tryWrites(desk)), Array(4).fill('invalid_argument'));
  await approve(desk);
  const store = await desk.until((s, pr) => s[pr] && s[pr].decision === 'approved', desk.pr);
  assert.deepEqual(Object.keys(store), [desk.pr]);
  await desk.close();

  // The rules never limit the owner, so the same writes land from an owner's view.
  desk = await open(browser, {level: 'owner'});
  await desk.page.waitForFunction('restore === "done"');
  assert.deepEqual(Object.values(await tryWrites(desk)), Array(4).fill('stored'));
});

test('the stub update merges nested objects and replaces arrays, as db.d.ts says', async () => {
  desk = await open(browser);
  const doc = await desk.page.evaluate(async () => {
    const ref = (await claude.use('db')).doc('review/pr-42');
    await ref.set({a: {x: 1, y: {z: 2}}, list: [1, 2], keep: true});
    await ref.update({a: {y: {w: 3}}, list: [3]});
    return (await ref.get()).data();
  });
  assert.deepEqual(doc, {a: {x: 1, y: {z: 2, w: 3}}, list: [3], keep: true});
});

test('a view granted db but not artifact says it cannot ring, and a sent message is still stored', async () => {
  desk = await open(browser, {capabilities: ['db']});
  await desk.page.click('#fab');
  await desk.page.waitForSelector('#aloneSlot >> text=This view cannot ring the working session');
  await desk.page.fill('#box', 'Stored without a bell');
  await desk.page.press('#box', 'Enter');
  await desk.until((s, pr) => turnsIn(s, pr).some(m => m.content === 'Stored without a bell'), desk.pr);
  await desk.page.waitForSelector('#stream >> text=could not ring the working session (unavailable)');
  assert.equal(await desk.page.locator('#check').count(), 0, 'no Check without a bell');
  assert.equal(await desk.page.textContent('#lostSlot'), '');
  assert.deepEqual(await desk.rings(), []);
  assert.deepEqual(desk.errors, []);
});

test('a view granted nothing says it cannot reach the store, and a sent message says it will not arrive', async () => {
  desk = await open(browser, {capabilities: []});
  await desk.page.click('#fab');
  await desk.page.waitForSelector('#lostSlot >> text=this view cannot reach the store');
  assert.equal(await desk.page.textContent('#aloneSlot'), '');
  await desk.page.fill('#box', 'Nowhere to go');
  await desk.page.press('#box', 'Enter');
  await desk.page.waitForSelector('#stream >> text=This view cannot save messages');
  // The property, not visibility: the host's reset hides [hidden], the harness
  // skeleton does not carry it, and .presence sets its own display.
  assert.equal(await desk.page.$eval('#presence', el => el.hidden), true);
  assert.deepEqual(await desk.store(), {});
  assert.deepEqual(await desk.rings(), []);
  assert.deepEqual(desk.errors, []);
});

test('carried text containing </script> loads the desk', async () => {
  const data = payload({
    title: 'Quotes a </script> tag',
    body: 'Mentions `</script>` and the `/*PAYLOAD*/` marker.',
    documents: [
      {name: 'templates/page.html', text: '<script>x()</script>\n'},
      {name: 'docs/old.md', text: '<!--<script>\nnot closed\n'},
      {name: 'docs/marker.md', text: 'const DATA = /*PAYLOAD*/;\nline sep\n'},
    ],
  });
  desk = await open(browser, {data, title: 'Script Tag Review'});
  // A cut-short script never draws the tabs; let the page errors say why.
  await desk.page.waitForSelector('.leaf:nth-child(4)', {timeout: 3000}).catch(() => {});
  assert.deepEqual(desk.errors, []);
  assert.equal(await desk.page.textContent('#title'), data.title);
  assert.equal(await desk.page.title(), 'Script Tag Review');
  assert.equal(await desk.page.locator('.leaf').count(), 4);
  await desk.page.click('.leaf:nth-child(2)');
  assert.equal(await desk.page.textContent('#sheet pre code'), '<script>x()</script>\n');
});

test('restoring frozen threads and then sending reaches the store', async () => {
  const seed = {'review/pr-42': {pr: 42, threads: [{id: 't1', name: 'Earlier',
    turns: [{id: 'm-old', role: 'user', content: 'Asked before the reload', to: 'session'}]}]}};
  desk = await open(browser, {seed});
  await desk.page.click('#fab');
  await desk.page.waitForSelector('text=Asked before the reload');
  await desk.page.fill('#box', 'Asked after the reload');
  await desk.page.click('#send');
  await desk.until((s, pr) => ((s[pr] && s[pr].threads) || []).some(t =>
    t.turns.some(m => m.content === 'Asked after the reload')), desk.pr);
  const turns = turnsIn(await desk.store(), desk.pr);
  assert.deepEqual(turns.filter(m => m.role === 'user').map(m => m.content),
    ['Asked before the reload', 'Asked after the reload']);
  assert.deepEqual(desk.errors, []);
  assert.equal(await desk.page.textContent('#lostSlot'), '');
});

test('Enter sends and clears the box', async () => {
  desk = await open(browser);
  await typeAndSend(desk, 'Why this way?');
  await desk.until((s, pr) => !!s[pr], desk.pr);
  assert.equal(await desk.page.inputValue('#box'), '');
  const sent = turnsIn(await desk.store(), desk.pr).filter(m => m.role === 'user');
  assert.deepEqual(sent.map(m => m.content), ['Why this way?']);
});

test('Shift+Enter inserts a newline and sends nothing', async () => {
  desk = await open(browser);
  await desk.page.click('#fab');
  await desk.page.click('#box');
  await desk.page.keyboard.type('line one');
  await desk.page.keyboard.press('Shift+Enter');
  await desk.page.keyboard.type('line two');
  await desk.page.waitForTimeout(600);             // past the 400 ms save debounce
  assert.equal(await desk.page.inputValue('#box'), 'line one\nline two');
  assert.deepEqual(await desk.store(), {});
  assert.deepEqual(await desk.rings(), []);
});

test('Enter while an input method is composing does nothing', async () => {
  desk = await open(browser);
  await desk.page.click('#fab');
  await desk.page.fill('#box', 'かな');
  // Playwright's keyboard cannot set isComposing, so the events are dispatched.
  // The second, identical but not composing, shows a dispatched Enter does send.
  const dispatch = composing => desk.page.$eval('#box', (el, composing) => {
    const e = new KeyboardEvent('keydown', {key: 'Enter', isComposing: composing,
      bubbles: true, cancelable: true});
    el.dispatchEvent(e);
    return e.defaultPrevented;
  }, composing);
  assert.equal(await dispatch(true), false);
  await desk.page.waitForTimeout(600);
  assert.equal(await desk.page.inputValue('#box'), 'かな');
  assert.deepEqual(await desk.store(), {});
  assert.equal(await dispatch(false), true);
  await desk.until((s, pr) => !!s[pr], desk.pr);
});

test('a send rings kind message, after the message is stored', async () => {
  desk = await open(browser);
  await typeAndSend(desk, 'Ring for this');
  await desk.page.waitForFunction(() => window.__desk.rings().length === 1);
  const [ring] = await desk.rings();
  const turn = turnsIn(await desk.store(), desk.pr).find(m => m.content === 'Ring for this');
  assert.deepEqual(ring.files, ['doorbell.json']);
  assert.equal(ring.doorbell.kind, 'message');
  assert.equal(ring.doorbell.turn, turn.id);
  assert.equal(ring.doorbell.pr, 42);
  const log = await desk.log();
  const stored = log.findIndex(e => e.op === 'set' && e.path === desk.pr
    && e.data.threads.some(t => t.turns.some(m => m.id === turn.id)));
  assert.ok(stored >= 0 && stored < log.findIndex(e => e.op === 'publish'));
});

test('Approve rings kind decision, after the decision is stored', async () => {
  desk = await open(browser);
  await approve(desk);
  await desk.page.waitForFunction(() => window.__desk.rings().length === 1);
  const [ring] = await desk.rings();
  const doc = (await desk.store())[desk.pr];
  assert.equal(ring.doorbell.kind, 'decision');
  assert.equal(ring.doorbell.decision, 'approved');
  assert.equal(ring.doorbell.decidedAt, doc.decidedAt);
  assert.equal(doc.decision, 'approved');
  const log = await desk.log();
  const stored = log.findIndex(e => e.op === 'set' && e.path === desk.pr && e.data.decision === 'approved');
  assert.ok(stored >= 0 && stored < log.findIndex(e => e.op === 'publish'));
  assert.deepEqual(desk.errors, []);
});

test('a session reply lands in the thread', async () => {
  desk = await open(browser);
  await typeAndSend(desk, 'Answer me');
  await desk.page.waitForFunction(() => window.__desk.rings().length === 1);
  const turn = turnsIn(await desk.store(), desk.pr).find(m => m.content === 'Answer me');
  await desk.reply(turn.id, 'Because **reasons**.');
  await desk.page.waitForSelector('.said.rich strong');
  assert.equal(await desk.page.textContent('.said.rich'), 'Because reasons.');
  assert.deepEqual(desk.errors, []);
});

test('the page says which review-desk built it, in the footer and in what it writes', async () => {
  // A desk is a published artifact and its page stays whatever version
  // published it. Without this the only way to tell an old desk from a new one
  // was to notice a behaviour it did not have.
  const declared = JSON.parse(fs.readFileSync(
    new URL('../../.claude-plugin/plugin.json', import.meta.url), 'utf8')).version;
  desk = await open(browser);
  await desk.page.waitForFunction('restore === "done"', null, {timeout: 5000});
  assert.equal(await desk.page.textContent('#built'), declared);
  assert.match(await desk.page.textContent('footer'), /review desk \d+\.\d+\.\d+/);

  await desk.page.click('#fab');
  await desk.page.fill('#box', 'Which version is this desk?');
  await desk.page.press('#box', 'Enter');
  const doc = (await desk.until(s => s[desk.pr] && (s[desk.pr].threads || [])
    .some(t => t.turns.some(m => m.content === 'Which version is this desk?'))))[desk.pr];
  assert.equal(doc.page, declared, 'every save records the page that made it');
});
