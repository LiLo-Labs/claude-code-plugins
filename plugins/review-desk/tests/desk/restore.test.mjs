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

// Whether some element outside the chat panel is on screen and says `source`.
// The panel is closed in these tests, so its banner is not on screen; what the
// reviewer sees has to come from the page itself.
const onPage = source => {
  const re = new RegExp(source);
  return [...document.querySelectorAll('body *')].some(el => !el.closest('#panel')
    && el.checkVisibility() && re.test(el.innerText || ''));
};
const shownOnPage = (desk, source, timeout = 5000) =>
  desk.page.waitForFunction(onPage, source, {timeout});
const enabled = (desk, sel, timeout = 5000) =>
  desk.page.waitForFunction(s => !document.querySelector(s).disabled, sel, {timeout});
const PAGE_FEEDS = ['/context/body', '/presence', '/context/pickup', '/documents'];

test('with the panel closed, a failed restore says so beside the decision, and Try again there loads it', async () => {
  desk = await open(browser, {seed: decidedDesk(), getFailures: 2});
  await shownOnPage(desk, 'could not be read');
  assert.equal(await desk.page.evaluate(() => document.body.classList.contains('open')), false);
  assert.ok(await desk.page.isDisabled('#ok'));
  assert.ok(await desk.page.isDisabled('#changes'));
  const retry = desk.page.locator('#decide').getByRole('button', {name: 'Try again'});
  assert.ok(await retry.isVisible());

  await retry.click();
  // The stored decision comes back, so the slab turns to it.
  await desk.page.waitForSelector('#decide >> text=approved');
  assert.equal(await desk.page.evaluate(onPage, 'could not be read'), false);
  assert.equal(await desk.page.textContent('#lostSlot'), '');
  await desk.page.click('#redo');
  await enabled(desk, '#ok');
  assert.equal(reads(await desk.log()), 3);
  assert.deepEqual(writes(await desk.log()), []);
  assert.deepEqual(desk.errors, []);
});

test('Try again beside the decision enables Approve when the store has nothing saved yet', async () => {
  desk = await open(browser, {seed: {}, getFailures: 2});
  await shownOnPage(desk, 'could not be read');
  await desk.page.locator('#decide').getByRole('button', {name: 'Try again'}).click();
  await enabled(desk, '#ok');
  assert.equal(await desk.page.textContent('#decideState'), '');
  assert.deepEqual(desk.errors, []);
});

test('with the panel closed, a slow restore says the saved discussion is loading beside the decision', async () => {
  desk = await open(browser, {seed: decidedDesk(), getDelay: 4000});
  await desk.page.waitForTimeout(1000);
  assert.ok(await desk.page.evaluate(onPage, 'Loading the saved discussion'));
  assert.ok(await desk.page.isDisabled('#ok'));
  await desk.page.waitForSelector('#decide >> text=approved', {timeout: 6000});
  assert.equal(await desk.page.evaluate(onPage, 'Loading the saved discussion'), false);
  assert.deepEqual(desk.errors, []);
});

test('malformed stored threads do not stop the page: controls come on and every listener starts', async () => {
  const seed = {[PR]: {pr: 42, title: 'Harness desk', threads: [null, {turns: {}}]}};
  desk = await open(browser, {seed});
  await enabled(desk, '#ok');
  await enabled(desk, '#send');
  await desk.page.waitForFunction(paths => paths.every(p =>
    window.__desk.log().some(e => e.op === 'subscribe' && e.path === p)),
    [...PAGE_FEEDS, '/replies'].map(p => PR + p));
  assert.equal(await desk.page.evaluate(onPage, 'could not be read|Loading the saved'), false);
  await desk.page.waitForTimeout(600);
  assert.deepEqual(writes(await desk.log()), []);
  assert.deepEqual(await desk.store(), seed);
  assert.deepEqual(desk.errors, []);
});

