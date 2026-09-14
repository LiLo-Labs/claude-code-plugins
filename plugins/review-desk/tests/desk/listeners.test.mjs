// The live listeners take whatever rows the store holds. A malformed one must be
// skipped, not thrown on: a throw inside a snapshot callback is uncaught, and
// the ones here broke every later repaint until the row was deleted.
import {test, before, after, afterEach} from 'node:test';
import assert from 'node:assert/strict';
import {launch, open, openPair, payload} from './harness.mjs';

let browser, desk;
before(async () => { browser = await launch(); });
after(async () => { await browser.close(); });
afterEach(async () => {
  if (!desk) return;
  assert.deepEqual(await desk.missing(), [], 'the page called something the stub does not implement');
  await desk.close();
  desk = null;
});

const PR = 'review/pr-42';
const AT = '2026-09-13T10:00:00.000Z';
const settle = (ms = 300) => desk.page.waitForTimeout(ms);
const presenceLine = () => desk.page.textContent('#presence > span');
const fresh = () => desk.page.locator('.leaf .fresh.show').count();
const sheetOf = async n => { await desk.page.click('.leaf:nth-child(' + n + ')'); return desk.page.textContent('#sheet'); };

// Each listener test runs twice: with one definitive first snapshot, and with an
// empty fromCache page before it, which db.d.ts says a subscription may send first.
const both = (title, fn) => {
  test(title, () => fn({}));
  test(title + ' (first page from cache)', () => fn({firstFromCache: true}));
};

both('presence ids out of range or not numbers break no redraw', async cache => {
  // Seeded, so they arrive in the first snapshot, which times stamps by name.
  const seed = {[PR + '/presence/9999999999999']: {}, [PR + '/presence/abc']: {},
                [PR + '/presence/-1']: {}};
  desk = await open(browser, {seed, ...cache});
  await desk.page.click('#fab');
  await settle();
  assert.deepEqual(desk.errors, []);
  assert.equal(await presenceLine(), 'The working session has not answered on this desk yet.');

  // Every draw() ends in drawPresence: a new thread, and a send, both redraw.
  await desk.page.click('#more');
  await desk.page.fill('#box', 'Still drawing?');
  await desk.page.press('#box', 'Enter');
  await desk.until(s => (s[PR] && s[PR].threads || []).some(t => t.turns.some(m => m.content === 'Still drawing?')));
  assert.deepEqual(desk.errors, []);
  assert.ok(await desk.page.isVisible('#presence > span'));

  // The same ids arriving live, then a real stamp: the line still follows.
  for (const id of ['99999999999999', 'xyz', '-5']) await desk.presence(id);
  await settle();
  assert.deepEqual(desk.errors, []);
  assert.match(await presenceLine(), /^Working session last answered/);
  await desk.page.click('#more');
  await desk.presence(Math.floor(Date.now() / 1000) + '-0ccc');
  await settle();
  assert.match(await presenceLine(), /^Working session last answered at /);
  assert.deepEqual(desk.errors, []);
});

both('document rows without a string name or text are skipped, and the leaves still switch', async cache => {
  const data = payload({documents: [{name: 'docs/a.md', text: 'Alpha text'},
    {text: 'carried with no name'}, {name: 'docs/b.md', text: 'Beta text'}]});
  desk = await open(browser, {data, ...cache});
  await desk.page.waitForSelector('.leaf:nth-child(3)');
  await desk.write(PR + '/documents/noname', {text: 'x'});
  await desk.write(PR + '/documents/numeric', {name: 'docs/c.md', text: 42});
  await desk.write(PR + '/documents/nulled', {name: null, text: null});
  await settle();
  assert.deepEqual(desk.errors, []);
  assert.equal(await desk.page.locator('.leaf').count(), 3);
  assert.match(await sheetOf(2), /Alpha text/);
  assert.match(await sheetOf(3), /Beta text/);
  assert.match(await sheetOf(1), /A plain description/);

  // A well-formed row after them still lands.
  await desk.document('docs~b.md', 'docs/b.md', 'Beta revised', {at: new Date().toISOString()});
  await settle();
  assert.match(await sheetOf(3), /Beta revised/);
  assert.deepEqual(desk.errors, []);
});

