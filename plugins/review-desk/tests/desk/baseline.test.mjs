// Behaviour the desk has today, locked in before later changes touch it.
import {test, before, after, afterEach} from 'node:test';
import assert from 'node:assert/strict';
import {launch, open, payload} from './harness.mjs';

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
  await desk.page.click('#ok');
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
