// A ring that went out and was never answered. The publish succeeds, so the page
// has nothing to retry and nothing to report, while the notice it should have
// become never reaches a session: LiLo-Labs/accrue#9 and #10 were both approved
// this way, and the page sat on "Waiting for the working session" until the
// reviewer went to a terminal and typed the decision out again.
//
// The session stamps review/pr-N/presence for every ring it handles, so a stamp
// from after the ring is the ring's receipt, and its absence is the one thing
// the page can measure. ACK_WAIT after a ring with no stamp, the view rings once
// more -- the same one extra ring a failed ring gets, spending the same `again`
// -- and says so rather than promising that something is on its way.
//
// Every seed here dates rungAt far enough back that the wait is already over, so
// nothing in this file waits 90 seconds for it.
import {test, before, after, afterEach} from 'node:test';
import assert from 'node:assert/strict';
import {launch, open} from './harness.mjs';

const PR = 'review/pr-42';
const RESUME = 'cd ~/code/claude-code-plugins && claude --resume 0123abcd-4567-89ab-cdef-0123456789ab';
// Comfortably past ACK_WAIT (90s), and past RERING_AFTER and RING_BACKOFF too,
// so a ring that does go out can only be the unanswered one.
const LONG_AGO = 95000;

let browser, desk;
before(async () => { browser = await launch(); });
after(async () => { await browser.close(); });
afterEach(async () => {
  if (!desk) return;
  assert.deepEqual(await desk.missing(), [], 'the page called something the stub does not implement');
  assert.deepEqual(desk.errors, []);
  await desk.close();
  desk = null;
});

const ready = d => d.page.waitForFunction('restore === "done"', null, {timeout: 5000});
const line = () => desk.page.textContent('#decide .pickup');
const decisionRings = async () => (await desk.rings()).filter(r => r.doorbell && r.doorbell.kind === 'decision');

const decidedAt = '2026-09-12T10:00:00.000Z';
const decidedDesk = (ring, extra = {}) => ({[PR]: {pr: 42, title: 'Harness desk',
  decision: 'approved', reason: null, decidedAt, decisionRing: {decidedAt, ...ring}, threads: []}, ...extra});
// A stamp is named after the epoch second of the ring it answers, so the page
// times one from its name. `at` is milliseconds.
const stamp = at => ({[PR + '/presence/' + Math.floor(at / 1000)]: {resume: RESUME}});

test('a decision rung with nothing heard since is rung once more, and the store records the spent re-ring', async () => {
  const rungAt = Date.now() - LONG_AGO;
  desk = await open(browser, {seed: decidedDesk({rungAt})});
  await ready(desk);
  const doc = (await desk.until(s => s[PR] && s[PR].decisionRing && s[PR].decisionRing.again,
    null, 8000))[PR];
  assert.equal(doc.decisionRing.decidedAt, decidedAt);
  assert.ok(doc.decisionRing.rungAt > rungAt, 'the new ring is recorded');
  const rings = await decisionRings();
  assert.equal(rings.length, 1, 'exactly one more ring');
  assert.equal(rings[0].doorbell.decision, 'approved');
  assert.equal(rings[0].doorbell.decidedAt, decidedAt);
  assert.equal(rings[0].doorbell.again, true, 'it is the one extra ring, not a first one');
  // The second ring is seconds old, so it is worth waiting on again. What the
  // page must never do is claim that while nothing has answered, which is the
  // state the test below leaves the desk in.
  assert.match(await line(), /^Waiting for the working session\./);
});

test('a stamp from after the ring is the receipt, and nothing is rung again', async () => {
  const rungAt = Date.now() - LONG_AGO;
  desk = await open(browser, {seed: decidedDesk({rungAt}, stamp(rungAt + 20000))});
  await ready(desk);
  await desk.page.waitForTimeout(3000);
  assert.deepEqual(await desk.rings(), []);
  assert.equal((await desk.store())[PR].decisionRing.again, undefined, 'the extra ring is unspent');
  assert.equal(await line(), 'Waiting for the working session. If no session is running, '
    + 'the next one to start picks it up.');
});

test('a stamp from before the ring is no receipt for it', async () => {
  // The session answered an earlier ring on this desk and has since stopped. A
  // page that took any stamp as an answer would wait on this ring for ever.
  const rungAt = Date.now() - LONG_AGO;
  desk = await open(browser, {seed: decidedDesk({rungAt}, stamp(rungAt - 30000))});
  await ready(desk);
  const doc = (await desk.until(s => s[PR] && s[PR].decisionRing && s[PR].decisionRing.again,
    null, 8000))[PR];
  assert.ok(doc.decisionRing.again, 'the unanswered ring is rung once more');
  assert.equal((await decisionRings()).length, 1);
});