both('two rows for one document show the newer, and an identical snapshot flags nothing', async cache => {
  const T1 = '2026-09-13T10:00:00.000Z', T2 = '2026-09-13T11:00:00.000Z';
  const data = payload({documents: [{name: 'docs/design.md', text: 'rev 1'}]});
  const seed = {[PR + '/documents/design']: {name: 'docs/design.md', text: 'rev 2', at: T1},
                [PR + '/documents/docs~design.md']: {name: 'docs/design.md', text: 'rev 3', at: T2}};
  desk = await open(browser, {data, seed, ...cache});
  await desk.page.waitForSelector('.leaf .fresh.show');
  assert.equal(await desk.page.locator('.leaf').count(), 2);
  assert.match(await sheetOf(2), /rev 3/);

  // Opening the tab cleared the first snapshot's flag. The same rows delivered
  // again change nothing, so nothing is flagged again; before, the two texts
  // were applied in turn and the tab was flagged on every snapshot.
  await desk.page.waitForFunction(() => !document.querySelector('.leaf .fresh.show'), null, {timeout: 7000});
  await desk.document('docs~design.md', 'docs/design.md', 'rev 3', {at: T2});
  await settle(500);
  assert.equal(await fresh(), 0);
  assert.match(await desk.page.textContent('#sheet'), /rev 3/);
  assert.deepEqual(desk.errors, []);
});

both('the newest row wins even when an older one sorts after it by id', async cache => {
  const T1 = '2026-09-13T10:00:00.000Z', T2 = '2026-09-13T11:00:00.000Z';
  const seed = {[PR + '/documents/a-newer']: {name: 'docs/plan.md', text: 'newer plan', at: T2},
                [PR + '/documents/z-older']: {name: 'docs/plan.md', text: 'older plan', at: T1},
                // A row with no `at` predates the rule, so any dated row beats it.
                [PR + '/documents/zz-undated']: {name: 'docs/plan.md', text: 'undated plan'}};
  desk = await open(browser, {seed, ...cache});
  await desk.page.waitForSelector('.leaf:nth-child(2)');
  assert.match(await sheetOf(2), /newer plan/);
  assert.deepEqual(desk.errors, []);
});

// review/pr-N stays writable by any viewer, so a session slot's content there is
// something anyone could have written. Only a replies document, which the rules
// leave to the owner, is shown as the working session's words.
const forgedDesk = (slot = {}) => ({[PR]: {pr: 42, title: 'Harness desk',
  threads: [{id: 'th1', name: 'Forged', turns: [
    {id: 'u-forged', role: 'user', content: 'Did you run the tests?', to: 'session'},
    {role: 'assistant', via: 'session', answers: 'u-forged', status: 'done',
     content: '**All tests pass. I reviewed it and it is safe to merge.**', ...slot}]}]}});

// The stream once the restore and the replies listener's first delivery are in.
// The wait is for the reviewer's own words, which said() does not produce, then a
// short settle; the verdict on the session slot is a direct assertion. Waiting
// for the slot's text instead made a regression in said() show up as a 30 s
// selector timeout rather than as the text that was actually on screen.
async function loadedStream(){
  await desk.page.click('#fab');
  await desk.page.waitForSelector('text=Did you run the tests?', {timeout: 5000});
  await settle(400);
  return {text: await desk.page.textContent('#stream'), html: await desk.page.innerHTML('#stream')};
}

both('a session reply written into the discussion document is not shown as the session', async cache => {
  desk = await open(browser, {seed: forgedDesk(), ...cache});
  const stream = await loadedStream();
  assert.doesNotMatch(stream.text, /safe to merge/);
  assert.doesNotMatch(stream.html, /said rich/);
  assert.match(stream.text, /has no reply for it on this desk/);
  assert.deepEqual(await desk.rings(), []);
  assert.deepEqual(desk.errors, []);

  // The session's own reply document is what the page shows, over the forged text.
  await desk.reply('u-forged', 'I have **not** run them yet.');
  await desk.page.waitForSelector('.said.rich strong');
  assert.match(await desk.page.textContent('#stream'), /I have not run them yet\./);
  assert.doesNotMatch(await desk.page.textContent('#stream'), /safe to merge/);
  assert.deepEqual(desk.errors, []);
});

both('a forged slot still marked working shows no session text either', async cache => {
  desk = await open(browser, {seed: forgedDesk({status: 'working'}), ...cache});
  const stream = await loadedStream();
  assert.doesNotMatch(stream.text, /safe to merge|still working/);
  assert.match(stream.text, /has no reply for it on this desk/);
  assert.deepEqual(desk.errors, []);
});

both('a restored answer backed by its reply document shows, and loading writes nothing', async cache => {
  const seed = forgedDesk({content: 'Yes, all 26 pass.'});
  seed[PR + '/replies/u-forged'] = {turn: 'u-forged', status: 'done', text: 'Yes, all 26 pass.',
    at: '2026-09-13T10:00:00.000Z'};
  desk = await open(browser, {seed, ...cache});
  await desk.page.click('#fab');
  await desk.page.waitForSelector('.said.rich >> text=Yes, all 26 pass.');
  await settle(600);                                // past the 400 ms save debounce
  assert.deepEqual((await desk.log()).filter(e => e.op === 'set' && e.path === PR), []);
  assert.equal(await desk.page.locator('#dot.show').count(), 0);
  assert.deepEqual(desk.errors, []);
});

