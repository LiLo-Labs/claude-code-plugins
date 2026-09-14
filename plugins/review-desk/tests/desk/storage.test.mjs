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

test('Approve refused as too large says so on the decision, not only in the panel', async () => {
  desk = await open(browser);
  await desk.page.click('#fab');
  // Over the store's 256 KiB body cap, so every whole-document set after it is
  // refused invalid_argument, the decision's included.
  await desk.page.fill('#box', 'x'.repeat(270 * 1024));
  await desk.page.press('#box', 'Enter');
  await desk.page.waitForSelector('#lostSlot .lost');
  await desk.page.click('#shut');
  await desk.page.click('#ok');
  await desk.page.waitForFunction(() => {
    const p = document.querySelector('#decide .pickup');
    return p && !/Saving/.test(p.textContent);
  });
  const line = await desk.page.textContent('#decide .pickup');
  assert.match(line, /too large/);
  assert.doesNotMatch(line, /^Not saved, so no session will see this/);
  assert.equal((await desk.store())[PR], undefined);
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
    assert.equal(await desk.page.inputValue('#box'), 'Refused with ' + code);
    assert.deepEqual(desk.errors, []);
    if (code !== codes[codes.length - 1]){
      assert.deepEqual(await desk.missing(), []);
      await desk.close();
    }
  }
});

test('a message refused twice says not saved, puts its text back, and Send again stores and rings it once', async () => {
  desk = await open(browser, {setFailures: {[PR]: ['unavailable', 'unavailable']}});
  await ready(desk);
  await desk.page.click('#fab');
  await sendText(desk, 'Is this safe?');
  await desk.page.waitForSelector('[data-resend]', {timeout: 3000});
  assert.match(await desk.page.textContent('#stream'), /Not saved, so this has not reached the working session/);
  assert.equal(await desk.page.inputValue('#box'), 'Is this safe?');
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

test('Enter on the text put back after a refused send sends that message again, not a second copy', async () => {
  desk = await open(browser, {setFailures: {[PR]: ['unavailable', 'unavailable']}});
  await ready(desk);
  await desk.page.click('#fab');
  await sendText(desk, 'Is this safe?');
  await desk.page.waitForSelector('[data-resend]', {timeout: 3000});
  await desk.page.press('#box', 'Enter');
  await desk.until(s => slots(s).some(m => m.rungAt), null, 3000);
  await desk.page.waitForTimeout(700);
  const store = await desk.store();
  assert.deepEqual(asked(store), ['Is this safe?']);
  assert.equal(turnsIn(store).length, 2);
  assert.equal((await desk.rings()).length, 1);
  assert.equal(await desk.page.locator('#stream .turn.mine').count(), 1);
  assert.equal(await desk.page.inputValue('#box'), '');
  assert.deepEqual(desk.errors, []);
});

test('Approve whose first save is refused as unavailable is stored on the retry and rung, never shown as not saved', async () => {
  desk = await open(browser, {setFailures: {[PR]: ['unavailable']}});
  await ready(desk);
  await watchFor(desk, '#decide', 'Not saved');
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

// View A's send is refused twice, so its slot is unsaved in A's memory only. A
// later save from A stores it. View B is reloaded right then, as A's ring reloads
// it on the host, and reads the stored slot while A holds the ring lease. Every
// read takes 1.2 s, which keeps B's read inside A's lease.
test('a message left unsaved is rung once when a later save stores it, and a view loaded meanwhile waits on the lease', async () => {
  pair = await openPair(browser, {getDelay: 1200});
  const [a, b] = pair;
  for (const v of pair) await ready(v);
  await a.page.click('#fab');
  await a.failSets(PR, ['unavailable', 'unavailable']);
  await sendText(a, 'Stranded question');
  await a.page.waitForSelector('[data-resend]', {timeout: 3000});
  const id = await a.page.evaluate('threads[0].turns[0].id');
  await a.page.waitForTimeout(800);
  assert.equal((await a.store())[PR], undefined);

  // A later save that rings for nothing of its own: a thread opened and closed.
  await a.page.click('#more');
  await a.page.click('[data-shut="1"]');
  await a.until(s => slots(s).some(m => m.answers === id));
  await b.reload();
  await a.until(s => slots(s).some(m => m.answers === id && m.rungAt), null, 8000);
  assert.equal(await a.page.locator('[data-resend]').count(), 0);
  assert.doesNotMatch(await a.page.textContent('#stream'), /Not saved/);

  const byB = async () => (await a.log()).filter(e => e.op === 'acquire' && e.view === 'view-b');
  await pollFor('view B never asked for the lease', async () => (await byB()).length, 8000);
  assert.equal((await byB())[0].acquired, false, 'view A holds the lease');
  assert.equal(await b.page.locator('[data-resend]').count(), 0);
  assert.doesNotMatch(await b.page.textContent('#stream'), /Not saved/);

  // Once A's lease runs out B asks again, reads A's rungAt, and does not ring.
  await pollFor('view B never read the slot again under its own lease', async () => {
    const log = await a.log();
    const got = log.findIndex(e => e.op === 'acquire' && e.view === 'view-b' && e.acquired);
    return got >= 0 && log.slice(got).some(e => e.op === 'get' && e.view === 'view-b' && e.path === PR);
  }, 30000);
  await b.page.waitForSelector('#stream >> text=Saved and rung', {state: 'attached', timeout: 5000});

  const publishes = (await a.log()).filter(e => e.op === 'publish');
  assert.equal(publishes.length, 1);
  assert.equal(publishes[0].view, 'view-a');
  assert.deepEqual(publishes[0].ring.doorbell.turns, [id]);
  const store = await a.store();
  assert.deepEqual(asked(store), ['Stranded question']);
  assert.equal(turnsIn(store).length, 2);
  assert.deepEqual(a.errors, []);
});
