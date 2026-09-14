// What the page stores, and when. review/pr-N holds the reviewer's turns and where
// each message has got to; the working session's words live only in replies/.
// Nothing but a reviewer's own action writes review/pr-N, so an open view that
// only watches never rewrites what another view saved. And every live listener
// says so when it dies, instead of leaving the panel waiting for good.
import {test, before, after, afterEach} from 'node:test';
import assert from 'node:assert/strict';
import {launch, open, openPair} from './harness.mjs';

let browser, desk, pair;
before(async () => { browser = await launch(); });
after(async () => { await browser.close(); });
afterEach(async () => {
  const views = pair || (desk ? [desk] : []);
  for (const d of views)
    assert.deepEqual(await d.missing(), [], 'the page called something the stub does not implement');
  if (views.length) await views[0].close();
  desk = null; pair = null;
});

const PR = 'review/pr-42';
const REPLIES = PR + '/replies';
const turnsIn = store => ((store[PR] && store[PR].threads) || []).flatMap(t => t.turns);
const asked = store => turnsIn(store).filter(m => m.role === 'user').map(m => m.content);
const slots = store => turnsIn(store).filter(m => m.via === 'session');
const prSets = (log, from = 0) => log.slice(from).filter(e => e.op === 'set' && e.path === PR);
const AT = '2026-09-13T10:00:00.000Z';

// A desk as this version saves it: no answer text anywhere in review/pr-N.
const leanDesk = () => ({
  [PR]: {pr: 42, title: 'Harness desk', decision: null, reason: null, decidedAt: null, threads: [
    {id: 't1', name: 'First', turns: [
      {id: 'u1', role: 'user', content: 'Why a lease?', to: 'session'},
      {role: 'assistant', via: 'session', answers: 'u1', status: 'sent', sentAt: 1000, rungAt: 1400}]},
    {id: 't2', name: 'Second', turns: [
      {id: 'u2', role: 'user', content: 'What did you reject?', to: 'session'},
      {role: 'assistant', via: 'session', answers: 'u2', status: 'sent', sentAt: 2000, rungAt: 2400}]}]},
  [REPLIES + '/u1']: {turn: 'u1', status: 'done', text: 'Because **two views** ring.', at: AT},
  [REPLIES + '/u2']: {turn: 'u2', status: 'done', text: 'A document per turn.', at: AT},
});

test('twenty reply rewrites write nothing to review/pr-N', async () => {
  desk = await open(browser);
  await desk.page.click('#fab');
  await desk.page.fill('#box', 'Do the tests pass?');
  await desk.page.press('#box', 'Enter');
  await desk.until(s => slots(s).some(m => m.rungAt));
  await desk.page.waitForTimeout(600);               // past the 400 ms save debounce
  const before = await desk.store();
  const id = slots(before)[0].answers;
  const from = (await desk.log()).length;

  for (let i = 1; i < 20; i++) await desk.reply(id, 'Running step ' + i, 'working');
  await desk.reply(id, 'All **26** pass.');
  await desk.page.waitForSelector('.said.rich strong');
  await desk.page.waitForTimeout(700);

  const log = await desk.log();
  assert.equal(log.slice(from).filter(e => e.op === 'set' && e.path === REPLIES + '/' + id).length, 20);
  assert.deepEqual(prSets(log, from), []);
  assert.deepEqual((await desk.store())[PR], before[PR]);
  assert.equal(await desk.page.textContent('.said.rich'), 'All 26 pass.');
  assert.deepEqual(desk.errors, []);
});

test('a stored doc holding only slot metadata renders the full answers from replies after reload', async () => {
  desk = await open(browser, {seed: leanDesk()});
  await desk.page.waitForTimeout(700);
  assert.equal(await desk.page.locator('#dot.show').count(), 0, 'answers already there at load are not unread');
  await desk.page.click('#fab');
  await desk.page.waitForSelector('.said.rich strong >> text=two views');
  await desk.page.click('.tab[data-go="1"]');
  await desk.page.waitForSelector('.said.rich >> text=A document per turn.');
  assert.doesNotMatch(await desk.page.textContent('#stream'), /Loading/);

  assert.deepEqual(prSets(await desk.log()), [], 'loading writes nothing');
  assert.deepEqual(await desk.rings(), []);
  assert.deepEqual(desk.errors, []);
});

