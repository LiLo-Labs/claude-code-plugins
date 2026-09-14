// An approval is of the commit the reviewer read. The page stores the head it
// was showing as decidedOn, and /review-collect merges only while GitHub's head
// is still that commit, so these pin what the page stores and shows.
import {test, before, after, afterEach} from 'node:test';
import assert from 'node:assert/strict';
import {launch, open, payload} from './harness.mjs';

const PR = 'review/pr-42';
const A = 'a1'.repeat(20), B = 'b2'.repeat(20);

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

const stored = async () => (await desk.store())[PR];
const turnsIn = doc => ((doc && doc.threads) || []).flatMap(t => t.turns);

test('Approve stores the head the page shows as decidedOn, and the repo', async () => {
  desk = await open(browser, {data: payload({headRefOid: A})});
  assert.match(await desk.page.textContent('#meta'), /commit a1a1a1a/);
  await desk.page.click('#ok');
  const doc = (await desk.until(s => s[PR] && s[PR].decision === 'approved'))[PR];
  assert.equal(doc.decidedOn, A);
  assert.equal(doc.repo, 'LiLo-Labs/claude-code-plugins');
  assert.equal(await desk.page.locator('#newerHead').count(), 0);
  assert.equal(await desk.page.locator('#staleHead').count(), 0);
});

test('a head written with the description moves what a later decision stores', async () => {
  desk = await open(browser, {data: payload({headRefOid: A})});
  await desk.page.click('#ok');
  const first = (await desk.until(s => s[PR] && s[PR].decidedOn === A))[PR];

  // The session pushes a fixup and rewrites the description with the new head.
  await desk.context('body', {text: '## Changed since you opened this\n\n- b2b2b2b fixup\n', head: B});
  await desk.page.waitForSelector('#newerHead');
  assert.match(await desk.page.textContent('#meta'), /commit b2b2b2b/);
  assert.match(await desk.page.textContent('#newerHead'), /newer commit.*was a1a1a1a/);
  assert.match(await desk.page.textContent('#staleHead'), /approved commit a1a1a1a.*now shows b2b2b2b/);

  // A save after the push carries the decision as it was made: on the old head.
  await desk.page.click('#fab');
  await desk.page.fill('#box', 'Saw the fixup');
  await desk.page.press('#box', 'Enter');
  const resaved = (await desk.until(s => turnsIn(s[PR]).some(m => m.content === 'Saw the fixup')))[PR];
  assert.equal(resaved.decidedOn, A);
  assert.equal(resaved.decidedAt, first.decidedAt);
  await desk.page.click('#shut');

  // Deciding again stores the head the page was showing at the new decidedAt.
  await desk.page.click('#redo');
  await desk.page.click('#ok');
  const again = (await desk.until(s => s[PR] && s[PR].decidedAt !== first.decidedAt
    && s[PR].decision === 'approved'))[PR];
  assert.equal(again.decidedOn, B);
  assert.equal(await desk.page.locator('#staleHead').count(), 0);
});