test('a ring still inside the wait is left alone', async () => {
  desk = await open(browser, {seed: decidedDesk({rungAt: Date.now() - 2000})});
  await ready(desk);
  await desk.page.waitForTimeout(3000);
  assert.deepEqual(await desk.rings(), [], 'a ring seconds old is still worth waiting on');
  assert.equal((await desk.store())[PR].decisionRing.again, undefined);
  assert.match(await line(), /^Waiting for the working session\./);
});

test('the one extra ring is never spent twice', async () => {
  const rungAt = Date.now() - LONG_AGO;
  desk = await open(browser, {seed: decidedDesk({rungAt, again: rungAt})});
  await ready(desk);
  await desk.page.waitForTimeout(3000);
  assert.deepEqual(await desk.rings(), [], 'a desk left open would otherwise ring for ever');
  await desk.page.waitForSelector('#decide .pickup >> text=no working session has answered', {timeout: 3000});
  assert.match(await line(), /Check, at the top of this panel, rings it again/);
});

test('a decision already collected is not rung again, however long it went unanswered', async () => {
  const rungAt = Date.now() - LONG_AGO;
  desk = await open(browser, {seed: decidedDesk({rungAt}, {[PR + '/context/pickup']:
    {decision: 'approved', decidedAt, session: 's', at: '2026-09-12T10:01:00.000Z'}})});
  await desk.page.waitForSelector('#decide .pickup >> text=Picked up by the working session');
  await desk.page.waitForTimeout(2500);
  assert.deepEqual(await desk.rings(), []);
});

// The same rule for a message: the reviewer asked something, the ring went out,
// and nothing answered.
const messaged = (slot, extra = {}) => ({[PR]: {pr: 42, title: 'Harness desk', decision: null,
  reason: null, decidedAt: null, threads: [{id: 't1', name: 'A', turns: [
    {id: 'm-a', role: 'user', content: 'Why this and not the other?', to: 'session'},
    {role: 'assistant', via: 'session', answers: 'm-a', content: '', ...slot}]}]}, ...extra});

test('a message rung with nothing heard since is rung once more', async () => {
  const rungAt = Date.now() - LONG_AGO;
  desk = await open(browser, {seed: messaged({status: 'sent', sentAt: rungAt - 500, rungAt})});
  await ready(desk);
  const doc = (await desk.until(s => s[PR].threads[0].turns[1].again, null, 10000))[PR];
  const slot = doc.threads[0].turns[1];
  assert.equal(slot.status, 'sent');
  assert.ok(slot.rungAt > rungAt, 'the new ring is recorded');
  const rings = await desk.rings();
  assert.equal(rings.length, 1);
  assert.deepEqual(rings[0].doorbell.turns, ['m-a']);
  assert.equal(rings[0].doorbell.again, true);
  await desk.page.click('#fab');
  // Nothing answered this second ring yet either, but it is seconds old: the
  // stream says the desk was rung and stops there.
  assert.match(await desk.page.textContent('#stream'), /Saved and rung\./);
  assert.doesNotMatch(await desk.page.textContent('#stream'), /rings it once more/);
});

test('an answered message is never rung again, stamp or no stamp', async () => {
  const rungAt = Date.now() - LONG_AGO;
  desk = await open(browser, {seed: messaged({status: 'sent', sentAt: rungAt - 500, rungAt},
    {[PR + '/replies/m-a']: {turn: 'm-a', status: 'done', text: 'Because of the other.',
      at: '2026-09-12T10:00:00.000Z'}})});
  await ready(desk);
  await desk.page.waitForTimeout(3000);
  assert.deepEqual(await desk.rings(), [], 'the reply is the answer; the stamp is only its receipt');
});

test('a message rung inside the wait is left alone', async () => {
  const rungAt = Date.now() - 2000;
  desk = await open(browser, {seed: messaged({status: 'sent', sentAt: rungAt - 500, rungAt})});
  await ready(desk);
  await desk.page.waitForTimeout(3000);
  assert.deepEqual(await desk.rings(), []);
  assert.equal((await desk.store())[PR].threads[0].turns[1].again, undefined);
});

test('a view that cannot ring spends nothing and says who will answer', async () => {
  // No artifact capability: there is no doorbell to ring, so an unanswered ring
  // is not this view's to chase.
  desk = await open(browser, {capabilities: ['db'], seed: decidedDesk({rungAt: Date.now() - LONG_AGO})});
  await ready(desk);
  await desk.page.waitForTimeout(2500);
  assert.deepEqual(await desk.rings(), []);
  assert.equal((await desk.store())[PR].decisionRing.again, undefined);
  assert.doesNotMatch(await line(), /rings it once more|Check, at the top/);
  assert.match(await line(), /^Waiting for the working session\./);
});