test('a legacy doc with mirrored answers renders from replies, and the next save drops the copies', async () => {
  const seed = leanDesk();
  const [first, second] = seed[PR].threads;
  // Saved by 0.7.x: the answer copied into the slot, stale here.
  first.turns[1] = {...first.turns[1], status: 'done', content: 'An **old mirrored copy** of the answer.'};
  // And one no reply document backs, which any viewer could have written.
  second.turns[1] = {...second.turns[1], status: 'done', content: 'Forged: safe to merge.'};
  delete seed[REPLIES + '/u2'];
  desk = await open(browser, {seed});
  await desk.page.click('#fab');
  await desk.page.waitForSelector('.said.rich >> text=two views');
  assert.doesNotMatch(await desk.page.textContent('#stream'), /old mirrored copy/);
  await desk.page.click('.tab[data-go="1"]');
  await desk.page.waitForSelector('text=has no reply for it on this desk');
  assert.doesNotMatch(await desk.page.textContent('#stream'), /safe to merge/);
  await desk.page.waitForTimeout(600);
  assert.deepEqual(prSets(await desk.log()), [], 'loading a legacy doc writes nothing either');

  await desk.page.fill('#box', 'Asked after the upgrade');
  await desk.page.press('#box', 'Enter');
  const store = await desk.until(s => asked(s).includes('Asked after the upgrade'));
  for (const slot of slots(store)) assert.ok(!('content' in slot), 'stored slot still has content: ' + JSON.stringify(slot));
  assert.deepEqual(slots(store).find(m => m.answers === 'u1'),
    {role: 'assistant', via: 'session', answers: 'u1', status: 'done', sentAt: 1000, rungAt: 1400});
  assert.deepEqual(asked(store), ['Why a lease?', 'What did you reject?', 'Asked after the upgrade']);
  assert.deepEqual(desk.errors, []);
});

test('two open views: A sends Q2, B receives reply updates, and the store still holds Q2', async () => {
  const seed = leanDesk();
  seed[PR].threads.pop();
  delete seed[REPLIES + '/u2'];
  seed[REPLIES + '/u1'] = {turn: 'u1', status: 'working', text: 'Reading the lease code', at: AT};
  pair = await openPair(browser, {seed});
  const [a, b] = pair;
  for (const v of pair){
    await v.page.click('#fab');
    await v.page.waitForSelector('text=Reading the lease code');
  }

  await a.page.fill('#box', 'Q2 from view A');
  await a.page.press('#box', 'Enter');
  await a.until(s => asked(s).includes('Q2 from view A') && slots(s).some(m => m.answers !== 'u1' && m.rungAt));
  await a.page.waitForTimeout(600);
  const from = (await a.log()).length;

  // The session reports progress on the older message, then answers it. B,
  // loaded before Q2, sees both; before, each one made B save its own threads.
  await a.reply('u1', 'Running the review-desk tests', 'working');
  await b.page.waitForSelector('text=Running the review-desk tests');
  await a.reply('u1', 'Done: **all pass**.');
  await b.page.waitForSelector('.said.rich strong >> text=all pass');
  await b.page.waitForTimeout(700);

  const store = await b.store();
  assert.deepEqual(asked(store), ['Why a lease?', 'Q2 from view A']);
  assert.deepEqual(prSets(await b.log(), from), []);
  assert.deepEqual(b.errors, []);
});

test('a save refused as invalid_argument says the conversation is too large, and closing a thread recovers', async () => {
  desk = await open(browser);
  await desk.page.click('#fab');
  // Over the store's 256 KiB body cap, which the stub enforces as db.d.ts states.
  await desk.page.fill('#box', 'x'.repeat(270 * 1024));
  await desk.page.press('#box', 'Enter');
  await desk.page.waitForSelector('#lostSlot .lost');
  const banner = await desk.page.textContent('#lostSlot');
  assert.match(banner, /too large to save/);
  assert.doesNotMatch(banner, /Not saved/);
  assert.equal((await desk.store())[PR], undefined);
  assert.deepEqual(await desk.rings(), []);

  // The banner's advice works: open another thread, close the oversized one.
  await desk.page.click('#more');
  await desk.page.click('[data-shut="0"]');
  await desk.page.click('#closeYes');
  await desk.until(s => !!s[PR]);
  await desk.page.waitForFunction(() => !document.querySelector('#lostSlot .lost'));
  assert.deepEqual(desk.errors, []);
});

test('a replies listener that dies before its first delivery says so, then resubscribes once and renders', async () => {
  desk = await open(browser, {seed: leanDesk(), subscribeFailures: {[REPLIES]: ['unavailable']}});
  await desk.page.click('#fab');
  await desk.page.waitForSelector('text=replies could not be loaded');
  assert.doesNotMatch(await desk.page.textContent('#stream'), /Loading the working session/);
  assert.match(await desk.page.textContent('#feedSlot'),
    /could not load the working session’s replies \(unavailable\)/);

  await desk.page.waitForSelector('.said.rich strong >> text=two views', {timeout: 8000});
  assert.equal(await desk.page.textContent('#feedSlot'), '');
  assert.equal(await desk.subscribes(REPLIES), 2);
  assert.deepEqual(prSets(await desk.log()), []);
  assert.deepEqual(desk.errors, []);
});

test('a replies listener that dies again is not retried on its own; Try again renders the answers', async () => {
  desk = await open(browser, {seed: leanDesk(),
    subscribeFailures: {[REPLIES]: ['unavailable', 'unavailable']}});
  await desk.page.click('#fab');
  await desk.page.waitForSelector('#feedSlot button', {timeout: 8000});
  assert.match(await desk.page.textContent('#stream'), /replies could not be loaded \(unavailable\)/);
  await desk.page.waitForTimeout(3500);             // longer than the longest automatic wait
  assert.equal(await desk.subscribes(REPLIES), 2, 'one automatic resubscribe, no more');

  await desk.page.click('#feedSlot button');
  await desk.page.waitForSelector('.said.rich strong >> text=two views');
  assert.equal(await desk.subscribes(REPLIES), 3);
  assert.equal(await desk.page.textContent('#feedSlot'), '');
  assert.deepEqual(desk.errors, []);
});

