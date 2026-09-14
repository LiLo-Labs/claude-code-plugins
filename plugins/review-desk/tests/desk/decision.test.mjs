// The decision loop: Approve and the confirm step it opens, Needs changes and its
// reason, Change this, the line under a recorded decision as the working session picks it up and reports
// what happened, and Check in the panel. The session's side is written the way
// /review-desk and /review-collect write it: a set of context/pickup, then the
// outcome, and a presence stamp for each ring it handles.
import {test, before, after, afterEach} from 'node:test';
import assert from 'node:assert/strict';
import {launch, open, openPair, payload, approve} from './harness.mjs';

const PR = 'review/pr-42';
const RESUME = 'cd ~/code/claude-code-plugins && claude --resume 0123abcd-4567-89ab-cdef-0123456789ab';

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
const lineSays = text => desk.page.waitForSelector('#decide .pickup >> text=' + text, {timeout: 3000});
const decisionRings = async () => (await desk.rings()).filter(r => r.doorbell && r.doorbell.kind === 'decision');

async function needsChanges(reason){
  await desk.page.click('#changes');
  await desk.page.fill('#why', reason);
  await desk.page.click('#recordReason');
}

test('Needs changes opens the reason form, records nothing without a reason, and Back returns to the choice', async () => {
  desk = await open(browser);
  await ready(desk);
  await desk.page.click('#changes');
  await desk.page.waitForSelector('#why');
  assert.equal(await desk.page.textContent('#decide .cap'), 'What needs changing');
  assert.equal(await desk.page.locator('#send').count(), 1, 'the chat Send is the only #send');

  await desk.page.fill('#why', '   ');
  await desk.page.click('#recordReason');
  await desk.page.waitForTimeout(600);
  assert.equal(await desk.page.locator('#why').count(), 1, 'an empty reason leaves the form up');
  assert.deepEqual(await desk.store(), {});
  assert.deepEqual(await desk.rings(), []);

  await desk.page.click('#back');
  await desk.page.waitForSelector('#ok');
  assert.equal(await desk.page.isEnabled('#changes'), true);
  assert.deepEqual(await desk.store(), {});
});

test('Record it stores needs changes with the reason and decidedAt, and rings kind decision once', async () => {
  desk = await open(browser);
  await ready(desk);
  const before = new Date().toISOString();
  await needsChanges('  Rename the flag, it reads as a boolean.  ');
  const doc = (await desk.until(s => s[PR] && s[PR].decision === 'needs changes'))[PR];
  assert.equal(doc.reason, 'Rename the flag, it reads as a boolean.');
  assert.match(doc.decidedAt, /^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}Z$/);
  assert.ok(doc.decidedAt >= before);

  await lineSays('Waiting for the working session');
  await desk.page.waitForTimeout(600);
  const rings = await desk.rings();
  assert.equal(rings.length, 1);
  assert.deepEqual({kind: rings[0].doorbell.kind, decision: rings[0].doorbell.decision,
    decidedAt: rings[0].doorbell.decidedAt}, {kind: 'decision', decision: 'needs changes', decidedAt: doc.decidedAt});
  assert.match(await desk.page.textContent('#decide .done'), /You marked this needs changes/);
  assert.equal(await desk.page.textContent('#decide blockquote'), 'Rename the flag, it reads as a boolean.');
});

test('Change this after a recorded decision re-opens the choice, and the new decision gets a later decidedAt', async () => {
  desk = await open(browser);
  await ready(desk);
  await needsChanges('Split the migration out.');
  const first = (await desk.until(s => s[PR] && s[PR].decision === 'needs changes'))[PR];
  await lineSays('Waiting for the working session');

  await desk.page.click('#redo');
  await desk.page.waitForSelector('#ok');
  assert.equal(await desk.page.isEnabled('#ok'), true);
  assert.equal(await desk.page.isEnabled('#changes'), true);
  // The reason form comes back holding the recorded reason to edit.
  await desk.page.click('#changes');
  assert.equal(await desk.page.inputValue('#why'), 'Split the migration out.');
  await desk.page.click('#back');

  await desk.page.waitForTimeout(5);
  await approve(desk);
  const again = (await desk.until(s => s[PR] && s[PR].decision === 'approved'))[PR];
  assert.ok(Date.parse(again.decidedAt) > Date.parse(first.decidedAt),
    again.decidedAt + ' is not later than ' + first.decidedAt);
  assert.equal(again.reason, null);
  await desk.page.waitForFunction(() => window.__desk.rings().length === 2);
  assert.deepEqual((await decisionRings()).map(r => [r.doorbell.decision, r.doorbell.decidedAt]),
    [['needs changes', first.decidedAt], ['approved', again.decidedAt]]);
});

