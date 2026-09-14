// Load order. Every save replaces the whole stored document, so nothing may be
// written until that document has been read; and a message stored without a
// recorded ring is rung again when the desk next loads.
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
const turnsIn = store => ((store[PR] && store[PR].threads) || []).flatMap(t => t.turns);
const asked = store => turnsIn(store).filter(m => m.role === 'user').map(m => m.content);
const reads = log => log.filter(e => e.op === 'get' && e.path === PR).length;
const writes = log => log.filter(e => e.op === 'set');

// A desk decided yesterday, with a conversation behind the decision.
const decidedDesk = () => ({[PR]: {pr: 42, title: 'Harness desk',
  decision: 'approved', reason: null, decidedAt: '2026-09-12T10:00:00.000Z',
  threads: [{id: 't1', name: 'Earlier', turns: [
    {id: 'm-old', role: 'user', content: 'Asked yesterday', to: 'session'},
    {role: 'assistant', via: 'session', answers: 'm-old', status: 'done',
     content: 'Answered yesterday', sentAt: 1}]}]}});

test('a restore that fails twice writes nothing, and says so', async () => {
  const seed = decidedDesk();
  desk = await open(browser, {seed, getFailures: 2});
  await desk.page.click('#fab');                  // the banner lives in the panel
  await desk.page.waitForSelector('#lostSlot .lost');
  await desk.page.fill('#box', 'Sent while the store could not be read');
  await desk.page.press('#box', 'Enter');
  await desk.page.waitForTimeout(600);             // past the 400 ms save debounce

  const log = await desk.log();
  assert.equal(reads(log), 2, 'one read and exactly one retry');
  assert.deepEqual(writes(log), []);
  assert.deepEqual(await desk.store(), seed);
  assert.deepEqual(await desk.rings(), []);
  assert.ok(await desk.page.isVisible('#lostSlot .lost'));
  assert.match(await desk.page.textContent('#lostSlot'), /could not be read/);
  assert.ok(await desk.page.isDisabled('#send'));
  assert.ok(await desk.page.isDisabled('#ok'));
  assert.equal(await desk.page.inputValue('#box'), 'Sent while the store could not be read');
  assert.deepEqual(desk.errors, []);
});

test('Try again after a failed restore loads the discussion, and saving resumes', async () => {
  desk = await open(browser, {seed: decidedDesk(), getFailures: 2});
  await desk.page.click('#fab');
  await desk.page.click('#lostSlot button');
  await desk.page.waitForSelector('text=Asked yesterday');
  assert.equal(await desk.page.textContent('#lostSlot'), '');
  await desk.page.fill('#box', 'Asked after trying again');
  await desk.page.press('#box', 'Enter');
  const store = await desk.until(s => asked(s).includes('Asked after trying again'));
  assert.deepEqual(asked(store), ['Asked yesterday', 'Asked after trying again']);
  assert.equal(store[PR].decision, 'approved');
  assert.deepEqual(desk.errors, []);
});

test('a restore that fails once is retried, and a send appends to what it restored', async () => {
  desk = await open(browser, {seed: decidedDesk(), getFailures: 1});
  await desk.page.click('#fab');
  await desk.page.waitForSelector('text=Asked yesterday');
  await desk.page.fill('#box', 'Asked after the retry');
  await desk.page.press('#box', 'Enter');
  const store = await desk.until(s => asked(s).includes('Asked after the retry'));

  assert.equal(reads(await desk.log()), 2);
  assert.deepEqual(asked(store), ['Asked yesterday', 'Asked after the retry']);
  assert.equal(store[PR].decision, 'approved');
  assert.equal(store[PR].decidedAt, '2026-09-12T10:00:00.000Z');
  assert.equal(await desk.page.textContent('#lostSlot'), '');
  assert.deepEqual(desk.errors, []);
});

test('while the stored document loads, Approve, Send and the openers write nothing', async () => {
  const seed = {[PR]: {pr: 42, title: 'Harness desk', decision: null, reason: null,
    decidedAt: null, threads: [{id: 't1', name: 'Earlier', turns: [
      {id: 'm-old', role: 'user', content: 'The important argument', to: 'session'}]}]}};
  desk = await open(browser, {seed, getDelay: 2000});
  const started = Date.now();

  assert.ok(await desk.page.isDisabled('#ok'));
  // force skips Playwright's wait for the button to be enabled, so the click
  // lands now, during the load, as a quick tap on a tablet would.
  await desk.page.click('#ok', {force: true});
  await desk.page.click('#fab');
  assert.match(await desk.page.textContent('#stream'), /Loading the saved discussion/);
  assert.ok(await desk.page.isDisabled('#send'));
  await desk.page.fill('#box', 'Sent during the load');
  await desk.page.press('#box', 'Enter');
  await desk.page.click('#seed button', {force: true});
  assert.ok(Date.now() - started < 2000, 'every action landed inside the delayed read');

  await desk.page.waitForSelector('text=The important argument');
  await desk.page.waitForTimeout(600);
  assert.deepEqual(writes(await desk.log()), []);
  assert.deepEqual(await desk.store(), seed);
  assert.equal(await desk.page.inputValue('#box'), 'Sent during the load');

  // Once settled, the same button records the decision beside the discussion.
  await desk.page.click('#ok');
  const store = await desk.until(s => s[PR].decision === 'approved');
  assert.deepEqual(asked(store), ['The important argument']);
  assert.deepEqual(desk.errors, []);
});