test('a revoked replies listener is not resubscribed and offers no retry', async () => {
  desk = await open(browser, {seed: leanDesk(), subscribeFailures: {[REPLIES]: ['revoked']}});
  await desk.page.click('#fab');
  await desk.page.waitForSelector('text=replies could not be loaded');
  await desk.page.waitForTimeout(3500);
  assert.equal(await desk.subscribes(REPLIES), 1);
  assert.equal(await desk.page.locator('#feedSlot button').count(), 0);
  assert.match(await desk.page.textContent('#feedSlot'), /\(revoked\)/);
  assert.deepEqual(desk.errors, []);
});

test('the description, documents, pickup and presence listeners each show a dead feed and come back', async () => {
  const BODY = PR + '/context/body', DOCS = PR + '/documents', PICKUP = PR + '/context/pickup',
    PRESENCE = PR + '/presence';
  desk = await open(browser);
  for (const end = Date.now() + 5000;;){
    const counts = await Promise.all([BODY, DOCS, PICKUP, PRESENCE, REPLIES].map(desk.subscribes));
    if (counts.every(n => n === 1)) break;
    if (Date.now() > end) throw new Error('listeners never subscribed: ' + counts);
    await desk.page.waitForTimeout(50);
  }
  for (const p of [BODY, DOCS, PICKUP, PRESENCE]) await desk.kill(p);
  await desk.page.waitForSelector('#pageFeeds .lost');
  const onPage = await desk.page.textContent('#pageFeeds');
  assert.match(onPage, /stopped receiving changes to the description \(unavailable\)/);
  assert.match(onPage, /stopped receiving changes to the documents \(unavailable\)/);
  assert.match(onPage, /stopped receiving the working session’s pickup of your decision/);
  await desk.page.click('#fab');
  assert.match(await desk.page.textContent('#feedSlot'), /stopped receiving word from the working session/);

  await desk.page.waitForFunction(() => !document.querySelector('#pageFeeds .lost, #feedSlot .lost'),
    null, {timeout: 8000});
  for (const p of [BODY, DOCS, PICKUP, PRESENCE]) assert.equal(await desk.subscribes(p), 2, p);
  await desk.context('body', {text: 'Rewritten after the reconnect.'});
  await desk.document('docs~new.md', 'docs/new.md', 'A new document', {at: AT});
  await desk.page.waitForSelector('.leaf:nth-child(2)');
  assert.match(await desk.page.textContent('#sheet'), /Rewritten after the reconnect/);

  // The feed delivered after coming back, so a second outage is a new one and
  // gets its own automatic resubscribe.
  await desk.kill(BODY);
  await desk.page.waitForSelector('#pageFeeds .lost');
  await desk.page.waitForFunction(() => !document.querySelector('#pageFeeds .lost'), null, {timeout: 8000});
  assert.equal(await desk.subscribes(BODY), 3);
  assert.deepEqual(desk.errors, []);
});

const subscribedTimes = async (p, n) => {
  for (const end = Date.now() + 8000;;){
    if (await desk.subscribes(p) === n) return;
    if (Date.now() > end) throw new Error(p + ' never reached ' + n + ' subscribes: ' + await desk.subscribes(p));
    await desk.page.waitForTimeout(50);
  }
};

test('each outage after a delivery gets one automatic resubscribe; a revoked feed never does', async () => {
  desk = await open(browser, {seed: leanDesk()});
  await desk.page.click('#fab');
  await desk.page.waitForSelector('.said.rich strong >> text=two views');

  for (const n of [2, 3]){
    await desk.kill(REPLIES);
    await desk.page.waitForSelector('#feedSlot .lost');
    assert.match(await desk.page.textContent('#feedSlot'), /Trying again/);
    await subscribedTimes(REPLIES, n);
    await desk.page.waitForFunction(() => !document.querySelector('#feedSlot .lost'), null, {timeout: 8000});
  }
  // Still delivering after the second recovery.
  await desk.reply('u1', 'Rewritten after two outages.');
  await desk.page.waitForSelector('text=Rewritten after two outages.');

  await desk.kill(REPLIES, 'revoked');
  await desk.page.waitForSelector('#feedSlot .lost');
  await desk.page.waitForTimeout(3500);             // longer than a first automatic wait
  assert.equal(await desk.subscribes(REPLIES), 3);
  assert.equal(await desk.page.locator('#feedSlot button').count(), 0);
  assert.match(await desk.page.textContent('#feedSlot'), /stopped receiving the working session’s replies \(revoked\)/);
  assert.deepEqual(desk.errors, []);
});

