// The four things this desk is for, and nothing else: it shows the request, it
// shows what the session is doing, a question about a passage reaches that
// session, and a decision is recorded with the commit it was made on.
//
// None of these tests sleeps. The machinery that could only be tested by waiting
// -- rings, re-rings, backoffs, leases -- is what v2 deleted.
import {test, before, after, afterEach} from 'node:test';
import assert from 'node:assert/strict';
import {launch, open, payload, approve} from './harness.mjs';

const PR = 'review/pr-42';
const HEAD = 'd7614c6a29796f1992a23fbfd8129c044f425955';

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
const steps = () => desk.page.$$eval('#work .step',
  els => els.map(e => [e.className.replace('step ', ''),
    e.querySelector('.what').textContent.replace(/^[a-z ]+/, '')]));
const decideText = () => desk.page.textContent('#decide');

/* ---------------- it shows the request ---------------- */

test('the request, its commit, and every carried file it was published with', async () => {
  desk = await open(browser, {data: payload({headRefOid: HEAD, summary: '2 files, no code',
    body: '## What it does\n\nIt states the rule.\n',
    documents: [{name: 'docs/spec.md', text: '# Spec\n\nOne rule.', base: '# Spec\n\nOne rule.'}]})});
  await ready(desk);
  assert.equal(await desk.page.textContent('#title'), 'Harness desk');
  assert.match(await desk.page.textContent('#meta'), /2 files, no code/);
  assert.match(await desk.page.textContent('#meta'), /d7614c6/, 'the commit being judged');
  assert.equal(await desk.page.locator('.leaf').count(), 2, 'the request, and the one document');
  assert.match(await desk.page.textContent('#sheet'), /It states the rule/);
  await desk.page.click('[data-leaf="1"]');
  assert.match(await desk.page.textContent('#sheet h1'), /Spec/);
  assert.match(await desk.page.textContent('footer'), /review desk \d+\.\d+\.\d+/);
});

/* ---------------- it shows what the session is doing ---------------- */

test('the session’s work appears as it writes it, in its own order', async () => {
  desk = await open(browser);
  await ready(desk);
  assert.match(await desk.page.textContent('#work'), /Nothing from the session yet/);

  // Written from outside the page, as the session's write_db lands. Out of
  // order on purpose: the page sorts by the session's own numbering.
  await desk.write(PR + '/progress/0002',
    {id: '0002', at: '2026-09-18T17:40:00Z', kind: 'found', text: 'The tests pass on the branch.'});
  await desk.write(PR + '/progress/0001',
    {id: '0001', at: '2026-09-18T17:39:00Z', kind: 'doing', text: 'Running the suites.'});
  await desk.page.waitForFunction(() => document.querySelectorAll('#work .step').length === 2);

  assert.deepEqual(await steps(), [['doing', 'Running the suites.'],
                                   ['found', 'The tests pass on the branch.']]);
  assert.equal(await desk.page.$eval('#pulse', el => el.hidden), false, 'something is in progress');

  await desk.write(PR + '/progress/0003',
    {id: '0003', at: '2026-09-18T17:41:00Z', kind: 'done', text: 'Pushed as 438a1c8.'});
  await desk.page.waitForFunction(() => document.querySelectorAll('#work .step').length === 3);
  assert.deepEqual((await steps())[2], ['done', 'Pushed as 438a1c8.']);
});

test('a row with no text is not a step, and the page says nothing rather than something empty', async () => {
  desk = await open(browser);
  await ready(desk);
  await desk.write(PR + '/progress/0001', {id: '0001', kind: 'doing'});
  await desk.page.waitForTimeout(150);
  assert.equal(await desk.page.locator('#work .step').count(), 0);
  assert.match(await desk.page.textContent('#work'), /Nothing from the session yet/);
});

/* ---------------- a question reaches the session ---------------- */