test('the pickup line follows the session: picked up, merged, blocked with its detail, closed, and revising on a later decision', async () => {
  desk = await open(browser);
  await ready(desk);
  await approve(desk);
  const {decidedAt} = (await desk.until(s => s[PR] && s[PR].decision === 'approved'))[PR];
  await lineSays('Waiting for the working session');
  const at = new Date().toISOString();
  const pickup = extra => desk.context('pickup', {decision: 'approved', decidedAt, session: 's1', at, ...extra});

  // An acknowledgement of some earlier verdict is not one for this verdict.
  await pickup({decidedAt: '2026-01-01T00:00:00.000Z'});
  await desk.page.waitForTimeout(300);
  assert.match(await line(), /^Waiting for the working session\./);

  await pickup({});
  await lineSays('Picked up by the working session');
  assert.match(await line(), /^Picked up by the working session at .+\. What it did shows here once it has acted\.$/);

  const outcomes = [
    [{result: 'merged', detail: 'Squash-merged as 1a2b3c4.'}, /^Merged by the working session at .+: Squash-merged as 1a2b3c4\.$/],
    [{result: 'blocked', detail: 'A required check failed: tests (webkit).'},
      /^The working session could not finish: A required check failed: tests \(webkit\)\.$/],
    [{result: 'closed', detail: 'The pull request was closed on GitHub.'},
      /^Closed without merging at .+: The pull request was closed on GitHub\.$/],
  ];
  const seen = new Set();
  for (const [outcome, expected] of outcomes){
    const before = await line();
    await pickup({outcome: {...outcome, at: new Date().toISOString()}});
    await desk.page.waitForFunction(was => document.querySelector('#decide .pickup').textContent !== was, before);
    const said = await line();
    assert.match(said, expected, outcome.result);
    seen.add(said);
  }
  assert.equal(seen.size, outcomes.length, 'each outcome has its own line');

  // Deciding again leaves the old pickup behind; the session's pickup for the new
  // verdict says it is revising.
  await desk.page.click('#redo');
  await needsChanges('Keep the old flag name as an alias.');
  const later = (await desk.until(s => s[PR] && s[PR].decision === 'needs changes'))[PR];
  await lineSays('Waiting for the working session');
  await desk.context('pickup', {decision: 'needs changes', decidedAt: later.decidedAt, session: 's1', at,
    outcome: {result: 'revising', detail: 'Adding the alias and a test for it.', at}});
  await lineSays('The working session is revising');
  assert.equal(await line(), 'The working session is revising: Adding the alias and a test for it.');
});

const refusedPublishes = log => log.filter(e => e.op === 'publish refused');
const LATER = ' If no session is running, the next one to start picks it up.';

test('Approve whose ring is refused as rate_limited or upstream_error records the failure and says it tries again', async () => {
  for (const code of ['rate_limited', 'upstream_error']){
    desk = await open(browser, {publishError: code});
    await ready(desk);
    await approve(desk);
    const doc = (await desk.until(s => s[PR] && s[PR].decisionRing && s[PR].decisionRing.why === code))[PR];
    assert.equal(doc.decisionRing.decidedAt, doc.decidedAt);
    assert.equal(await line(), 'Saved, but the working session was not notified (' + code
      + '). This view tries again in a few seconds.' + LATER, code);
    assert.deepEqual(await desk.rings(), [], code);
    // artifact.d.ts: retry only upstream_error, once; rate_limited slows down instead.
    assert.equal(refusedPublishes(await desk.log()).length, code === 'upstream_error' ? 2 : 1, code);
    if (code === 'rate_limited'){
      assert.deepEqual(await desk.missing(), []);
      assert.deepEqual(desk.errors, []);
      await desk.close();
    }
  }
});