test('a feed that keeps delivering and dropping waits longer each time, up to a minute', async () => {
  desk = await open(browser, {seed: leanDesk()});
  await desk.page.click('#fab');
  await desk.page.waitForSelector('.said.rich strong >> text=two views');

  const waits = [];
  for (const n of [2, 3, 4]){
    await desk.kill(REPLIES);
    await desk.page.waitForSelector('#feedSlot .lost');
    waits.push(await desk.page.evaluate('FEEDS.replies.wait'));
    if (n < 4){
      await subscribedTimes(REPLIES, n);
      await desk.page.waitForFunction(() => !document.querySelector('#feedSlot .lost'), null, {timeout: 8000});
    }
  }
  assert.ok(waits[0] >= 1500 && waits[0] <= 3000, 'first wait ' + waits[0]);
  assert.ok(waits[1] >= 3000 && waits[1] <= 6000, 'second wait ' + waits[1]);
  assert.ok(waits[2] >= 6000 && waits[2] <= 12000, 'third wait ' + waits[2]);
  assert.equal(await desk.page.evaluate('RESUBSCRIBE_MAX'), 60000);
  assert.deepEqual(desk.errors, []);
});

test('a replies listener killed after it has delivered says the view stopped receiving', async () => {
  const seed = leanDesk();
  delete seed[REPLIES + '/u2'];                     // u2 waits on an answer this view may miss
  desk = await open(browser, {seed});
  await desk.page.click('#fab');
  await desk.page.waitForSelector('.said.rich strong >> text=two views');
  await desk.page.click('.tab[data-go="1"]');
  await desk.page.waitForSelector('text=Saved and rung');

  // not_granted is never retried on its own, so the state holds still to be read.
  await desk.kill(REPLIES, 'not_granted');
  await desk.page.waitForSelector('#feedSlot .lost');
  assert.match(await desk.page.textContent('#feedSlot'),
    /This view stopped receiving the working session’s replies \(not_granted\)\. What shows here may be out of date\./);
  assert.match(await desk.page.textContent('#stream'),
    /This view stopped receiving the working session’s replies \(not_granted\), so an answer may be waiting/);
  assert.doesNotMatch(await desk.page.textContent('#stream'), /Saved and rung|could not be loaded/);
  await desk.page.waitForTimeout(3500);
  assert.equal(await desk.subscribes(REPLIES), 1);

  // Try again brings the feed, and the waiting line, back.
  await desk.page.click('#feedSlot button');
  await desk.page.waitForSelector('#stream >> text=Saved and rung');
  assert.equal(await desk.page.textContent('#feedSlot'), '');
  assert.deepEqual(desk.errors, []);
});

// A message refused as too large is held out of later writes like any other
// refused message, so it no longer makes the decision's write too large. What does
// is a stored discussion near the cap: here 250 KiB, and a reason that crosses it.
test('a decision refused as too large says so on the decision, not only in the panel', async () => {
  const seed = leanDesk();
  seed[PR].threads[0].turns[0] = {...seed[PR].threads[0].turns[0], content: 'x'.repeat(250 * 1024)};
  desk = await open(browser, {seed});
  await ready(desk);
  await desk.page.click('#changes');
  await desk.page.fill('#why', 'y'.repeat(8 * 1024));
  await desk.page.click('#decide #send');
  await desk.page.waitForFunction(() => {
    const p = document.querySelector('#decide .pickup');
    return p && !/Saving/.test(p.textContent);
  });
  const line = await desk.page.textContent('#decide .pickup');
  assert.match(line, /too large/);
  assert.doesNotMatch(line, /^Not saved, so no session will see this/);
  assert.equal((await desk.store())[PR].decision, null);
  assert.deepEqual(await desk.rings(), []);
  assert.deepEqual(desk.errors, []);
});

/* ---- a save the store refuses, once or for a while ---- */
const ready = d => d.page.waitForFunction('restore === "done"', null, {timeout: 5000});
// Records in the page whether an element ever showed `text`, so a line drawn and
// replaced between two polls from here is still caught.
const watchFor = (d, sel, text) => d.page.evaluate(([sel, text]) => {
  const seen = window.__seen = window.__seen || {};
  const el = document.querySelector(sel);
  const check = () => { if (el.textContent.includes(text)) seen[sel] = el.textContent; };
  new MutationObserver(check).observe(el, {childList: true, subtree: true, characterData: true});
  check();
}, [sel, text]);
const seen = d => d.page.evaluate(() => window.__seen || {});
const refusals = log => log.filter(e => e.op === 'refused' && e.path === PR);
const ringsFor = (rings, id) => rings.filter(r => r.doorbell && r.doorbell.kind === 'message'
  && (r.doorbell.turn === id || (r.doorbell.turns || []).includes(id)));
const sendText = async (d, text) => { await d.page.fill('#box', text); await d.page.press('#box', 'Enter'); };
const pollFor = async (what, fn, timeout) => {
  for (const end = Date.now() + timeout;;){
    if (await fn()) return;
    if (Date.now() > end) throw new Error(what);
    await new Promise(r => setTimeout(r, 100));
  }
};

