// What the page stores, and when. review/pr-N holds the reviewer's turns and where
// each message has got to; the working session's words live only in replies/.
// Nothing but a reviewer's own action writes review/pr-N, so an open view that
// only watches never rewrites what another view saved. And every live listener
// says so when it dies, instead of leaving the panel waiting for good.
import {test, before, after, afterEach} from 'node:test';
import assert from 'node:assert/strict';
import {launch, open, openPair} from './harness.mjs';

let browser, desk, pair;
before(async () => { browser = await launch(); });
after(async () => { await browser.close(); });
afterEach(async () => {
  const views = pair || (desk ? [desk] : []);
  for (const d of views)
    assert.deepEqual(await d.missing(), [], 'the page called something the stub does not implement');
  if (views.length) await views[0].close();
  desk = null; pair = null;
});

const PR = 'review/pr-42';
const REPLIES = PR + '/replies';
const turnsIn = store => ((store[PR] && store[PR].threads) || []).flatMap(t => t.turns);
const asked = store => turnsIn(store).filter(m => m.role === 'user').map(m => m.content);
const slots = store => turnsIn(store).filter(m => m.via === 'session');
const prSets = (log, from = 0) => log.slice(from).filter(e => e.op === 'set' && e.path === PR);
const AT = '2026-09-13T10:00:00.000Z';

// A desk as this version saves it: no answer text anywhere in review/pr-N.
const leanDesk = () => ({
  [PR]: {pr: 42, title: 'Harness desk', decision: null, reason: null, decidedAt: null, threads: [
    {id: 't1', name: 'First', turns: [
      {id: 'u1', role: 'user', content: 'Why a lease?', to: 'session'},
      {role: 'assistant', via: 'session', answers: 'u1', status: 'sent', sentAt: 1000, rungAt: 1400}]},
    {id: 't2', name: 'Second', turns: [
      {id: 'u2', role: 'user', content: 'What did you reject?', to: 'session'},
      {role: 'assistant', via: 'session', answers: 'u2', status: 'sent', sentAt: 2000, rungAt: 2400}]}]},
  [REPLIES + '/u1']: {turn: 'u1', status: 'done', text: 'Because **two views** ring.', at: AT},
  [REPLIES + '/u2']: {turn: 'u2', status: 'done', text: 'A document per turn.', at: AT},
});

test('twenty reply rewrites write nothing to review/pr-N', async () => {
  desk = await open(browser);
  await desk.page.click('#fab');
  await desk.page.fill('#box', 'Do the tests pass?');
  await desk.page.press('#box', 'Enter');
  await desk.until(s => slots(s).some(m => m.rungAt));
  await desk.page.waitForTimeout(600);               // past the 400 ms save debounce
  const before = await desk.store();
  const id = slots(before)[0].answers;
  const from = (await desk.log()).length;

  for (let i = 1; i < 20; i++) await desk.reply(id, 'Running step ' + i, 'working');
  await desk.reply(id, 'All **26** pass.');
  await desk.page.waitForSelector('.said.rich strong');
  await desk.page.waitForTimeout(700);

  const log = await desk.log();
  assert.equal(log.slice(from).filter(e => e.op === 'set' && e.path === REPLIES + '/' + id).length, 20);
  assert.deepEqual(prSets(log, from), []);
  assert.deepEqual((await desk.store())[PR], before[PR]);
  assert.equal(await desk.page.textContent('.said.rich'), 'All 26 pass.');
  assert.deepEqual(desk.errors, []);
});

test('a stored doc holding only slot metadata renders the full answers from replies after reload', async () => {
  desk = await open(browser, {seed: leanDesk()});
  await desk.page.waitForTimeout(700);
  assert.equal(await desk.page.locator('#dot.show').count(), 0, 'answers already there at load are not unread');
  await desk.page.click('#fab');
  await desk.page.waitForSelector('.said.rich strong >> text=two views');
  await desk.page.click('.tab[data-go="1"]');
  await desk.page.waitForSelector('.said.rich >> text=A document per turn.');
  assert.doesNotMatch(await desk.page.textContent('#stream'), /Loading/);

  assert.deepEqual(prSets(await desk.log()), [], 'loading writes nothing');
  assert.deepEqual(await desk.rings(), []);
  assert.deepEqual(desk.errors, []);
});