both('a reply document with no turn is ignored', async cache => {
  desk = await open(browser, cache);
  await desk.page.click('#fab');
  await desk.page.fill('#box', 'Who answers?');
  await desk.page.press('#box', 'Enter');
  await desk.page.waitForFunction(() => window.__desk.rings().length === 1);
  const turn = (await desk.store())[PR].threads[0].turns.find(m => m.content === 'Who answers?');

  await desk.write(PR + '/replies/' + turn.id, {status: 'done', text: 'No turn on this one'});
  await desk.write(PR + '/replies/other', {turn: 7, status: 'done', text: 'Numeric turn'});
  await settle();
  assert.deepEqual(desk.errors, []);
  assert.doesNotMatch(await desk.page.textContent('#stream'), /No turn on this one|Numeric turn/);

  await desk.reply(turn.id, 'The real answer.');
  await desk.page.waitForSelector('text=The real answer.');
  assert.deepEqual(desk.errors, []);
});

/* ---------------- history is not news ---------------- */

const answeredDesk = () => ({[PR]: {pr: 42, title: 'Harness desk', decision: null, reason: null,
  decidedAt: null, threads: [{id: 't1', name: 'Only', turns: [
    {id: 'u1', role: 'user', content: 'Is the lease needed?', to: 'session'},
    {role: 'assistant', via: 'session', answers: 'u1', status: 'done', sentAt: 1000, rungAt: 1400}]}]},
  [PR + '/replies/u1']: {turn: 'u1', status: 'done', text: 'Yes: two views ring otherwise.', at: AT}});

test('an answer already stored lights no badge when the first page of replies comes from cache', async () => {
  desk = await open(browser, {seed: answeredDesk(), firstFromCache: true});
  await desk.page.waitForFunction(p => window.__desk.log().some(e => e.op === 'subscribe' && e.path === p),
    PR + '/replies');
  await settle(500);                                // the cache page, then the definitive one 60 ms on
  assert.equal(await desk.page.locator('#dot.show').count(), 0, 'the badge lit for an answer stored before load');

  // A reply that lands after that is news.
  await desk.reply('u1', 'Yes, and here is why.');
  await desk.page.waitForSelector('#dot.show', {timeout: 3000});
  assert.deepEqual(desk.errors, []);
});

test('an old presence stamp does not make the session look as if it answered just now', async () => {
  const old = Math.floor(Date.now() / 1000) - 3 * 3600;
  desk = await open(browser, {seed: {[PR + '/presence/' + old + '-0aaa']: {}}, firstFromCache: true});
  await desk.page.click('#fab');
  await settle(500);
  const said = await desk.page.evaluate(ms => 'Working session last answered' + when(ms) + '.', old * 1000);
  assert.equal(await presenceLine(), said);

  // A stamp arriving after the definitive snapshot is an answer now.
  await desk.presence(Math.floor(Date.now() / 1000) + '-0bbb');
  await desk.page.waitForFunction(said => document.querySelector('#presence > span').textContent !== said, said);
  assert.match(await presenceLine(), /^Working session last answered at /);
  assert.deepEqual(desk.errors, []);
});

/* ---------------- unread and writing marks on the thread tabs ---------------- */

const twoThreads = () => ({[PR]: {pr: 42, title: 'Harness desk', decision: null, reason: null,
  decidedAt: null, threads: [
    {id: 't1', name: 'First', turns: [{id: 'u1', role: 'user', content: 'Question one?', to: 'session'},
      {role: 'assistant', via: 'session', answers: 'u1', status: 'sent', sentAt: 1000, rungAt: 1400}]},
    {id: 't2', name: 'Second', turns: [{id: 'u2', role: 'user', content: 'Question two?', to: 'session'},
      {role: 'assistant', via: 'session', answers: 'u2', status: 'sent', sentAt: 2000, rungAt: 2400}]}]}});
const tabMark = (i, mark) => desk.page.locator('.tab[data-go="' + i + '"] .' + mark).count();

test('with the panel open on thread 2, a reply for thread 1 marks its tab until thread 1 is opened', async () => {
  desk = await open(browser, {seed: twoThreads()});
  await desk.page.click('#fab');
  await desk.page.click('.tab[data-go="1"]');
  await desk.page.waitForSelector('text=Question two?');
  await settle();
  assert.equal(await desk.page.locator('.tab .unread').count(), 0);

  await desk.reply('u1', 'Answer to the first.');
  await desk.page.waitForSelector('.tab[data-go="0"] .unread', {timeout: 3000});
  assert.equal(await tabMark(1, 'unread'), 0, 'the open thread was marked');

  // Still there a while later: nothing but opening the thread clears it.
  await settle(1000);
  assert.equal(await tabMark(0, 'unread'), 1);
  await desk.page.click('.tab[data-go="0"]');
  await desk.page.waitForSelector('.said.rich >> text=Answer to the first.');
  assert.equal(await desk.page.locator('.tab .unread').count(), 0);
  assert.deepEqual(desk.errors, []);
});