test('a message whose first save is refused as unavailable is stored on the retry, rung once, and never shown as not saved', async () => {
  desk = await open(browser, {setFailures: {[PR]: ['unavailable']}});
  await ready(desk);
  await desk.page.click('#fab');
  for (const sel of ['#stream', '#lostSlot']) await watchFor(desk, sel, 'Not saved');
  const sent = Date.now();
  await sendText(desk, 'Is this safe?');
  await desk.until(s => slots(s).some(m => m.status === 'sent' && m.rungAt), null, 3000);
  assert.ok(Date.now() - sent < 3000);
  await desk.page.waitForTimeout(1200);              // past the debounce and any later write

  const store = await desk.store();
  assert.equal(turnsIn(store).length, 2, 'one message and its slot');
  const [turn, slot] = turnsIn(store);
  assert.equal(turn.content, 'Is this safe?');
  assert.equal(slot.status, 'sent');
  assert.equal(slot.why, undefined);
  const rings = await desk.rings();
  assert.equal(rings.length, 1);
  assert.equal(ringsFor(rings, turn.id).length, 1);
  assert.deepEqual(await seen(desk), {});
  assert.equal(await desk.page.inputValue('#box'), '');

  // One retry, after the short randomized delay db.d.ts asks for.
  const log = await desk.log();
  assert.equal(refusals(log).length, 1);
  const [refused] = refusals(log);
  const retry = log.find(e => e.op === 'set' && e.path === PR && e.at >= refused.at);
  const gap = retry.at - refused.at;
  assert.ok(gap >= 300 && gap <= 1250, 'retried after ' + gap + ' ms');
  assert.deepEqual(desk.errors, []);
});

test('a save refused as invalid_argument, quota_exceeded or resource_exhausted is not retried', async () => {
  const codes = ['invalid_argument', 'quota_exceeded', 'resource_exhausted'];
  for (const code of codes){
    desk = await open(browser, {setFailures: {[PR]: [code]}});
    await ready(desk);
    await desk.page.click('#fab');
    await sendText(desk, 'Refused with ' + code);
    await desk.page.waitForSelector('[data-resend]');
    await desk.page.waitForTimeout(1500);            // past the longest retry delay
    const log = await desk.log();
    assert.equal(refusals(log).length, 1, code);
    assert.deepEqual(prSets(log), [], code + ' was retried');
    assert.deepEqual(await desk.rings(), []);
    assert.match(await desk.page.textContent('#stream .turn.mine'), new RegExp('Refused with ' + code));
    assert.equal(await desk.page.inputValue('#box'), '', 'the message stays in the stream, not the box');
    assert.deepEqual(desk.errors, []);
    if (code !== codes[codes.length - 1]){
      assert.deepEqual(await desk.missing(), []);
      await desk.close();
    }
  }
});

test('a message refused twice stays in its thread marked not saved with Send again and an empty box, and Send again stores and rings it once', async () => {
  desk = await open(browser, {setFailures: {[PR]: ['unavailable', 'unavailable']}});
  await ready(desk);
  await desk.page.click('#fab');
  await sendText(desk, 'Is this safe?');
  await desk.page.waitForSelector('[data-resend]', {timeout: 3000});
  assert.match(await desk.page.textContent('#stream'), /Not saved, so this has not reached the working session/);
  assert.match(await desk.page.textContent('#stream .turn.mine'), /Is this safe\?/);
  assert.equal(await desk.page.inputValue('#box'), '', 'nothing is put back in the shared box');
  await desk.page.waitForTimeout(1000);
  assert.equal(refusals(await desk.log()).length, 2);
  assert.equal((await desk.store())[PR], undefined, 'nothing saved it behind the reviewer');
  assert.deepEqual(await desk.rings(), []);

  await desk.page.click('[data-resend]');
  await desk.until(s => slots(s).some(m => m.status === 'sent' && m.rungAt), null, 3000);
  await desk.page.waitForTimeout(700);
  const store = await desk.store();
  assert.equal(turnsIn(store).length, 2, 'the same turn, not a second copy');
  assert.deepEqual(asked(store), ['Is this safe?']);
  const rings = await desk.rings();
  assert.equal(rings.length, 1);
  assert.equal(ringsFor(rings, turnsIn(store)[0].id).length, 1);
  assert.equal(await desk.page.locator('#stream .turn.mine').count(), 1);
  assert.equal(await desk.page.inputValue('#box'), '');
  assert.equal(await desk.page.locator('[data-resend]').count(), 0);
  assert.doesNotMatch(await desk.page.textContent('#stream'), /Not saved/);
  assert.equal(await desk.page.textContent('#lostSlot'), '');
  assert.deepEqual(desk.errors, []);
});

// Whether any write to review/pr-N stored a message with this text. The thread's
// name is taken from its first question and is not a message, so it is not checked.
const everWritten = (log, text) => log.some(e => e.op === 'set' && e.path === PR
  && (e.data.threads || []).some(t => t.turns.some(m => m.role === 'user' && m.content === text)));

