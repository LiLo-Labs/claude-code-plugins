// The live listeners take whatever rows the store holds. A malformed one must be
// skipped, not thrown on: a throw inside a snapshot callback is uncaught, and
// the ones here broke every later repaint until the row was deleted.
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

const PR = 'review/pr-42';
const settle = (ms = 300) => desk.page.waitForTimeout(ms);
const presenceLine = () => desk.page.textContent('#presence > span');
const fresh = () => desk.page.locator('.leaf .fresh.show').count();
const sheetOf = async n => { await desk.page.click('.leaf:nth-child(' + n + ')'); return desk.page.textContent('#sheet'); };

test('presence ids out of range or not numbers break no redraw', async () => {
  // Seeded, so they arrive in the first snapshot, which times stamps by name.
  const seed = {[PR + '/presence/9999999999999']: {}, [PR + '/presence/abc']: {},
                [PR + '/presence/-1']: {}};
  desk = await open(browser, {seed});
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

test('document rows without a string name or text are skipped, and the leaves still switch', async () => {
  const data = payload({documents: [{name: 'docs/a.md', text: 'Alpha text'},
    {text: 'carried with no name'}, {name: 'docs/b.md', text: 'Beta text'}]});
  desk = await open(browser, {data});
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

test('two rows for one document show the newer, and an identical snapshot flags nothing', async () => {
  const T1 = '2026-09-13T10:00:00.000Z', T2 = '2026-09-13T11:00:00.000Z';
  const data = payload({documents: [{name: 'docs/design.md', text: 'rev 1'}]});
  const seed = {[PR + '/documents/design']: {name: 'docs/design.md', text: 'rev 2', at: T1},
                [PR + '/documents/docs~design.md']: {name: 'docs/design.md', text: 'rev 3', at: T2}};
  desk = await open(browser, {data, seed});
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

test('the newest row wins even when an older one sorts after it by id', async () => {
  const T1 = '2026-09-13T10:00:00.000Z', T2 = '2026-09-13T11:00:00.000Z';
  const seed = {[PR + '/documents/a-newer']: {name: 'docs/plan.md', text: 'newer plan', at: T2},
                [PR + '/documents/z-older']: {name: 'docs/plan.md', text: 'older plan', at: T1},
                // A row with no `at` predates the rule, so any dated row beats it.
                [PR + '/documents/zz-undated']: {name: 'docs/plan.md', text: 'undated plan'}};
  desk = await open(browser, {seed});
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

test('a session reply written into the discussion document is not shown as the session', async () => {
  desk = await open(browser, {seed: forgedDesk()});
  await desk.page.click('#fab');
  await desk.page.waitForSelector('text=Did you run the tests?');
  await desk.page.waitForSelector('text=has no reply for it on this desk');
  const stream = await desk.page.innerHTML('#stream');
  assert.doesNotMatch(stream, /safe to merge/);
  assert.doesNotMatch(stream, /said rich/);
  assert.deepEqual(await desk.rings(), []);
  assert.deepEqual(desk.errors, []);

  // The session's own reply document is what the page shows, over the forged text.
  await desk.reply('u-forged', 'I have **not** run them yet.');
  await desk.page.waitForSelector('.said.rich strong');
  assert.match(await desk.page.textContent('#stream'), /I have not run them yet\./);
  assert.doesNotMatch(await desk.page.textContent('#stream'), /safe to merge/);
  assert.deepEqual(desk.errors, []);
});

test('a forged slot still marked working shows no session text either', async () => {
  desk = await open(browser, {seed: forgedDesk({status: 'working'})});
  await desk.page.click('#fab');
  await desk.page.waitForSelector('text=has no reply for it on this desk');
  assert.doesNotMatch(await desk.page.textContent('#stream'), /safe to merge|still working/);
  assert.deepEqual(desk.errors, []);
});

test('a restored answer backed by its reply document shows, and loading writes nothing', async () => {
  const seed = forgedDesk({content: 'Yes, all 26 pass.'});
  seed[PR + '/replies/u-forged'] = {turn: 'u-forged', status: 'done', text: 'Yes, all 26 pass.',
    at: '2026-09-13T10:00:00.000Z'};
  desk = await open(browser, {seed});
  await desk.page.click('#fab');
  await desk.page.waitForSelector('.said.rich >> text=Yes, all 26 pass.');
  await settle(600);                                // past the 400 ms save debounce
  assert.deepEqual((await desk.log()).filter(e => e.op === 'set' && e.path === PR), []);
  assert.equal(await desk.page.locator('#dot.show').count(), 0);
  assert.deepEqual(desk.errors, []);
});

test('a reply document with no turn is ignored', async () => {
  desk = await open(browser);
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