// The recovery /review-collect performs for a head block: it writes the head it
// read into context/body before reporting blocked, so deciding again is on the
// new commit. Without that write the page kept storing the old one (the second
// half of this test), and every collection blocked it again.
test('a head block clears once the collector writes the head, and not before', async () => {
  desk = await open(browser, {data: payload({headRefOid: A})});
  await desk.page.click('#ok');
  const first = (await desk.until(s => s[PR] && s[PR].decidedOn === A))[PR];
  const blocked = decidedAt => ({decision: 'approved', decidedAt, session: 's', at: new Date().toISOString(),
    outcome: {result: 'blocked', at: new Date().toISOString(),
      detail: 'New commits since you approved (a1a1a1a..b2b2b2b), so this was not merged.'}});

  // A text-only rewrite, as the after-push reminder used to ask for: the head stays.
  await desk.context('body', {text: '## Changed since you opened this\n\n- b2b2b2b fixup\n'});
  await desk.context('pickup', blocked(first.decidedAt));
  await desk.page.waitForSelector('text=could not finish');
  assert.match(await desk.page.textContent('#meta'), /commit a1a1a1a/);
  await desk.page.click('#redo');
  await desk.page.click('#ok');
  const stuck = (await desk.until(s => s[PR] && s[PR].decidedAt !== first.decidedAt
    && s[PR].decision === 'approved'))[PR];
  assert.equal(stuck.decidedOn, A, 'with no head in context/body the page can only store the old commit');

  // The collector's recovery: the head it read, then the blocked outcome.
  await desk.context('body', {text: '## Changed since you opened this\n\n- b2b2b2b fixup\n', head: B});
  await desk.context('pickup', blocked(stuck.decidedAt));
  await desk.page.waitForSelector('#newerHead');
  assert.match(await desk.page.textContent('#meta'), /commit b2b2b2b/);
  await desk.page.click('#redo');
  await desk.page.click('#ok');
  const again = (await desk.until(s => s[PR] && s[PR].decidedAt !== stuck.decidedAt
    && s[PR].decision === 'approved'))[PR];
  assert.equal(again.decidedOn, B);
});

test('a body without a well-formed head leaves the head alone', async () => {
  desk = await open(browser, {data: payload({headRefOid: A}),
    seed: {[PR + '/context/body']: {text: 'Rewritten, no head'}}});
  await desk.page.waitForSelector('text=Rewritten, no head');
  await desk.context('body', {text: 'Rewritten again', head: B.toUpperCase()});
  await desk.page.waitForSelector('text=Rewritten again');
  assert.equal(await desk.page.locator('#newerHead').count(), 0);
  await desk.page.click('#ok');
  assert.equal((await desk.until(s => s[PR] && s[PR].decision === 'approved'))[PR].decidedOn, A);
});

test('a page built without a head stores no decidedOn', async () => {
  desk = await open(browser);
  await desk.page.click('#ok');
  const doc = (await desk.until(s => s[PR] && s[PR].decision === 'approved'))[PR];
  assert.equal('decidedOn' in doc, false);
  assert.doesNotMatch(await desk.page.textContent('#meta'), /commit/);
});

test('a restored decision keeps the decidedOn it was stored with, or none', async () => {
  const decided = extra => ({[PR]: {pr: 42, title: 'Harness desk', decision: 'approved', reason: null,
    decidedAt: '2026-09-12T10:00:00.000Z', ...extra,
    threads: [{id: 't1', name: 'Earlier', turns: [{id: 'm-old', role: 'user', content: 'Asked yesterday', to: 'session'}]}]}});

  // Approved on A; the desk was republished on B since, so the page says so.
  desk = await open(browser, {data: payload({headRefOid: B}), seed: decided({decidedOn: A})});
  await desk.page.waitForSelector('#staleHead');
  await desk.page.click('#fab');
  await desk.page.fill('#box', 'After the reload');
  await desk.page.press('#box', 'Enter');
  let doc = (await desk.until(s => turnsIn(s[PR]).some(m => m.content === 'After the reload')))[PR];
  assert.equal(doc.decidedOn, A);
  await desk.close();

  // A desk saved before decidedOn existed: /review-collect merges it as before,
  // so the page must not invent one for the old decision.
  desk = await open(browser, {data: payload({headRefOid: B}), seed: decided({})});
  await desk.page.click('#fab');
  await desk.page.waitForSelector('text=Asked yesterday');
  await desk.page.fill('#box', 'After the reload');
  await desk.page.press('#box', 'Enter');
  doc = (await desk.until(s => turnsIn(s[PR]).some(m => m.content === 'After the reload')))[PR];
  assert.equal('decidedOn' in doc, false);
  assert.equal(await desk.page.locator('#staleHead').count(), 0);
});