// The round-4 probe. Send again, then Enter on the box and a second Send again,
// both while that save or its retry is still on its way. Before this design the
// box still held the question at that moment, so Enter asked it a second time.
async function sendAgainTwice(options){
  desk = await open(browser, options);
  await ready(desk);
  await desk.page.click('#fab');
  await sendText(desk, 'Is this safe?');
  await desk.page.waitForSelector('[data-resend]:not([disabled])', {timeout: 3000});
  const id = await desk.page.evaluate('threads[0].turns[0].id');

  await desk.page.click('[data-resend]');
  await desk.page.press('#box', 'Enter');
  const again = desk.page.locator('[data-resend]');
  const shown = await again.count();
  const off = shown ? await again.isDisabled() : null;
  if (shown) await again.dispatchEvent('click');
  await desk.page.evaluate(id => resend(id), id);   // a click that got past the disabled button
  const lastPress = await desk.page.evaluate('Date.now()');

  await desk.until(s => slots(s).some(m => m.rungAt), null, 8000);
  await desk.page.waitForTimeout(1200 + (options.setDelay || 0));
  const store = await desk.store();
  assert.deepEqual(asked(store), ['Is this safe?']);
  assert.equal(turnsIn(store).length, 2, 'one stored turn and its slot');
  const rings = await desk.rings();
  assert.equal(rings.length, 1);
  assert.equal(ringsFor(rings, id).length, 1);
  assert.ok(lastPress < prSets(await desk.log())[0].at, 'the presses came before the save landed');
  assert.equal(shown, 1, 'Send again stays on screen while its save is on its way');
  assert.equal(off, true, 'and is disabled');
  assert.equal(await desk.page.locator('#stream .turn.mine').count(), 1);
  assert.equal(await desk.page.inputValue('#box'), '');
  assert.equal(await desk.page.locator('[data-resend], [data-edit]').count(), 0);
  assert.doesNotMatch(await desk.page.textContent('#stream'), /Not saved/);
  assert.deepEqual(desk.errors, []);
}

test('Enter and a second Send again during a Send again that is refused once store and ring the question once', () =>
  sendAgainTwice({setFailures: {[PR]: ['unavailable', 'unavailable', 'unavailable']}}));

test('Enter and a second Send again while a slow Send again save is landing store and ring the question once', () =>
  sendAgainTwice({setDelay: 1500, setFailures: {[PR]: ['unavailable', 'unavailable']}}));

// Round 3: the text put back in the shared box was sent again from another thread,
// and stored and rung twice. Now nothing follows into the other thread, and no
// write made there carries the refused message.
test('a message refused in one thread is left out of a different question sent from another, and is rung only after its Send again', async () => {
  desk = await open(browser, {setFailures: {[PR]: ['unavailable', 'unavailable']}});
  await ready(desk);
  await desk.page.click('#fab');
  await sendText(desk, 'Is this safe?');
  await desk.page.waitForSelector('[data-resend]', {timeout: 3000});
  const first = await desk.page.evaluate('threads[0].turns[0].id');

  await desk.page.click('#more');
  assert.equal(await desk.page.inputValue('#box'), '', 'nothing of the refused message follows into the new thread');
  await desk.page.press('#box', 'Enter');
  await sendText(desk, 'What about the tests?');
  await desk.until(s => slots(s).some(m => m.rungAt), null, 3000);
  await desk.page.waitForTimeout(1500);
  let store = await desk.store();
  assert.deepEqual(asked(store), ['What about the tests?']);
  const second = turnsIn(store).find(m => m.role === 'user').id;
  assert.equal((await desk.rings()).length, 1);
  assert.equal(ringsFor(await desk.rings(), first).length, 0, 'not rung before its Send again');
  assert.ok(!everWritten(await desk.log(), 'Is this safe?'), 'not written before its Send again');
  assert.match(await desk.page.textContent('#lostSlot'), /could not be stored/);

  await desk.page.click('.tab[data-go="0"]');
  assert.match(await desk.page.textContent('#stream'), /Not saved/);
  await desk.page.click('[data-resend]');
  await desk.until(s => slots(s).length === 2 && slots(s).every(m => m.rungAt), null, 3000);
  await desk.page.waitForTimeout(1200);
  store = await desk.store();
  assert.deepEqual(store[PR].threads.map(t => t.turns.filter(m => m.role === 'user').map(m => m.content)),
    [['Is this safe?'], ['What about the tests?']]);
  assert.equal(turnsIn(store).length, 4);
  const rings = await desk.rings();
  assert.equal(rings.length, 2);
  assert.equal(ringsFor(rings, first).length, 1);
  assert.equal(ringsFor(rings, second).length, 1);
  assert.doesNotMatch(await desk.page.textContent('#stream'), /Not saved/);
  assert.equal(await desk.page.textContent('#lostSlot'), '');
  assert.deepEqual(desk.errors, []);
});

test('Edit takes a refused message out and puts its words in the empty box; only the reworded message is ever stored or rung', async () => {
  desk = await open(browser, {setFailures: {[PR]: ['unavailable', 'unavailable']}});
  await ready(desk);
  await desk.page.click('#fab');
  await sendText(desk, 'Is this safe?');
  await desk.page.waitForSelector('[data-edit]', {timeout: 3000});

  await desk.page.fill('#box', 'A draft');
  assert.equal(await desk.page.locator('[data-edit]').isDisabled(), true, 'Edit never overwrites a draft');
  await desk.page.fill('#box', '');
  await desk.page.click('[data-edit]');
  assert.equal(await desk.page.inputValue('#box'), 'Is this safe?');
  assert.equal(await desk.page.locator('#stream .turn.mine').count(), 0);
  assert.equal(await desk.page.locator('[data-resend], [data-edit]').count(), 0);

  await sendText(desk, 'Is this safe to ship?');
  await desk.until(s => slots(s).some(m => m.rungAt), null, 3000);
  await desk.page.waitForTimeout(1200);
  const store = await desk.store();
  assert.deepEqual(asked(store), ['Is this safe to ship?']);
  assert.equal(turnsIn(store).length, 2);
  const rings = await desk.rings();
  assert.equal(rings.length, 1);
  assert.equal(ringsFor(rings, turnsIn(store)[0].id).length, 1);
  assert.ok(!everWritten(await desk.log(), 'Is this safe?'), 'the original was never written');
  assert.equal(await desk.page.locator('#stream .turn.mine').count(), 1);
  assert.doesNotMatch(await desk.page.textContent('#stream'), /Not saved/);
  assert.equal(await desk.page.textContent('#lostSlot'), '');
  assert.deepEqual(desk.errors, []);
});

