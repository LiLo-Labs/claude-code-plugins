// Behaviour the desk has today, locked in before later changes touch it.
import {test, before, after, afterEach} from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import {launch, open, payload, approve} from './harness.mjs';

let browser, desk;
before(async () => { browser = await launch(); });
after(async () => { await browser.close(); });
afterEach(async () => {
  if (!desk) return;
  assert.deepEqual(await desk.missing(), [], 'the page called something the stub does not implement');
  await desk.close();
  desk = null;
});

const turnsIn = (store, pr) => ((store[pr] && store[pr].threads) || []).flatMap(t => t.turns);

async function typeAndSend(d, text){
  await d.page.click('#fab');
  await d.page.fill('#box', text);
  await d.page.press('#box', 'Enter');
}

test('a page write to a session path is refused under the desk rules, and the page save is not', async () => {
  const tryWrites = d => d.page.evaluate(async paths => {
    const db = await claude.use('db');
    const out = {};
    for (const p of paths){
      try { await db.doc(p).set({decision: 'approved', text: 'written by the page'}); out[p] = 'stored'; }
      catch (e){ out[p] = e.code; }
    }
    return out;
  }, ['review/pr-42/context/pickup', 'review/pr-42/replies/m1', 'review/pr-42/presence/1700000000',
    'review/pr-42/documents/d1']);

  desk = await open(browser);
  await desk.page.waitForFunction('restore === "done"');
  assert.deepEqual(Object.values(await tryWrites(desk)), Array(4).fill('invalid_argument'));
  await approve(desk);
  const store = await desk.until((s, pr) => s[pr] && s[pr].decision === 'approved', desk.pr);
  assert.deepEqual(Object.keys(store), [desk.pr]);
  await desk.close();

  // The rules never limit the owner, so the same writes land from an owner's view.
  desk = await open(browser, {level: 'owner'});
  await desk.page.waitForFunction('restore === "done"');
  assert.deepEqual(Object.values(await tryWrites(desk)), Array(4).fill('stored'));
});

test('the stub update merges nested objects and replaces arrays, as db.d.ts says', async () => {
  desk = await open(browser);
  const doc = await desk.page.evaluate(async () => {
    const ref = (await claude.use('db')).doc('review/pr-42');
    await ref.set({a: {x: 1, y: {z: 2}}, list: [1, 2], keep: true});
    await ref.update({a: {y: {w: 3}}, list: [3]});
    return (await ref.get()).data();
  });
  assert.deepEqual(doc, {a: {x: 1, y: {z: 2, w: 3}}, list: [3], keep: true});
});

test('carried text containing </script> loads the desk', async () => {
  const data = payload({
    title: 'Quotes a </script> tag',
    body: 'Mentions `</script>` and the `/*PAYLOAD*/` marker.',
    documents: [
      {name: 'templates/page.html', text: '<script>x()</script>\n'},
      {name: 'docs/old.md', text: '<!--<script>\nnot closed\n'},
      {name: 'docs/marker.md', text: 'const DATA = /*PAYLOAD*/;\nline sep\n'},
    ],
  });
  desk = await open(browser, {data, title: 'Script Tag Review'});
  // A cut-short script never draws the tabs; let the page errors say why.
  await desk.page.waitForSelector('.leaf:nth-child(4)', {timeout: 3000}).catch(() => {});
  assert.deepEqual(desk.errors, []);
  assert.equal(await desk.page.textContent('#title'), data.title);
  assert.equal(await desk.page.title(), 'Script Tag Review');
  assert.equal(await desk.page.locator('.leaf').count(), 4);
  await desk.page.click('.leaf:nth-child(2)');
  assert.equal(await desk.page.textContent('#sheet pre code'), '<script>x()</script>\n');
});

