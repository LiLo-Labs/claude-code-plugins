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