test('a decision whose re-ring is refused again is not tried a third time, and the line points at Check', async () => {
  desk = await open(browser, {publishError: 'rate_limited'});
  await ready(desk);
  await approve(desk);
  await desk.until(s => s[PR] && s[PR].decisionRing && s[PR].decisionRing.again, null, 10000);
  await lineSays('Check in the panel rings it again');
  assert.equal(await line(), 'Saved, but this view could not notify the working session (rate_limited). '
    + 'Check in the panel rings it again.' + LATER);
  await desk.page.waitForTimeout(6500);              // past another backoff
  assert.equal(refusedPublishes(await desk.log()).length, 2);
});

// artifact.d.ts: a read-only view still resolves the namespace, and its first
// not_writer or not_granted is the read-only signal.
test('a view refused as not_writer or not_granted stops ringing: the banner shows, Check goes, and nothing publishes again', async () => {
  for (const code of ['not_writer', 'not_granted']){
    desk = await open(browser, {publishError: code});
    await ready(desk);
    await desk.page.click('#fab');
    await desk.page.waitForSelector('#check');
    assert.equal(await desk.page.textContent('#aloneSlot'), '', code + ': nothing says read-only before a publish');

    await desk.page.fill('#box', 'First message');
    await desk.page.press('#box', 'Enter');
    await desk.page.waitForSelector('#aloneSlot .lost >> text=This view cannot ring the working session');
    assert.ok(await desk.page.isVisible('#aloneSlot .lost'), code);
    assert.equal(await desk.page.locator('#check').count(), 0, code + ': Check is gone');
    await desk.page.waitForSelector('#stream >> text=This view cannot ring the working session, so the next session to start answers it');

    await desk.page.fill('#box', 'Second message');
    await desk.page.press('#box', 'Enter');
    await desk.page.click('#shut');
    await approve(desk);
    const doc = (await desk.until(s => s[PR] && s[PR].decision === 'approved' && s[PR].decisionRing
      && s[PR].threads[0].turns.filter(m => m.via === 'session' && m.why === 'readonly').length === 2))[PR];
    assert.equal(doc.decisionRing.why, 'readonly');
    await lineSays('cannot notify');
    assert.equal(await line(), 'Saved. This view cannot notify the working session, so the next session to start picks it up.');
    await desk.page.waitForTimeout(600);

    assert.equal(refusedPublishes(await desk.log()).length, 1, code + ': only the first attempt publishes');
    assert.deepEqual(await desk.rings(), [], code);
    for (const sel of ['#panel', '#decide'])
      assert.doesNotMatch(await desk.page.textContent(sel), new RegExp('\\(' + code + '\\)|' + code), code + ' in ' + sel);
    if (code === 'not_writer'){
      assert.deepEqual(await desk.missing(), []);
      assert.deepEqual(desk.errors, []);
      await desk.close();
    }
  }
});

// Records every pickup line the decision slab is drawn with, at the moment it is
// written, with how many rings this view had made by then. A MutationObserver read
// the text only when its callback ran, after the stub had loaded, rung and redrawn
// in one burst of microtasks, so an intermediate line was never seen.
const recordLines = () => {
  window.__lines = [];
  const html = Object.getOwnPropertyDescriptor(Element.prototype, 'innerHTML');
  Object.defineProperty(Element.prototype, 'innerHTML', {...html, set(v){
    const m = this.id === 'decide' && /<p class="pickup">([^<]*)<\/p>/.exec(String(v));
    if (m) window.__lines.push({text: m[1], rung: window.__desk.rings().length});
    return html.set.call(this, v);
  }});
};
const decisionPublishes = log => log.filter(e => e.op === 'publish' && e.ring.doorbell && e.ring.doorbell.kind === 'decision');
// Lines that said the view was waiting while this view had rung nothing.
const waitingBefore = lines => lines.filter(l => /Waiting for the working session/.test(l.text) && l.rung === 0);
const pollFor = async (what, fn, timeout) => {
  for (const end = Date.now() + timeout;;){
    if (await fn()) return;
    if (Date.now() > end) throw new Error(what);
    await new Promise(r => setTimeout(r, 100));
  }
};