test('a stored message with no recorded ring is rung again once, and not on the next load', async () => {
  const seed = {[PR]: {pr: 42, threads: [{id: 't1', name: 'Earlier', turns: [
    {id: 'm-lost', role: 'user', content: 'Saved but never rung', to: 'session'},
    {role: 'assistant', via: 'session', answers: 'm-lost', status: 'sent', content: '',
     sentAt: Date.now() - 30000}]}]}};
  desk = await open(browser, {seed});
  const stored = await desk.until(s => turnsIn(s).some(m => m.answers === 'm-lost' && m.rungAt));
  await desk.page.waitForTimeout(800);
  const rings = await desk.rings();
  assert.equal(rings.length, 1);
  assert.equal(rings[0].doorbell.kind, 'message');
  assert.deepEqual(rings[0].doorbell.turns, ['m-lost']);
  assert.deepEqual(await desk.missing(), []);
  await desk.close();

  // The same store, loaded again straight away.
  desk = await open(browser, {seed: stored});
  await desk.page.waitForSelector('text=Saved but never rung', {state: 'attached'});
  await desk.page.waitForTimeout(1000);
  assert.deepEqual(await desk.rings(), []);
  assert.deepEqual(desk.errors, []);
});

// The republish case: the view reloads seconds after a send, before the ring
// outcome was stored. The slot is too young to ring at load, and must still be
// rung once it comes of age while the tab stays open.
test('a message with a reply is never rung; one sent seconds ago is rung when it is ten seconds old', async () => {
  const seed = {
    [PR]: {pr: 42, threads: [{id: 't1', name: 'Two', turns: [
      {id: 'm-claimed', role: 'user', content: 'Claimed already', to: 'session'},
      {role: 'assistant', via: 'session', answers: 'm-claimed', status: 'sent', content: '',
       sentAt: Date.now() - 30000},
      {id: 'm-fresh', role: 'user', content: 'Sent a moment ago', to: 'session'},
      {role: 'assistant', via: 'session', answers: 'm-fresh', status: 'sent', content: '',
       sentAt: Date.now() - 6000}]}]},
    // Another tab may still be ringing for m-fresh; m-claimed has a reply document.
    [PR + '/replies/m-claimed']: {turn: 'm-claimed', status: 'working', text: '', at: '2026-09-13T00:00:00Z'},
  };
  desk = await open(browser, {seed});
  await desk.page.click('#fab');
  await desk.page.waitForSelector('text=Sent a moment ago');
  await desk.page.waitForTimeout(500);
  assert.deepEqual(await desk.rings(), [], 'too young to ring at load');
  // No ring is recorded, so the page must not say it rang.
  assert.doesNotMatch(await desk.page.textContent('#stream'), /Saved and rung/);
  assert.match(await desk.page.textContent('#stream'), /Ringing the working session/);

  const store = await desk.until(s => turnsIn(s).some(m => m.answers === 'm-fresh' && m.rungAt),
    null, 8000);
  await desk.page.waitForTimeout(800);
  const rings = await desk.rings();
  assert.equal(rings.length, 1);
  assert.deepEqual(rings[0].doorbell.turns, ['m-fresh']);
  assert.ok(!turnsIn(store).find(m => m.answers === 'm-claimed').rungAt);
  assert.deepEqual(desk.errors, []);
});

test('a ring refused with conflict is rung again on the next load, without waiting', async () => {
  // The ring publish loses to a newer version, as it does when the session
  // republishes the desk during a send.
  desk = await open(browser, {seed: {}, publishError: 'conflict'});
  await desk.page.click('#fab');
  await desk.page.fill('#box', 'Sent as the desk republished');
  await desk.page.press('#box', 'Enter');
  const stored = await desk.until(s => turnsIn(s).some(m => m.status === 'unsent' && m.why === 'conflict'));
  const id = turnsIn(stored).find(m => m.why === 'conflict').answers;
  await desk.close();

  // The reloaded view, seconds after the send: well inside RERING_AFTER.
  desk = await open(browser, {seed: stored});
  const after = await desk.until(s => turnsIn(s).some(m => m.answers === id && m.rungAt), null, 3000);
  const slot = turnsIn(after).find(m => m.answers === id);
  assert.equal(slot.status, 'sent');
  assert.equal(slot.why, undefined);
  const rings = await desk.rings();
  assert.equal(rings.length, 1);
  assert.deepEqual(rings[0].doorbell.turns, [id]);
  assert.deepEqual(desk.errors, []);
});

test('the Sent line promises no answer until a presence stamp newer than the send', async () => {
  const sentAt = Date.now() - 5000;
  const tenMinutesAgo = Math.floor((Date.now() - 600000) / 1000);
  const seed = {
    [PR]: {pr: 42, threads: [{id: 't1', name: 'Waiting', turns: [
      {id: 'm-wait', role: 'user', content: 'Is anyone there?', to: 'session'},
      {role: 'assistant', via: 'session', answers: 'm-wait', status: 'sent', content: '',
       sentAt, rungAt: sentAt + 300}]}]},
    // A stamp from an earlier ring, before this message was sent.
    [PR + '/presence/' + tenMinutesAgo + '-0aaa']: {},
  };
  desk = await open(browser, {seed});
  await desk.page.click('#fab');
  await desk.page.waitForSelector('text=No working session has answered');
  const said = () => desk.page.textContent('.turn.theirs .said');
  assert.doesNotMatch(await said(), /within seconds/);

  await desk.presence(Math.floor(Date.now() / 1000) + '-0bbb');
  await desk.page.waitForSelector('text=answers within seconds');
  assert.deepEqual(await desk.rings(), []);
  assert.deepEqual(desk.errors, []);
});