test('bad threads and turns are skipped in memory, and the store keeps them until the reviewer sends', async () => {
  const seed = {[PR]: {pr: 42, title: 'Harness desk', threads: [
    null, 'stray',
    {id: 't1', name: 'Kept', turns: [null, 7, ['x'],
      {id: 'm-old', role: 'user', content: 'Still here', to: 'session'}]},
    {turns: {}}]}};
  desk = await open(browser, {seed});
  await desk.page.click('#fab');
  await desk.page.waitForSelector('#stream >> text=Still here');
  assert.deepEqual(await desk.page.$$eval('#tabs .tab', b => b.map(x => x.textContent)), ['Kept', 'Thread 2']);
  await desk.page.waitForTimeout(600);
  assert.deepEqual(writes(await desk.log()), [], 'restoring writes nothing back');
  assert.deepEqual(await desk.store(), seed);

  await desk.page.fill('#box', 'Asked after the odd load');
  await desk.page.press('#box', 'Enter');
  const store = await desk.until(s => asked(s).includes('Asked after the odd load'));
  assert.deepEqual(asked(store), ['Still here', 'Asked after the odd load']);
  assert.deepEqual(store[PR].threads.map(t => t.name), ['Kept', 'Thread 2']);
  assert.deepEqual(desk.errors, []);
});