test('a decision whose ring failed twice as upstream_error is rung once by the reloaded view, which never says it is waiting first', async () => {
  const [a, b] = await openPair(browser, {publishError: ['upstream_error', 'upstream_error'], init: recordLines});
  desk = a;
  await ready(a); await ready(b);
  await approve(a);
  const {decidedAt} = (await a.until(s => s[PR] && s[PR].decisionRing
    && s[PR].decisionRing.why === 'upstream_error'))[PR];
  assert.equal(refusedPublishes(await a.log()).length, 2);
  assert.match(await line(), /^Saved, but the working session was not notified \(upstream_error\)\./);
  assert.deepEqual(waitingBefore(await a.page.evaluate('window.__lines'), Infinity), []);

  // The tab reloads before its own retry, as a closed iPad tab reopened would.
  const reloadedAt = Date.now();
  await a.reload();
  await ready(a);
  await pollFor('the reloaded view never rang the decision', async () =>
    decisionPublishes(await a.log()).length === 1, 20000);
  const [ring] = decisionPublishes(await a.log());
  assert.equal(ring.view, 'view-a');
  assert.ok(ring.at - reloadedAt < 20000, 'rung ' + (ring.at - reloadedAt) + ' ms after the reload');
  assert.deepEqual([ring.ring.doorbell.decision, ring.ring.doorbell.decidedAt], ['approved', decidedAt]);
  const stored = (await a.until(s => s[PR].decisionRing && s[PR].decisionRing.rungAt))[PR];
  assert.equal(stored.decisionRing.decidedAt, decidedAt);
  assert.ok(stored.decisionRing.again, 'the one re-ring is spent');
  await lineSays('Waiting for the working session');
  assert.deepEqual(waitingBefore(await a.page.evaluate('window.__lines'), ring.at), []);

  // The other view loads the rung record: it says waiting, and nothing rings again.
  await b.reload();
  await ready(b);
  await b.page.waitForSelector('#decide .pickup >> text=Waiting for the working session');
  await a.page.waitForTimeout(6500);                 // past the backoff
  assert.equal(decisionPublishes(await a.log()).length, 1);
  assert.equal(refusedPublishes(await a.log()).length, 2);
  assert.deepEqual(await b.missing(), []);
});

test('a stored decision with no recorded ring and no pickup is rung once at load, and not on the next load', async () => {
  const seed = {[PR]: {pr: 42, title: 'Harness desk', decision: 'approved', reason: null,
    decidedAt: '2026-09-12T10:00:00.000Z', threads: []}};
  desk = await open(browser, {seed, init: recordLines});
  await pollFor('the stored decision was never rung', async () => (await decisionRings()).length === 1, 5000);
  const [ring] = decisionPublishes(await desk.log());
  const stored = await desk.until(s => s[PR].decisionRing && s[PR].decisionRing.rungAt);
  await lineSays('Waiting for the working session');
  const lines = await desk.page.evaluate('window.__lines');
  assert.deepEqual(waitingBefore(lines, ring.at), []);
  assert.ok(lines.some(l => /^Saved\. No ring is recorded for it yet/.test(l.text)), JSON.stringify(lines));
  assert.deepEqual(await desk.missing(), []);
  await desk.close();

  desk = await open(browser, {seed: stored});
  await ready(desk);
  await lineSays('Waiting for the working session');
  await desk.page.waitForTimeout(1500);
  assert.deepEqual(await desk.rings(), []);
  assert.deepEqual(await desk.missing(), []);
  await desk.close();

  // The same decision picked up already: nothing rings.
  desk = await open(browser, {seed: {...seed, [PR + '/context/pickup']: {decision: 'approved',
    decidedAt: seed[PR].decidedAt, session: 's', at: '2026-09-12T10:01:00.000Z'}}});
  await lineSays('Picked up by the working session');
  await desk.page.waitForTimeout(1500);
  assert.deepEqual(await desk.rings(), []);
  assert.deepEqual(await desk.missing(), []);
  await desk.close();

  // A view that cannot ring says so, and never that it is waiting.
  desk = await open(browser, {seed, capabilities: ['db'], init: recordLines});
  await lineSays('cannot notify');
  await desk.page.waitForTimeout(1000);
  assert.equal(await line(), 'Saved. This view cannot notify the working session, so the next session to start picks it up.');
  assert.deepEqual(waitingBefore(await desk.page.evaluate('window.__lines'), Infinity), []);
});

