// The decision loop past Approve: Needs changes and its reason, Change this, the
// line under a recorded decision as the working session picks it up and reports
// what happened, and Check in the panel. The session's side is written the way
// /review-desk and /review-collect write it: a set of context/pickup, then the
// outcome, and a presence stamp for each ring it handles.
import {test, before, after, afterEach} from 'node:test';
import assert from 'node:assert/strict';
import {launch, open} from './harness.mjs';

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
  await desk.page.click('#ok');
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
  await desk.page.click('#ok');
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

test('Approve whose ring is refused says the view could not notify the working session, with the code', async () => {
  for (const code of ['rate_limited', 'not_granted', 'upstream_error', 'not_writer']){
    desk = await open(browser, {publishError: code});
    await ready(desk);
    await desk.page.click('#ok');
    await desk.until(s => s[PR] && s[PR].decision === 'approved');
    await lineSays('could not notify');
    assert.equal(await line(), 'Saved, but this view could not notify the working session (' + code
      + '). If no session is running, the next one to start picks it up.', code);
    assert.deepEqual(await desk.rings(), [], code);
    assert.equal((await desk.log()).filter(e => e.op === 'publish refused').length, 1, code + ' was retried');
    if (code !== 'not_writer'){
      assert.deepEqual(await desk.missing(), []);
      assert.deepEqual(desk.errors, []);
      await desk.close();
    }
  }
});

test('a view that cannot ring records a decision and says it could not notify the working session', async () => {
  desk = await open(browser, {capabilities: ['db']});
  await ready(desk);
  await desk.page.click('#ok');
  await desk.until(s => s[PR] && s[PR].decision === 'approved');
  await lineSays('could not notify');
  assert.match(await line(), /^Saved, but this view could not notify the working session \(unavailable\)\./);
});

test('a view that cannot reach the store says no session will see the decision', async () => {
  desk = await open(browser, {capabilities: []});
  await desk.page.waitForFunction('restore === "nostore"');
  await desk.page.click('#ok');
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
