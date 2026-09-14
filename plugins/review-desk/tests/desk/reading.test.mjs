// Reading the panel and the page while answers arrive: the badge says an answer
// came, the stream keeps the reviewer's place, and the page keeps track of which
// section they are reading.
import {test, before, after, afterEach} from 'node:test';
import assert from 'node:assert/strict';
import {launch, open} from './harness.mjs';

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
const REPLIES = PR + '/replies';
const AT = '2026-09-13T10:00:00.000Z';

/* ---------------- the badge ---------------- */

// One thread, one message the session has not answered yet. rungAt is set so
// nothing rings for it on load.
const oneWaiting = () => ({[PR]: {pr: 42, title: 'Harness desk', decision: null, reason: null,
  decidedAt: null, threads: [{id: 't1', name: 'Only', turns: [
    {id: 'u1', role: 'user', content: 'Is the lease needed?', to: 'session'},
    {role: 'assistant', via: 'session', answers: 'u1', status: 'sent', sentAt: 1000, rungAt: 1400}]}]}});

test('with one thread and the panel closed, a reply lights the badge', async () => {
  desk = await open(browser, {seed: oneWaiting()});
  await desk.page.waitForFunction(p => window.__desk.log().some(e => e.op === 'subscribe' && e.path === p),
    REPLIES);
  await desk.page.waitForTimeout(300);                // the first, historical, delivery
  assert.equal(await desk.page.locator('#dot.show').count(), 0);

  await desk.reply('u1', 'Yes: two views ring otherwise.');
  await desk.page.waitForSelector('#dot.show', {timeout: 3000});
  assert.equal(await desk.page.textContent('#dot'), '1');

  // Opening the panel reads it.
  await desk.page.click('#fab');
  await desk.page.waitForSelector('.said.rich >> text=two views ring');
  await desk.page.click('#shut');
  assert.equal(await desk.page.locator('#dot.show').count(), 0);
  assert.deepEqual(desk.errors, []);
});

test('a reply with the panel open on that thread lights nothing', async () => {
  desk = await open(browser, {seed: oneWaiting()});
  await desk.page.click('#fab');
  await desk.page.waitForSelector('text=Is the lease needed?');
  await desk.reply('u1', 'Answered while you watched.');
  await desk.page.waitForSelector('text=Answered while you watched.');
  await desk.page.click('#shut');
  assert.equal(await desk.page.locator('#dot.show').count(), 0);
  assert.deepEqual(desk.errors, []);
});

/* ---------------- the stream keeps its place ---------------- */

const LONG = Array.from({length: 60}, (_, i) => 'Paragraph ' + (i + 1) + ' of the long answer.').join('\n\n');
const twoInOne = () => ({[PR]: {pr: 42, title: 'Harness desk', decision: null, reason: null,
  decidedAt: null, threads: [{id: 't1', name: 'Long', turns: [
    {id: 'u1', role: 'user', content: 'Explain the lease.', to: 'session'},
    {role: 'assistant', via: 'session', answers: 'u1', status: 'done', sentAt: 1000, rungAt: 1400},
    {id: 'u2', role: 'user', content: 'And the retry?', to: 'session'},
    {role: 'assistant', via: 'session', answers: 'u2', status: 'working', sentAt: 2000, rungAt: 2400}]}]},
  [REPLIES + '/u1']: {turn: 'u1', status: 'done', text: LONG, at: AT},
  [REPLIES + '/u2']: {turn: 'u2', status: 'working', text: 'Step 1', at: AT}});

const scroll = to => desk.page.$eval('#stream', (el, to) => {
  el.scrollTop = to === 'end' ? el.scrollHeight : to;
  return el.scrollTop;
}, to);
const scrollTop = () => desk.page.$eval('#stream', el => el.scrollTop);
const gap = () => desk.page.$eval('#stream', el => el.scrollHeight - el.scrollTop - el.clientHeight);

test('a reply rewrite leaves a reader scrolled up where they were, and keeps one at the end there', async () => {
  desk = await open(browser, {seed: twoInOne()});
  await desk.page.click('#fab');
  await desk.page.waitForSelector('text=Step 1');
  assert.ok(await gap() < 2, 'opening the panel starts at the end');

  assert.equal(await scroll(0), 0);
  await desk.reply('u2', 'Step 2', 'working');
  await desk.page.waitForSelector('text=Step 2');
  assert.equal(await scrollTop(), 0);

  // Part way up, too: not only the top, which a clamp would also leave alone.
  const mid = await scroll(300);
  assert.ok(mid > 0, 'the stream is long enough to scroll');
  await desk.reply('u2', 'Step 3', 'working');
  await desk.page.waitForSelector('text=Step 3');
  assert.equal(await scrollTop(), mid);

  await scroll('end');
  await desk.reply('u2', 'Done.\n\n' + LONG.replace(/long answer/g, 'retry answer'));
  await desk.page.waitForSelector('text=Paragraph 60 of the retry answer.');
  assert.ok(await gap() < 2, 'a reader at the end follows the new text');
  assert.deepEqual(desk.errors, []);
});

test('a reply for another thread leaves the open thread\'s stream nodes in place', async () => {
  const seed = twoInOne();
  const turns = seed[PR].threads[0].turns;
  seed[PR].threads = [{id: 't1', name: 'First', turns: turns.slice(0, 2)},
                      {id: 't2', name: 'Second', turns: turns.slice(2)}];
  desk = await open(browser, {seed});
  await desk.page.click('#fab');
  await desk.page.waitForSelector('text=Paragraph 60 of the long answer.');
  await desk.page.waitForTimeout(300);
  await desk.page.evaluate(() => {
    window.__held = document.querySelector('#stream .turn.theirs');
    window.__tabsRedrawn = new Promise(done => new MutationObserver((_, o) => { o.disconnect(); done(); })
      .observe(document.getElementById('tabs'), {childList: true}));
  });

  await desk.reply('u2', 'The retry is bounded.');
  await desk.page.evaluate(() => window.__tabsRedrawn);
  await desk.page.waitForTimeout(100);
  assert.equal(await desk.page.evaluate(() =>
    window.__held.isConnected && document.querySelector('#stream .turn.theirs') === window.__held), true,
    'the open thread\'s stream was rebuilt for a reply to another thread');

  // Nothing is stale: the other thread shows the new answer when opened.
  await desk.page.click('.tab[data-go="1"]');
  await desk.page.waitForSelector('.said.rich >> text=The retry is bounded.');
  // And a later one, while the panel is shut on the first thread, lights the badge.
  await desk.page.click('.tab[data-go="0"]');
  await desk.page.click('#shut');
  await desk.reply('u2', 'The retry is bounded, twice.');
  await desk.page.waitForSelector('#dot.show', {timeout: 3000});
  assert.deepEqual(desk.errors, []);
});