test('a view that cannot ring records a decision and says it could not notify the working session', async () => {
  desk = await open(browser, {capabilities: ['db']});
  await ready(desk);
  await approve(desk);
  await desk.until(s => s[PR] && s[PR].decision === 'approved');
  await lineSays('could not notify');
  assert.match(await line(), /^Saved, but this view could not notify the working session \(unavailable\)\./);
});

test('a view that cannot reach the store says no session will see the decision', async () => {
  desk = await open(browser, {capabilities: []});
  await desk.page.waitForFunction('restore === "nostore"');
  await approve(desk);
  await lineSays('Saving is unavailable on this view');
  assert.deepEqual(await desk.store(), {});
});

test('Check rings kind ping, and a presence stamp written after it says the session answered', async () => {
  desk = await open(browser);
  await ready(desk);
  await desk.page.click('#fab');
  await desk.page.waitForSelector('#presence >> text=has not answered on this desk yet');
  await desk.page.click('#check');
  await desk.page.waitForSelector('#presence >> text=Checking the working session');
  await desk.page.waitForFunction(() => window.__desk.rings().length === 1);
  const [ring] = await desk.rings();
  assert.equal(ring.doorbell.kind, 'ping');

  await desk.presence(String(Math.floor(Date.now() / 1000)));
  await desk.page.waitForSelector('#presence >> text=Working session last answered at');
  assert.equal(await desk.page.locator('#resumeCmd').count(), 0);
  assert.deepEqual(Object.keys(await desk.store()).filter(k => !k.startsWith(PR + '/presence/')), [],
    'Check writes nothing to the store; only the session stamp is there');
});

test('Check with no answer inside the wait says so, and offers the resume command to copy', async () => {
  const stamp = String(Math.floor(Date.now() / 1000) - 3600);
  desk = await open(browser, {clock: true, seed: {[PR + '/presence/' + stamp]: {resume: RESUME}}});
  await ready(desk);
  await desk.page.click('#fab');
  await desk.page.waitForSelector('#presence >> text=Working session last answered at');
  await desk.page.click('#check');
  await desk.page.waitForSelector('#presence >> text=Checking the working session');
  assert.equal(await desk.page.locator('#resumeCmd').count(), 0, 'no resume command while the check is waiting');

  await desk.page.clock.fastForward(76000);
  await desk.page.waitForSelector('#presence .gone >> text=No answer to the check sent at');
  assert.equal(await desk.page.textContent('#resumeCmd'), RESUME);
  const box = await desk.page.locator('#copyResume').boundingBox();
  const width = await desk.page.evaluate(() => innerWidth);
  assert.ok(box.x + box.width <= width, 'Copy is inside the window: right edge ' + (box.x + box.width) + ' of ' + width);
  await desk.page.click('#copyResume');
  await desk.page.waitForFunction(() => /Copied|Selected/.test(document.getElementById('copyResume').textContent));
  if (await desk.page.textContent('#copyResume') === 'Selected')
    assert.equal(await desk.page.evaluate(() => String(getSelection())), RESUME);
});

test('a Check whose ring is refused says it could not ring the working session', async () => {
  desk = await open(browser, {publishError: ['rate_limited']});
  await ready(desk);
  await desk.page.click('#fab');
  await desk.page.click('#check');
  await desk.page.waitForSelector('#presence >> text=Could not ring the working session (rate_limited).');
  assert.doesNotMatch(await desk.page.textContent('#presence'), /Checking/);
  assert.deepEqual(await desk.rings(), []);
});

/* ---- Approve asks once before it starts a merge ---- */
const HEAD = 'a1'.repeat(20);
// The page must never ask with window.confirm: a frame sandboxed without
// allow-modals answers false at once. A call throws, and afterEach sees the error.
const noConfirm = () => { window.confirm = () => { throw new Error('window.confirm was called'); }; };
const focused = () => desk.page.evaluate(() => document.activeElement && document.activeElement.id);
const pending = () => desk.page.evaluate(() => {
  const el = document.getElementById('approvePending');
  return el.hidden ? null : el.textContent;
});
const slot = (id, extra = {}) => [{id, role: 'user', content: 'Question ' + id, to: 'session'},
  {role: 'assistant', via: 'session', answers: id, status: 'sent', sentAt: 1, rungAt: 2, ...extra}];