test('a question carries the passage, the reviewer’s words, and an instruction not to guess', async () => {
  desk = await open(browser, {data: payload({body: '## Rule\n\nAt most one phase may be open.\n'})});
  await ready(desk);
  assert.match(await desk.page.textContent('#askState'), /A session is listening/);
  assert.equal(await desk.page.$eval('#ask', el => el.disabled), true, 'nothing typed yet');

  // Select the passage, the way a reviewer does before asking about it.
  await desk.page.evaluate(() => {
    const p = [...document.querySelectorAll('#sheet p')].find(x => x.textContent.includes('one phase'));
    const r = document.createRange();
    r.selectNodeContents(p);
    const s = window.getSelection();
    s.removeAllRanges();
    s.addRange(r);
  });
  await desk.page.waitForFunction(() =>
    document.getElementById('ask').textContent.includes('what you selected'));
  assert.match(await desk.page.textContent('#quoted'), /At most one phase may be open/);

  await desk.page.fill('#question', 'Is this one requirement or two?');
  await desk.page.click('#ask');
  const sent = await desk.page.evaluate(() => window.__desk.sent());
  assert.equal(sent.length, 1);
  assert.match(sent[0].text, /^User states from the desk, on “At most one phase may be open\.”:/);
  assert.match(sent[0].text, /Is this one requirement or two\?/);
  // The instruction that makes the quick reply a receipt rather than a guess.
  assert.match(sent[0].text, /Do not answer this from context/);
  assert.match(sent[0].text, /Reply with exactly: "Taken to the session\."/);
  assert.match(sent[0].text, /with the repository and its tools/);
  assert.ok(sent[0].anchor, 'anchored to the passage');

  assert.equal(await desk.page.inputValue('#question'), '', 'the box is cleared once sent');
  assert.match(await desk.page.textContent('#askState'), /answers in the thread on this page/);
});

test('with nothing selected the question is about the page being read', async () => {
  desk = await open(browser, {data: payload({
    documents: [{name: 'docs/spec.md', text: '# Spec\n\nOne rule.', base: null}]})});
  await ready(desk);
  await desk.page.click('[data-leaf="1"]');
  await desk.page.fill('#question', 'Why is this file here at all?');
  await desk.page.click('#ask');
  const sent = await desk.page.evaluate(() => window.__desk.sent());
  assert.match(sent[0].text, /^User states from the desk, on docs\/spec\.md:/);
});

test('when no session is listening the page says so, and will not send', async () => {
  // The answer the old desk never had: it rang its doorbell into the dark.
  desk = await open(browser, {listening: 'no_session'});
  await ready(desk);
  await desk.page.fill('#question', 'Anyone there?');
  assert.equal(await desk.page.$eval('#ask', el => el.disabled), true);
  assert.match(await desk.page.textContent('#askState'), /No session is listening right now/);
  assert.deepEqual(await desk.page.evaluate(() => window.__desk.sent()), []);
});

test('a refusal keeps the reviewer’s words and says what happened', async () => {
  desk = await open(browser, {sendToClaudeError: 'claude_unavailable'});
  await ready(desk);
  await desk.page.fill('#question', 'Does the head still match?');
  await desk.page.click('#ask');
  await desk.page.waitForFunction(() =>
    document.getElementById('askState').textContent.includes('could not reach a session'));
  assert.match(await desk.page.textContent('#askState'), /nothing was posted/);
  assert.equal(await desk.page.inputValue('#question'), 'Does the head still match?',
    'the question is not thrown away');
});

test('consent not yet given is said as itself, not as a failure', async () => {
  desk = await open(browser, {sendToClaudeError: 'consent_required'});
  await ready(desk);
  await desk.page.fill('#question', 'Why this bound?');
  await desk.page.click('#ask');
  await desk.page.waitForFunction(() =>
    document.getElementById('askState').textContent.includes('Allow this page to comment'));
  assert.equal(await desk.page.inputValue('#question'), 'Why this bound?');
});

test('a view that cannot comment at all says that, rather than failing when pressed', async () => {
  desk = await open(browser, {capabilities: ['db', 'artifact']});
  await ready(desk);
  assert.equal(await desk.page.$eval('#ask', el => el.disabled), true);
  assert.match(await desk.page.textContent('#askState'), /not available in this view/);
});

/* ---------------- and a decision, on a commit ---------------- */