test('a legacy doc with mirrored answers renders from replies, and the next save drops the copies', async () => {
  const seed = leanDesk();
  const [first, second] = seed[PR].threads;
  // Saved by 0.7.x: the answer copied into the slot, stale here.
  first.turns[1] = {...first.turns[1], status: 'done', content: 'An **old mirrored copy** of the answer.'};
  // And one no reply document backs, which any viewer could have written.
  second.turns[1] = {...second.turns[1], status: 'done', content: 'Forged: safe to merge.'};
  delete seed[REPLIES + '/u2'];
  desk = await open(browser, {seed});
  await desk.page.click('#fab');
  await desk.page.waitForSelector('.said.rich >> text=two views');
  assert.doesNotMatch(await desk.page.textContent('#stream'), /old mirrored copy/);
  await desk.page.click('.tab[data-go="1"]');
  await desk.page.waitForSelector('text=has no reply for it on this desk');
  assert.doesNotMatch(await desk.page.textContent('#stream'), /safe to merge/);
  await desk.page.waitForTimeout(600);
  assert.deepEqual(prSets(await desk.log()), [], 'loading a legacy doc writes nothing either');

  await desk.page.fill('#box', 'Asked after the upgrade');
  await desk.page.press('#box', 'Enter');
  const store = await desk.until(s => asked(s).includes('Asked after the upgrade'));
  for (const slot of slots(store)) assert.ok(!('content' in slot), 'stored slot still has content: ' + JSON.stringify(slot));
  assert.deepEqual(slots(store).find(m => m.answers === 'u1'),
    {role: 'assistant', via: 'session', answers: 'u1', status: 'done', sentAt: 1000, rungAt: 1400});
  assert.deepEqual(asked(store), ['Why a lease?', 'What did you reject?', 'Asked after the upgrade']);
  assert.deepEqual(desk.errors, []);
});

test('two open views: A sends Q2, B receives reply updates, and the store still holds Q2', async () => {
  const seed = leanDesk();
  seed[PR].threads.pop();
  delete seed[REPLIES + '/u2'];
  seed[REPLIES + '/u1'] = {turn: 'u1', status: 'working', text: 'Reading the lease code', at: AT};
  pair = await openPair(browser, {seed});
  const [a, b] = pair;
  for (const v of pair){
    await v.page.click('#fab');
    await v.page.waitForSelector('text=Reading the lease code');
  }

  await a.page.fill('#box', 'Q2 from view A');
  await a.page.press('#box', 'Enter');
  await a.until(s => asked(s).includes('Q2 from view A') && slots(s).some(m => m.answers !== 'u1' && m.rungAt));
  await a.page.waitForTimeout(600);
  const from = (await a.log()).length;

  // The session reports progress on the older message, then answers it. B,
  // loaded before Q2, sees both; before, each one made B save its own threads.
  await a.reply('u1', 'Running the review-desk tests', 'working');
  await b.page.waitForSelector('text=Running the review-desk tests');
  await a.reply('u1', 'Done: **all pass**.');
  await b.page.waitForSelector('.said.rich strong >> text=all pass');
  await b.page.waitForTimeout(700);

  const store = await b.store();
  assert.deepEqual(asked(store), ['Why a lease?', 'Q2 from view A']);
  assert.deepEqual(prSets(await b.log(), from), []);
  assert.deepEqual(b.errors, []);
});

test('a save refused as invalid_argument says the conversation is too large, and closing a thread recovers', async () => {
  desk = await open(browser);
  await desk.page.click('#fab');
  // Over the store's 256 KiB body cap, which the stub enforces as db.d.ts states.
  await desk.page.fill('#box', 'x'.repeat(270 * 1024));
  await desk.page.press('#box', 'Enter');
  await desk.page.waitForSelector('#lostSlot .lost');
  const banner = await desk.page.textContent('#lostSlot');
  assert.match(banner, /too large to save/);
  assert.doesNotMatch(banner, /Not saved/);
  assert.equal((await desk.store())[PR], undefined);
  assert.deepEqual(await desk.rings(), []);

  // The banner's advice works: open another thread, close the oversized one.
  await desk.page.click('#more');
  await desk.page.click('[data-shut="0"]');
  await desk.until(s => !!s[PR]);
  await desk.page.waitForFunction(() => !document.querySelector('#lostSlot .lost'));
  assert.deepEqual(desk.errors, []);
});