const withTurns = (turns, replies = {}) => ({
  [PR]: {pr: 42, title: 'Harness desk', decision: null, reason: null, decidedAt: null,
    threads: [{id: 't1', name: 'Asked', turns}]},
  ...Object.fromEntries(Object.entries(replies).map(([id, [status, text]]) =>
    [PR + '/replies/' + id, {turn: id, status, text, at: '2026-09-14T10:00:00.000Z'}])),
});
const repliesLoaded = d => d.page.waitForFunction('repliesIn === true', null, {timeout: 5000});

test('one press on Approve stores and rings nothing, and opens a confirm step naming the pull request and head', async () => {
  desk = await open(browser, {data: payload({headRefOid: HEAD}), init: noConfirm});
  await ready(desk);
  const ok = await desk.page.locator('#ok').boundingBox();
  await desk.page.click('#ok');
  await desk.page.waitForTimeout(600);
  assert.deepEqual(await desk.store(), {});
  assert.deepEqual(await desk.rings(), []);
  // A double tap on Approve must not land its second tap on Confirm.
  assert.notEqual(await desk.page.evaluate(([x, y]) => (document.elementFromPoint(x, y) || {}).id,
    [ok.x + ok.width / 2, ok.y + ok.height / 2]), 'approveConfirm');

  assert.equal(await desk.page.textContent('#approveAsk'), 'Approve and merge LiLo-Labs/claude-code-plugins#42 at a1a1a1a?');
  assert.equal(await pending(), null, 'nothing is in progress, so no in-progress line');
  assert.equal(await focused(), 'approveConfirm');
  for (const [sel, name] of [['#approveConfirm', 'Confirm'], ['#approveBack', 'Back']]){
    const b = desk.page.locator(sel);
    assert.equal(await b.evaluate(el => el.tagName), 'BUTTON', sel);
    assert.equal((await b.textContent()).trim(), name);
    const box = await b.boundingBox();
    assert.ok(box.width >= 44 && box.height >= 44, sel + ' is ' + box.width + 'x' + box.height);
  }
  assert.equal(await desk.page.locator('#decide button').count(), 2, 'Confirm and Back are separate buttons');
});

test('Approve then Confirm stores approved with decidedAt, decidedOn and repo, and rings kind decision once', async () => {
  desk = await open(browser, {data: payload({headRefOid: HEAD}), init: noConfirm});
  await ready(desk);
  const before = new Date().toISOString();
  await approve(desk);
  const doc = (await desk.until(s => s[PR] && s[PR].decision === 'approved' && s[PR].decisionRing))[PR];
  assert.deepEqual(Object.keys(doc).sort(),
    ['decidedAt', 'decidedOn', 'decision', 'decisionRing', 'pr', 'reason', 'repo', 'threads', 'title', 'updatedAt']);
  // The ring's outcome is stored with the decision it rang for, so a later load
  // knows whether anything was told.
  assert.deepEqual(Object.keys(doc.decisionRing).sort(), ['decidedAt', 'rungAt']);
  assert.equal(doc.decisionRing.decidedAt, doc.decidedAt);
  assert.equal(doc.decidedOn, HEAD);
  assert.equal(doc.repo, 'LiLo-Labs/claude-code-plugins');
  assert.equal(doc.reason, null);
  assert.match(doc.decidedAt, /^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}Z$/);
  assert.ok(doc.decidedAt >= before);

  await lineSays('Waiting for the working session');
  await desk.page.waitForTimeout(600);
  const rings = await decisionRings();
  assert.equal((await desk.rings()).length, 1);
  assert.deepEqual({decision: rings[0].doorbell.decision, decidedAt: rings[0].doorbell.decidedAt},
    {decision: 'approved', decidedAt: doc.decidedAt});
  assert.match(await desk.page.textContent('#decide .done'), /You marked this approved/);
});