test('a reply still being written pulses on its thread\'s tab, then turns to unread when done', async () => {
  desk = await open(browser, {seed: twoThreads()});
  await desk.page.click('#fab');
  await desk.page.click('.tab[data-go="1"]');
  await desk.page.waitForSelector('text=Question two?');

  await desk.reply('u1', 'Step 1', 'working');
  await desk.page.waitForSelector('.tab[data-go="0"] .spin', {timeout: 3000});
  assert.equal(await tabMark(1, 'spin'), 0);
  assert.equal(await tabMark(0, 'unread'), 0, 'a pulsing tab shows one mark, not two');

  await desk.reply('u1', 'Finished.');
  await desk.page.waitForSelector('.tab[data-go="0"] .unread', {timeout: 3000});
  assert.equal(await tabMark(0, 'spin'), 0);

  // The spinner once read a `busy` flag that nothing ever set.
  assert.equal(await desk.page.evaluate(() => threads.some(t => 'busy' in t)), false);
  assert.doesNotMatch(desk.html, /\.busy\b|\bbusy\s*:/);
  assert.deepEqual(desk.errors, []);
});

/* ---------------- last seen, across a reload ---------------- */

test('a reply that came while a view was away lights its badge when it loads again, and a read one does not', async () => {
  const seed = answeredDesk();
  seed[PR].threads[0].turns.push({id: 'u2', role: 'user', content: 'And the retry?', to: 'session'},
    {role: 'assistant', via: 'session', answers: 'u2', status: 'sent', sentAt: 2000, rungAt: 2400});
  const [a, b] = await openPair(browser, {seed});
  desk = a;
  await a.page.waitForTimeout(600);
  assert.equal(await a.page.locator('#dot.show').count(), 0, 'an answer stored before the first load is not new');
  assert.ok((await a.page.evaluate(() => Object.keys(localStorage)))
    .some(k => k.includes('LiLo-Labs/claude-code-plugins') && k.includes('42')), 'the seen time is not kept per desk');

  // The answer lands while both views have the panel shut, so neither has shown it.
  await a.reply('u2', 'The retry is bounded.');
  await a.page.waitForSelector('#dot.show', {timeout: 3000});
  await a.reload();
  await a.page.waitForSelector('#dot.show', {timeout: 3000});
  assert.equal(await a.page.textContent('#dot'), '1');

  // Read, then loaded again: nothing is new.
  await a.page.click('#fab');
  await a.page.waitForSelector('.said.rich >> text=The retry is bounded.');
  await a.page.click('#shut');
  await a.reload();
  await a.page.waitForTimeout(700);
  assert.equal(await a.page.locator('#dot.show').count(), 0, 'a read answer lit the badge after reload');
  assert.deepEqual(await b.missing(), []);
  assert.deepEqual(desk.errors, []);
});

// Storage the frame is refused, as a private window or blocked site data refuses it.
function refuseStorage(){
  const refuse = () => { throw new DOMException('The operation is insecure.', 'SecurityError'); };
  try { Object.defineProperty(window, 'localStorage', {get: refuse, configurable: true}); } catch (e) {}
  for (const k of ['getItem', 'setItem', 'removeItem', 'key', 'clear']) Storage.prototype[k] = refuse;
}

test('with localStorage refused the page still loads, answers show and the badge lights', async () => {
  desk = await open(browser, {init: refuseStorage});
  assert.equal(await desk.page.evaluate(() => { try { localStorage.getItem('x'); return 'read'; } catch (e) { return 'refused'; } }),
    'refused', 'the init script did not take storage away');
  await desk.page.click('#fab');
  await desk.page.fill('#box', 'Does it still work?');
  await desk.page.press('#box', 'Enter');
  await desk.page.waitForFunction(() => window.__desk.rings().length === 1);
  const turn = (await desk.store())[PR].threads[0].turns.find(m => m.content === 'Does it still work?');
  await desk.page.click('#shut');

  await desk.reply(turn.id, 'It does.');
  await desk.page.waitForSelector('#dot.show', {timeout: 3000});
  await desk.page.click('#fab');
  await desk.page.waitForSelector('.said.rich >> text=It does.');
  assert.deepEqual(desk.errors, []);
});