test('Approve asks once more, then stores the decision with the commit shown', async () => {
  desk = await open(browser, {data: payload({headRefOid: HEAD})});
  await ready(desk);
  await desk.page.click('#approve');
  assert.match(await decideText(), /Approve this request at commit d7614c6/);
  assert.match(await decideText(), /merges that commit and nothing newer/);

  await desk.page.click('#confirm');
  const doc = (await desk.until(s => s[PR] && s[PR].decision === 'approved'))[PR];
  assert.equal(doc.decidedOn, HEAD, 'the commit the reviewer was shown');
  assert.match(doc.decidedAt, /^\d{4}-\d\d-\d\dT/);
  assert.equal(doc.reason, null);
  assert.match(doc.page, /^\d+\.\d+\.\d+$/, 'which page recorded it');
  assert.match(await decideText(), /Approved at commit d7614c6/);
  assert.match(await decideText(), /Waiting for the session/);
});

test('Back leaves nothing recorded', async () => {
  desk = await open(browser);
  await ready(desk);
  await desk.page.click('#approve');
  await desk.page.click('#back');
  await desk.page.waitForSelector('#approve');
  assert.deepEqual(Object.keys(await desk.store()), [], 'nothing was written');
});

test('Needs changes records the reviewer’s own words, and nothing without them', async () => {
  desk = await open(browser);
  await ready(desk);
  await desk.page.click('#changes');
  await desk.page.click('#recordReason');
  assert.deepEqual(Object.keys(await desk.store()), [], 'no reason, no decision');

  await desk.page.fill('#why', 'REQ-15 is two requirements in one sentence.');
  await desk.page.click('#recordReason');
  const doc = (await desk.until(s => s[PR] && s[PR].decision === 'needs changes'))[PR];
  assert.equal(doc.reason, 'REQ-15 is two requirements in one sentence.');
  assert.equal(doc.decidedOn, undefined, 'only an approval pins a commit');
  assert.match(await decideText(), /REQ-15 is two requirements/);
});

test('what the session did with the decision shows under it', async () => {
  desk = await open(browser, {data: payload({headRefOid: HEAD})});
  await ready(desk);
  await approve(desk);
  const doc = (await desk.until(s => s[PR] && s[PR].decision === 'approved'))[PR];

  // The session's pickup, then its outcome, as /review-collect writes them.
  await desk.write(PR + '/context/pickup',
    {decision: 'approved', decidedAt: doc.decidedAt, session: 's', at: '2026-09-18T18:00:00Z'});
  await desk.page.waitForFunction(() =>
    document.getElementById('decide').textContent.includes('Picked up by the session'));

  await desk.write(PR + '/context/pickup',
    {decision: 'approved', decidedAt: doc.decidedAt, session: 's', at: '2026-09-18T18:00:00Z',
     outcome: {result: 'merged', at: '2026-09-18T18:02:00Z', detail: 'Squash-merged as 67ae750'}});
  await desk.page.waitForFunction(() =>
    document.getElementById('decide').textContent.includes('Merged'));
  assert.match(await decideText(), /Squash-merged as 67ae750/);
});

test('a decision made on another device shows here', async () => {
  desk = await open(browser, {data: payload({headRefOid: HEAD})});
  await ready(desk);
  await desk.write(PR, {pr: 42, decision: 'approved', decidedAt: '2026-09-18T17:00:00Z',
    decidedOn: HEAD, reason: null});
  await desk.page.waitForFunction(() =>
    document.getElementById('decide').textContent.includes('Approved'));
  assert.match(await decideText(), /Approved at commit d7614c6/);
  assert.equal(await desk.page.locator('#approve').count(), 0, 'not asked to decide twice');
});

test('a refused write says the decision did not reach the session', async () => {
  desk = await open(browser);
  await ready(desk);
  await desk.failSets(PR, ['unavailable']);
  await desk.page.click('#approve');
  await desk.page.click('#confirm');
  await desk.page.waitForSelector('#lost .lost');
  assert.match(await desk.page.textContent('#lost'), /not saved \(unavailable\)/);
  assert.match(await desk.page.textContent('#lost'), /Tell the session directly/);
});