test('Back and Escape leave the confirm step with nothing stored or rung, and focus returns to Approve', async () => {
  desk = await open(browser, {init: noConfirm});
  await ready(desk);
  for (const leave of [() => desk.page.click('#approveBack'), () => desk.page.keyboard.press('Escape')]){
    await desk.page.click('#ok');
    await desk.page.waitForSelector('#approveConfirm');
    await leave();
    await desk.page.waitForSelector('#ok');
    assert.equal(await desk.page.locator('#approveAsk').count(), 0);
    assert.equal(await focused(), 'ok');
    assert.equal(await desk.page.isEnabled('#changes'), true);
  }
  await desk.page.waitForTimeout(600);
  assert.deepEqual(await desk.store(), {});
  assert.deepEqual(await desk.rings(), []);
});

test('a reply still being written is named in the confirm step, which clears when it finishes and does not block Confirm', async () => {
  desk = await open(browser, {seed: withTurns(slot('m1'), {m1: ['working', 'Renaming it now']}), init: noConfirm});
  await ready(desk);
  await repliesLoaded(desk);
  await desk.page.click('#ok');
  assert.equal(await pending(), '1 answer is still being written. Confirm does not wait for it.');
  assert.equal(await desk.page.isEnabled('#approveConfirm'), true);

  await desk.reply('m1', 'Renamed.', 'done');
  await desk.page.waitForFunction(() => document.getElementById('approvePending').hidden);
  assert.equal(await focused(), 'approveConfirm', 'the redraw kept focus on Confirm');
  await desk.page.click('#approveConfirm');
  await desk.until(s => s[PR] && s[PR].decision === 'approved');
});

test('a sent message with no reply is named in the confirm step, and counts add up with replies still being written', async () => {
  desk = await open(browser, {seed: withTurns(slot('m1')), init: noConfirm});
  await ready(desk);
  await repliesLoaded(desk);
  await desk.page.click('#ok');
  assert.equal(await pending(), '1 message is still waiting for the working session. Confirm does not wait for it.');
  assert.equal(await desk.page.isEnabled('#approveConfirm'), true);
  await desk.page.click('#approveBack');
  await desk.close();

  desk = await open(browser, {init: noConfirm, seed: withTurns(
    [...slot('m1'), ...slot('m2'), ...slot('m3'), ...slot('m4')],
    {m1: ['working', 'One'], m2: ['working', 'Two'], m4: ['done', 'Answered']})});
  await ready(desk);
  await repliesLoaded(desk);
  await desk.page.click('#ok');
  assert.equal(await pending(), '2 answers are still being written and 1 message is still waiting for '
    + 'the working session. Confirm does not wait for them.');
  await desk.page.click('#approveConfirm');
  await desk.until(s => s[PR] && s[PR].decision === 'approved');
  assert.deepEqual(await desk.store().then(s => Object.keys(s).filter(k => k.includes('/replies/')).length), 3);
});

test('with the replies unreadable, the confirm step says it cannot tell whether an answer is still coming', async () => {
  desk = await open(browser, {seed: withTurns(slot('m1')), init: noConfirm,
    subscribeFailures: {[PR + '/replies']: ['not_granted']}});
  await ready(desk);
  await desk.page.waitForFunction('FEEDS.replies && FEEDS.replies.dead === "not_granted"');
  await desk.page.click('#ok');
  assert.match(await pending(), /replies have not loaded on this view, so it cannot tell whether an answer is still coming/);
  assert.equal(await desk.page.isEnabled('#approveConfirm'), true);
});

test('a held Enter on Approve stops at the confirm step, and a fresh Enter on Confirm records', async () => {
  desk = await open(browser, {init: noConfirm});
  await ready(desk);
  await desk.page.focus('#ok');
  // keyboard.down on a key already down sends it as an auto-repeat.
  await desk.page.keyboard.down('Enter');
  await desk.page.waitForSelector('#approveConfirm');
  for (let i = 0; i < 5; i++){ await desk.page.keyboard.down('Enter'); await desk.page.waitForTimeout(30); }
  await desk.page.keyboard.up('Enter');
  await desk.page.waitForTimeout(600);
  assert.equal(await desk.page.locator('#approveAsk').count(), 1, 'the repeats left the confirm step up');
  assert.deepEqual(await desk.store(), {});
  assert.deepEqual(await desk.rings(), []);

  assert.equal(await focused(), 'approveConfirm');
  await desk.page.keyboard.press('Enter');
  await desk.until(s => s[PR] && s[PR].decision === 'approved');
});