test('Approve whose first save is refused as unavailable is stored on the retry and rung, never shown as not saved', async () => {
  desk = await open(browser, {setFailures: {[PR]: ['unavailable']}});
  await ready(desk);
  for (const sel of ['#decide', '#lostSlot']) await watchFor(desk, sel, 'Not saved');
  await desk.page.click('#ok');
  await desk.until(s => s[PR] && s[PR].decision === 'approved', null, 3000);
  await desk.page.waitForFunction(() => window.__desk.rings().length === 1, null, {timeout: 3000});
  const [ring] = await desk.rings();
  assert.equal(ring.doorbell.kind, 'decision');
  assert.equal(ring.doorbell.decision, 'approved');
  await desk.page.waitForSelector('#decide .pickup >> text=Waiting for the working session');
  assert.deepEqual(await seen(desk), {});
  assert.equal(refusals(await desk.log()).length, 1);
  assert.deepEqual(desk.errors, []);
});

test('a decision refused twice is rung, and stops saying not saved, once a later save stores it', async () => {
  desk = await open(browser, {setFailures: {[PR]: ['unavailable', 'unavailable']}});
  await ready(desk);
  await desk.page.click('#ok');
  await desk.page.waitForSelector('#decide .pickup >> text=Not saved, so no session will see this', {timeout: 3000});
  assert.deepEqual(await desk.rings(), []);

  await desk.page.click('#fab');
  await sendText(desk, 'One more thing');
  await desk.until(s => s[PR] && s[PR].decision === 'approved' && slots(s).some(m => m.rungAt), null, 3000);
  await desk.page.waitForSelector('#decide .pickup >> text=Waiting for the working session', {timeout: 3000});
  assert.deepEqual((await desk.rings()).map(r => r.doorbell.kind).sort(), ['decision', 'message']);
  assert.deepEqual(desk.errors, []);
});

// Pages up to 0.10.2 let a later save store a message whose own save had failed,
// still marked unsent/unsaved; this page never writes one (see record). Both views
// load such a slot, and every read takes 1.2 s, so the two ask for the ring lease
// together. Only the holder rings. The other waits the lease out, reads the
// holder's rungAt, and does not ring. The test takes about 25 s for that wait.
test('a slot a later save stored as unsaved is rung once across two views, and neither view says it was not saved', async () => {
  const id = 'm-stranded';
  const seed = {[PR]: {pr: 42, title: 'Harness desk', decision: null, reason: null, decidedAt: null,
    threads: [{id: 't1', name: 'Stranded', turns: [
      {id, role: 'user', content: 'Stranded question', to: 'session'},
      {role: 'assistant', via: 'session', answers: id, status: 'unsent', why: 'unsaved', sentAt: Date.now() - 2000}]}]}};
  pair = await openPair(browser, {seed, getDelay: 1200});
  for (const v of pair) for (const sel of ['#stream', '#lostSlot']) await watchFor(v, sel, 'Not saved');
  for (const v of pair){ await ready(v); await v.page.click('#fab'); }
  const [a] = pair;

  const acquires = async () => (await a.log()).filter(e => e.op === 'acquire');
  await pollFor('both views never asked for the lease', async () => (await acquires()).length >= 2, 10000);
  const [one, two] = await acquires();
  assert.notEqual(one.view, two.view);
  assert.deepEqual([one.acquired, two.acquired], [true, false], 'one view holds the lease');
  const holder = pair.find(v => v.page.name() === one.view), waiter = pair.find(v => v !== holder);

  await pollFor('the waiting view never read the slot again under its own lease', async () => {
    const log = await a.log();
    const got = log.findIndex(e => e.op === 'acquire' && e.view === two.view && e.acquired);
    return got >= 0 && log.slice(got).some(e => e.op === 'get' && e.view === two.view && e.path === PR);
  }, 30000);
  await waiter.page.waitForSelector('#stream >> text=Saved and rung', {state: 'attached', timeout: 5000});

  const publishes = (await a.log()).filter(e => e.op === 'publish');
  assert.equal(publishes.length, 1);
  assert.equal(publishes[0].view, one.view);
  assert.deepEqual(publishes[0].ring.doorbell.turns, [id]);
  const [slot] = slots(await a.store());
  assert.equal(slot.status, 'sent');
  assert.equal(slot.why, undefined);
  assert.ok(slot.rungAt);
  for (const v of [holder, waiter]){
    assert.equal(await v.page.evaluate('lateStored.size'), 0, v.page.name() + ' still holds a rung slot as late');
    assert.equal(await v.page.locator('[data-resend], [data-edit]').count(), 0);
    assert.deepEqual(await seen(v), {});
  }
  assert.deepEqual(a.errors, []);
});