test('a replies listener that dies before its first delivery says so, then resubscribes once and renders', async () => {
  desk = await open(browser, {seed: leanDesk(), subscribeFailures: {[REPLIES]: ['unavailable']}});
  await desk.page.click('#fab');
  await desk.page.waitForSelector('text=replies could not be loaded');
  assert.doesNotMatch(await desk.page.textContent('#stream'), /Loading the working session/);
  assert.match(await desk.page.textContent('#feedSlot'),
    /could not load the working session’s replies \(unavailable\)/);

  await desk.page.waitForSelector('.said.rich strong >> text=two views', {timeout: 8000});
  assert.equal(await desk.page.textContent('#feedSlot'), '');
  assert.equal(await desk.subscribes(REPLIES), 2);
  assert.deepEqual(prSets(await desk.log()), []);
  assert.deepEqual(desk.errors, []);
});

test('a replies listener that dies again is not retried on its own; Try again renders the answers', async () => {
  desk = await open(browser, {seed: leanDesk(),
    subscribeFailures: {[REPLIES]: ['unavailable', 'unavailable']}});
  await desk.page.click('#fab');
  await desk.page.waitForSelector('#feedSlot button', {timeout: 8000});
  assert.match(await desk.page.textContent('#stream'), /replies could not be loaded \(unavailable\)/);
  await desk.page.waitForTimeout(3500);             // longer than the longest automatic wait
  assert.equal(await desk.subscribes(REPLIES), 2, 'one automatic resubscribe, no more');

  await desk.page.click('#feedSlot button');
  await desk.page.waitForSelector('.said.rich strong >> text=two views');
  assert.equal(await desk.subscribes(REPLIES), 3);
  assert.equal(await desk.page.textContent('#feedSlot'), '');
  assert.deepEqual(desk.errors, []);
});

test('a revoked replies listener is not resubscribed and offers no retry', async () => {
  desk = await open(browser, {seed: leanDesk(), subscribeFailures: {[REPLIES]: ['revoked']}});
  await desk.page.click('#fab');
  await desk.page.waitForSelector('text=replies could not be loaded');
  await desk.page.waitForTimeout(3500);
  assert.equal(await desk.subscribes(REPLIES), 1);
  assert.equal(await desk.page.locator('#feedSlot button').count(), 0);
  assert.match(await desk.page.textContent('#feedSlot'), /\(revoked\)/);
  assert.deepEqual(desk.errors, []);
});

test('the description, documents, pickup and presence listeners each show a dead feed and come back', async () => {
  const BODY = PR + '/context/body', DOCS = PR + '/documents', PICKUP = PR + '/context/pickup',
    PRESENCE = PR + '/presence';
  desk = await open(browser);
  for (const end = Date.now() + 5000;;){
    const counts = await Promise.all([BODY, DOCS, PICKUP, PRESENCE, REPLIES].map(desk.subscribes));
    if (counts.every(n => n === 1)) break;
    if (Date.now() > end) throw new Error('listeners never subscribed: ' + counts);
    await desk.page.waitForTimeout(50);
  }
  for (const p of [BODY, DOCS, PICKUP, PRESENCE]) await desk.kill(p);
  await desk.page.waitForSelector('#pageFeeds .lost');
  const onPage = await desk.page.textContent('#pageFeeds');
  assert.match(onPage, /stopped receiving changes to the description \(unavailable\)/);
  assert.match(onPage, /stopped receiving changes to the documents \(unavailable\)/);
  assert.match(onPage, /stopped receiving the working session’s pickup of your decision/);
  await desk.page.click('#fab');
  assert.match(await desk.page.textContent('#feedSlot'), /stopped receiving word from the working session/);

  await desk.page.waitForFunction(() => !document.querySelector('#pageFeeds .lost, #feedSlot .lost'),
    null, {timeout: 8000});
  for (const p of [BODY, DOCS, PICKUP, PRESENCE]) assert.equal(await desk.subscribes(p), 2, p);
  await desk.context('body', {text: 'Rewritten after the reconnect.'});
  await desk.document('docs~new.md', 'docs/new.md', 'A new document', {at: AT});
  await desk.page.waitForSelector('.leaf:nth-child(2)');
  assert.match(await desk.page.textContent('#sheet'), /Rewritten after the reconnect/);

  // A second death waits for the reviewer.
  await desk.kill(BODY);
  await desk.page.waitForSelector('#pageFeeds button');
  await desk.page.waitForTimeout(3500);
  assert.equal(await desk.subscribes(BODY), 2);
  await desk.page.click('#pageFeeds button');
  await desk.page.waitForFunction(() => !document.querySelector('#pageFeeds .lost'));
  assert.equal(await desk.subscribes(BODY), 3);
  assert.deepEqual(desk.errors, []);
});