test('a restore that throws before it reads still shows Try again, and the page feeds start', async () => {
  // db.doc throws once, on the main document, as a store refusing the path would.
  const init = () => {
    const real = window.claude;
    let thrown = false;
    window.claude = {use: async name => {
      const got = await real.use(name);
      if (name !== 'db' || !got) return got;
      return {collection: p => got.collection(p), doc: p => {
        if (!thrown && p === 'review/pr-42'){ thrown = true; throw new TypeError('stubbed doc throw'); }
        return got.doc(p);
      }};
    }};
  };
  desk = await open(browser, {seed: decidedDesk(), init});
  await shownOnPage(desk, 'could not be read \\(stubbed doc throw\\)');
  await desk.page.waitForFunction(paths => paths.every(p =>
    window.__desk.log().some(e => e.op === 'subscribe' && e.path === p)),
    PAGE_FEEDS.map(p => PR + p));
  await desk.page.locator('#decide').getByRole('button', {name: 'Try again'}).click();
  await desk.page.waitForSelector('#decide >> text=approved');
  assert.equal(await desk.subscribes(PR + '/replies'), 1);
  for (const p of PAGE_FEEDS) assert.equal(await desk.subscribes(PR + p), 1, 'started once: ' + p);
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

// Two open views. View A sends and rings; the ring reloads view B, which reads
// the slot before A has stored rungAt. B must see A's rungAt before ringing,
// and must not write its load-time copy over what A stored.
const LEASE = PR + '/rering/lease';
const pageSets = log => log.filter(e => e.op === 'set' && e.by === 'page');
const unrungDesk = (slot, extra = []) => ({pr: 42, title: 'Harness desk', decision: null,
  reason: null, decidedAt: null, threads: [{id: 't1', name: 'A', turns: [
    {id: 'm-a', role: 'user', content: 'Sent from view A', to: 'session'},
    {role: 'assistant', via: 'session', answers: 'm-a', content: '', ...slot}]}, ...extra]});

test('a view reloaded by another view\'s ring does not ring again once that view stores rungAt', async () => {
  const sentAt = Date.now() - 2000;
  desk = await open(browser, {seed: {[PR]: unrungDesk({status: 'sent', sentAt})}});
  await desk.page.click('#fab');
  await desk.page.waitForSelector('text=Sent from view A');
  await desk.page.waitForTimeout(700);
  // A's second save lands, and A has also renamed the thread: a save-only change
  // that B's load-time copy does not have.
  const fromA = unrungDesk({status: 'sent', sentAt, rungAt: sentAt + 400});
  fromA.threads[0].name = 'Renamed in A';
  await desk.write(PR, fromA);

  await desk.page.waitForTimeout(10000);             // past RERING_AFTER from sentAt
  assert.deepEqual(await desk.rings(), []);
  assert.deepEqual(pageSets(await desk.log()), []);
  assert.deepEqual((await desk.store())[PR], fromA);
  // B takes the stored outcome, so it stops saying it is still ringing.
  assert.match(await desk.page.textContent('#stream'), /Saved and rung/);
  assert.deepEqual(desk.errors, []);
});

test('a slot another view holds the ring lease for is not rung while the lease lasts', async () => {
  const slot = {status: 'unsent', why: 'conflict', sentAt: Date.now() - 3000};
  desk = await open(browser, {seed: {[PR]: unrungDesk(slot)}, leases: {[LEASE]: 1500}});
  await desk.page.waitForTimeout(800);
  assert.deepEqual(await desk.rings(), [], 'the lease holder is ringing');
  // The holder's outcome lands before its lease runs out.
  const rung = unrungDesk({status: 'sent', sentAt: slot.sentAt, rungAt: Date.now()});
  await desk.write(PR, rung);
  await desk.page.waitForTimeout(2000);
  assert.deepEqual(await desk.rings(), []);
  assert.deepEqual(pageSets(await desk.log()), []);
  assert.deepEqual((await desk.store())[PR], rung);
  // Nothing rang because the view asked and was refused, not because it never
  // looked; and it then took the holder's stored outcome.
  assert.ok((await desk.log()).some(e => e.op === 'acquire' && e.path === LEASE), 'the view asked for the lease');
  assert.match(await desk.page.textContent('#stream'), /Saved and rung/);
  assert.deepEqual(desk.errors, []);
});

// rering reads the stored document and writes the ring outcome into that copy.
// A message sent from the same view between that read and that write must
// survive the write.
test('a message sent while a re-ring is storing its outcome is not overwritten', async () => {
  const slot = {status: 'unsent', why: 'conflict', sentAt: Date.now() - 60000};
  desk = await open(browser, {seed: {[PR]: unrungDesk(slot)}, getDelay: 1500});
  await desk.page.click('#fab');
  await desk.page.waitForSelector('text=Sent from view A');
  // Restore read, lease read, ring, then the read the outcome is written into.
  for (const end = Date.now() + 8000;;){
    const log = await desk.log();
    const ringAt = log.findIndex(e => e.op === 'publish');
    if (ringAt >= 0 && log.slice(ringAt).some(e => e.op === 'get' && e.path === PR)) break;
    if (Date.now() > end) throw new Error('rering never re-read after ringing');
    await new Promise(r => setTimeout(r, 25));
  }
  await desk.page.fill('#box', 'Sent during the re-ring');
  await desk.page.press('#box', 'Enter');

  await desk.page.waitForTimeout(2500);               // past the outcome read and its write
  const store = await desk.store();
  assert.deepEqual(asked(store), ['Sent from view A', 'Sent during the re-ring']);
  assert.ok(turnsIn(store).find(m => m.answers === 'm-a').rungAt, 'the re-ring outcome is stored');
  const rings = await desk.rings();
  assert.deepEqual(rings.map(r => r.doorbell.turns || [r.doorbell.turn]),
    [['m-a'], [turnsIn(store).find(m => m.content === 'Sent during the re-ring').id]]);
  assert.match(await desk.page.textContent('#stream'), /Saved and rung/);
  assert.deepEqual(desk.errors, []);
});

test('when the lease holder never stores an outcome, the slot is rung once into the stored document', async () => {
  const slot = {status: 'unsent', why: 'conflict', sentAt: Date.now() - 3000};
  desk = await open(browser, {seed: {[PR]: unrungDesk(slot)}, leases: {[LEASE]: 1500}});
  await desk.page.waitForTimeout(500);
  // Another view adds a thread meanwhile; the ring outcome must not undo it.
  const later = unrungDesk(slot, [{id: 't2', name: 'Opened in another view', turns: []}]);
  await desk.write(PR, later);

  const store = await desk.until(s => turnsIn(s).some(m => m.answers === 'm-a' && m.rungAt), null, 5000);
  await desk.page.waitForTimeout(800);
  const rings = await desk.rings();
  assert.equal(rings.length, 1);
  assert.deepEqual(rings[0].doorbell.turns, ['m-a']);
  assert.deepEqual(store[PR].threads.map(t => t.name), ['A', 'Opened in another view']);
  const stored = turnsIn(store).find(m => m.answers === 'm-a');
  assert.equal(stored.status, 'sent');
  assert.equal(stored.why, undefined);
  assert.deepEqual(desk.errors, []);
});

// The re-ring outcome is written by the view on its own, not by the reviewer, so
// it must leave entries it cannot read exactly as they are stored.
test('a re-ring into a document with malformed threads stores its outcome and keeps them as they were', async () => {
  const slot = {status: 'unsent', why: 'conflict', sentAt: Date.now() - 60000};
  desk = await open(browser, {seed: {[PR]: unrungDesk(slot, [null, {turns: {}}])}});
  const store = await desk.until(s => s[PR].threads[0].turns.some(m => m.answers === 'm-a' && m.rungAt));
  assert.equal(store[PR].threads[1], null);
  assert.deepEqual(store[PR].threads[2], {turns: {}});
  assert.equal((await desk.rings()).length, 1);
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