/* ---- a refused retry while another write is storing the same thing ---- */
// Every set carries the whole document. A send made during a refused save's retry
// wait stores that save's message or decision too, whatever the retry then does.
const ringsOf = (rings, kind) => rings.filter(r => r.doorbell && r.doorbell.kind === kind);
const sendDuring = (d, text) => d.page.evaluate(text => new Promise(r => setTimeout(() => {
  document.getElementById('box').value = text; send(); r();
}, 20)), text);

test('a message whose retry is refused after a later send stored it is rung once and never shown as not saved', async () => {
  // X refused; Y's save and its rungAt save land; X's retry refused.
  desk = await open(browser, {setFailures: {[PR]: ['unavailable', null, null, 'unavailable']}});
  await ready(desk);
  await desk.page.click('#fab');
  for (const sel of ['#stream', '#lostSlot']) await watchFor(desk, sel, 'Not saved');
  await sendText(desk, 'Question X');
  await sendDuring(desk, 'Question Y');
  await desk.until(s => slots(s).length === 2 && slots(s).every(m => m.status === 'sent' && m.rungAt),
    null, 4000);
  await desk.page.waitForTimeout(1200);

  assert.equal(refusals(await desk.log()).length, 2, 'both of X\'s sets were refused');
  const store = await desk.store();
  assert.deepEqual(asked(store), ['Question X', 'Question Y']);
  assert.equal(turnsIn(store).length, 4);
  const rings = await desk.rings();
  assert.equal(rings.length, 2);
  for (const m of turnsIn(store).filter(m => m.role === 'user'))
    assert.equal(ringsFor(rings, m.id).length, 1, m.content);
  assert.deepEqual(await seen(desk), {});
  assert.equal(await desk.page.locator('[data-resend]').count(), 0);
  assert.equal(await desk.page.inputValue('#box'), '');
  assert.equal(await desk.page.textContent('#lostSlot'), '');
  assert.deepEqual(desk.errors, []);
});

test('a message whose retry is refused while a later send is still storing it waits for that write, and is rung once', async () => {
  // Accepted sets take 1.5 s to land, longer than the longest retry delay, so X's
  // retry is refused while Y's first save, which carries X, is on its way.
  desk = await open(browser, {setDelay: 1500, setFailures: {[PR]: ['unavailable', null, 'unavailable']}});
  await ready(desk);
  await desk.page.click('#fab');
  for (const sel of ['#stream', '#lostSlot']) await watchFor(desk, sel, 'Not saved');
  await sendText(desk, 'Question X');
  await sendDuring(desk, 'Question Y');
  await desk.until(s => slots(s).length === 2 && slots(s).every(m => m.status === 'sent' && m.rungAt),
    null, 8000);
  await desk.page.waitForTimeout(2000);

  const log = await desk.log();
  const refused = refusals(log);
  assert.equal(refused.length, 2);
  assert.ok(refused[1].at < prSets(log)[0].at, 'the retry was refused before the covering write landed');
  const store = await desk.store();
  assert.deepEqual(asked(store), ['Question X', 'Question Y']);
  assert.equal(turnsIn(store).length, 4);
  const rings = await desk.rings();
  assert.equal(rings.length, 2);
  for (const m of turnsIn(store).filter(m => m.role === 'user'))
    assert.equal(ringsFor(rings, m.id).length, 1, m.content);
  assert.deepEqual(await seen(desk), {});
  assert.equal(await desk.page.locator('[data-resend]').count(), 0);
  assert.equal(await desk.page.inputValue('#box'), '');
  assert.equal(await desk.page.textContent('#lostSlot'), '');
  assert.deepEqual(desk.errors, []);
});

test('a decision whose retry is refused after a send stored it is rung once and never shown as not saved', async () => {
  desk = await open(browser, {setFailures: {[PR]: ['unavailable', null, null, 'unavailable']}});
  await ready(desk);
  for (const sel of ['#decide', '#lostSlot']) await watchFor(desk, sel, 'Not saved');
  await desk.page.click('#fab');
  await desk.page.evaluate(() => { decide('approved'); });
  await sendDuring(desk, 'One more thing');
  await desk.page.waitForFunction(() => window.__desk.rings().length === 2, null, {timeout: 4000});
  await desk.page.waitForTimeout(1200);

  assert.equal(refusals(await desk.log()).length, 2, 'both of the decision\'s own sets were refused');
  const store = await desk.store();
  assert.equal(store[PR].decision, 'approved');
  const rings = await desk.rings();
  assert.equal(rings.length, 2);
  assert.equal(ringsOf(rings, 'decision').length, 1);
  assert.equal(ringsOf(rings, 'message').length, 1);
  await desk.page.waitForSelector('#decide .pickup >> text=Waiting for the working session', {state: 'attached'});
  assert.deepEqual(await seen(desk), {});
  assert.equal(await desk.page.textContent('#lostSlot'), '');
  assert.deepEqual(desk.errors, []);
});
