// What changed, drawn in the document rather than beside it: what went struck
// through where it stood, what arrived underlined in its place, the way a
// tracked change reads in a word processor. A patch is a list of fragments, and
// the reviewer is judging a document -- so prose stays prose, and a source file
// keeps every line, changed or not.
//
// Three ways to read a page: the document, what has changed since this tab last
// read it, and what this request changes against the branch it is against. The
// read baseline is per tab in sessionStorage, because a ring reloads the tab;
// the base text is carried onto the desk by the working session.
import {test, before, after, afterEach} from 'node:test';
import assert from 'node:assert/strict';
import {launch, open, payload} from './harness.mjs';

const PR = 'review/pr-42';

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

const NOTES = 'docs/notes.md';
const FIRST = ['# Notes', '', 'One stays as it is.', 'Two stays as it is.',
  'Three is the line that moves.', 'Four stays as it is.', 'Five stays as it is.',
  'Six stays as it is.', 'Seven stays as it is.', 'Eight stays as it is.'].join('\n');
const SECOND = FIRST.replace('Three is the line that moves.',
  'Three has been rewritten by the session.');

// FIRST is what the file says on main here too, so the request changes nothing
// until the session rewrites the document: each test's two baselines stay
// independent of one another.
const data = (extra = {}) => payload({baseRefName: 'main',
  documents: [{name: NOTES, text: FIRST, base: FIRST}], ...extra});

const bar = () => desk.page.locator('#revbar .what');
const barShown = () => desk.page.$eval('#revbar', el => !el.hidden);
const sheet = () => desk.page.textContent('#sheet');
const openNotes = () => desk.page.click('[data-leaf="1"]');
// The marks themselves: what the page says arrived, and what it says went.
const arrived = () => desk.page.$$eval('#sheet ins.rl', els => els.map(e => e.textContent));
const went = () => desk.page.$$eval('#sheet del.rl', els => els.map(e => e.textContent));
const marked = () => desk.page.waitForSelector('#sheet ins.rl, #sheet del.rl', {timeout: 3000});
// A source file's lines, with what the page made of each one.
const codeLines = () => desk.page.$$eval('#sheet pre.redline .row',
  els => els.map(e => [e.className.replace('row ', ''), e.textContent.replace(/\n$/, '')]));

test('a rewritten page says so, and the changes are one press away', async () => {
  desk = await open(browser, {data: data()});
  await desk.page.waitForSelector('#sheet h2, #sheet h1');
  assert.equal(await barShown(), false, 'nothing has changed yet');

  await desk.document('docs~notes.md', NOTES, SECOND);
  await desk.page.waitForFunction(() => document.querySelector('.leaf .fresh.show'));
  // Still on the request: another page's rewrite does not disturb this one.
  assert.equal(await barShown(), false);

  await openNotes();
  await desk.page.waitForFunction(() => !document.querySelector('#revbar').hidden);
  assert.match(await bar().textContent(), /Rewritten since you read this page/);
  // The document is still the document until the reviewer asks.
  assert.equal(await desk.page.locator('#sheet ins.rl').count(), 0);

  await desk.page.click('[data-view="read"]');
  await marked();
  // Still a document: the heading is a heading, and every line that did not
  // change is there, unmarked.
  assert.equal(await desk.page.locator('#sheet h1').count(), 1, 'prose stays prose');
  const text = await sheet();
  for (const kept of ['One stays as it is.', 'Four stays as it is.', 'Eight stays as it is.'])
    assert.ok(text.includes(kept), kept + ' is missing');
  // Grouped, not alternated: the phrase that went, then the phrase that came.
  assert.deepEqual(await went(), ['is the line that moves.']);
  assert.deepEqual(await arrived(), ['has been rewritten by the session.']);
  assert.ok(text.includes('Three'), 'the word both texts share is outside the marks');
});

test('a rewrite of the page on screen leaves the prose alone until the changes are asked for', async () => {
  desk = await open(browser, {data: data({body: '## What it does\n\nThe first account.\n'})});
  await desk.page.waitForSelector('#sheet h2');
  await desk.context('body', {text: '## What it does\n\nThe second account.\n'});
  await desk.page.waitForFunction(() => document.querySelector('#sheet').textContent.includes('second account'));

  // Swapping the page under someone reading takes away the prose, where they
  // are in it, and the passage they were about to quote.
  assert.equal(await barShown(), true);
  assert.equal(await desk.page.locator('#sheet h2').count(), 1);
  assert.equal(await desk.page.locator('#sheet ins.rl').count(), 0);

  await desk.page.click('[data-view="read"]');
  await marked();
  assert.deepEqual(await went(), ['first']);
  assert.deepEqual(await arrived(), ['second']);
  assert.equal(await desk.page.locator('#sheet h2').count(), 1, 'the heading survives the marks');
  assert.equal(await desk.page.$eval('[data-view="read"]', el => el.getAttribute('aria-pressed')), 'true');

  await desk.page.click('[data-view="full"]');
  await desk.page.waitForSelector('#sheet h2');
  assert.equal(await desk.page.locator('#sheet ins.rl').count(), 0);
  // Looking at the document is not saying you have read the change: the bar stays.
  assert.equal(await barShown(), true);
});

test('a source file keeps every line, with the changed one marked in place', async () => {
  // Asked for plainly: an inline diff is fine, but all of the code, not the
  // changed snippets. A file read as a handful of fragments cannot be judged.
  const lines = n => Array.from({length: 40}, (_, i) => 'x_' + i + ' = ' + (i === 20 ? n : i)).join('\n');
  desk = await open(browser, {data: payload({baseRefName: 'main',
    documents: [{name: 'tools/a.py', text: lines(999), base: lines(20)}]})});
  await desk.page.waitForSelector('.leaf[data-leaf="1"]');
  await openNotes();
  await desk.page.click('[data-view="base"]');
  await desk.page.waitForSelector('#sheet pre.redline');

  const drawn = await codeLines();
  assert.equal(drawn.length, 40, 'every line of the file is drawn, not just the change');
  const changed = drawn.filter(([kind]) => kind !== 'ctx');
  assert.deepEqual(changed.map(([kind]) => kind), ['both']);
  assert.deepEqual(await went(), ['20']);
  assert.deepEqual(await arrived(), ['999']);
  assert.equal(drawn[0][1], 'x_0 = 0');
  assert.equal(drawn[39][1], 'x_39 = 39');
});

test('a line that only went, and one that only arrived, are marked whole', async () => {
  const before = ['keep me', 'delete me', 'keep me too'].join('\n');
  const after = ['keep me', 'keep me too', 'added at the end'].join('\n');
  desk = await open(browser, {data: payload({baseRefName: 'main',
    documents: [{name: 'tools/b.sh', text: after, base: before}]})});
  await desk.page.waitForSelector('.leaf[data-leaf="1"]');
  await openNotes();
  await desk.page.click('[data-view="base"]');
  await desk.page.waitForSelector('#sheet pre.redline');
  assert.deepEqual(await codeLines(), [
    ['ctx', 'keep me'],
    ['del', 'delete me'],
    ['ctx', 'keep me too'],
    ['add', 'added at the end'],
  ]);
  assert.deepEqual(await went(), ['delete me']);
  assert.deepEqual(await arrived(), ['added at the end']);
});

test('a heading or a list item that changed is still a heading or a list item', async () => {
  // The marks are carried through the parser as characters, not tags, exactly so
  // this holds: a mark in front of a # or a bullet would leave the line as a
  // paragraph in the middle of a list.
  const before = ['## The old heading', '', '- first item', '- second item'].join('\n');
  const after = ['## The new heading', '', '- first item', '- second item, reworded',
    '- a third item'].join('\n');
  desk = await open(browser, {data: payload({baseRefName: 'main',
    documents: [{name: 'docs/list.md', text: after, base: before}]})});
  await desk.page.waitForSelector('#sheet');
  await openNotes();
  await desk.page.click('[data-view="base"]');
  await marked();
  assert.equal(await desk.page.locator('#sheet h2').count(), 1, 'the heading is still a heading');
  assert.match(await desk.page.textContent('#sheet h2'), /old.*new|new.*old/);
  assert.equal(await desk.page.locator('#sheet li').count(), 4,
    'the list is still a list, with the item that went beside the one that came');
  assert.ok((await went()).includes('old'), JSON.stringify(await went()));
  assert.ok((await arrived()).includes('new'), JSON.stringify(await arrived()));
  // The rewritten item and the added one are separate lines, so each is marked
  // whole -- which is why there are four items here and three in the file.
  assert.ok((await went()).includes('second item'), JSON.stringify(await went()));
});

test('Mark as read moves the read baseline, and the next rewrite is drawn against it', async () => {
  desk = await open(browser, {data: data()});
  await desk.page.waitForSelector('#sheet h2, #sheet h1');
  await desk.document('docs~notes.md', NOTES, SECOND);
  await desk.page.waitForFunction(() => document.querySelector('.leaf .fresh.show'));
  await openNotes();
  await desk.page.click('[data-view="read"]');
  await marked();

  await desk.page.click('[data-view="markRead"]');
  await desk.page.waitForFunction(() => !document.querySelector('#sheet ins.rl'));

  // A second rewrite, of a different line, while this page is on screen.
  const third = SECOND.replace('Eight stays as it is.', 'Eight has moved too.');
  await desk.document('docs~notes.md', NOTES, third);
  // In a redline the new phrase sits beside the old one, so the page reads
  // "Eight stays as it is. has moved too." -- the arrival is what to wait for.
  await desk.page.waitForFunction(() => [...document.querySelectorAll('#sheet ins.rl')]
    .some(e => e.textContent.includes('moved too')));
  await marked();
  assert.deepEqual(await arrived(), ['has moved too.']);
  assert.ok(!(await arrived()).includes('rewritten'),
    'the first rewrite was read, so it is not marked again');
});

test('the baseline a reload comes back to is what this tab had read', async () => {
  const READ_KEY = 'review-desk read LiLo-Labs/claude-code-plugins#42';
  desk = await open(browser, {
    data: data(),
    seed: {[PR + '/documents/docs~notes.md']:
      {name: NOTES, text: SECOND, base: FIRST, at: '2026-09-17T10:00:00.000Z'}},
    init: 'sessionStorage.setItem(' + JSON.stringify(READ_KEY) + ', '
      + JSON.stringify(JSON.stringify([{k: NOTES, t: FIRST}])) + ')',
  });
  await desk.page.waitForFunction(() => document.querySelector('.leaf .fresh.show'));
  await openNotes();
  await desk.page.click('[data-view="read"]');
  await marked();
  assert.deepEqual(await arrived(), ['has been rewritten by the session.']);
});

test('the toggle holds for the whole desk, and comes back after a reload', async () => {
  const DRAFTS = 'review-desk draft LiLo-Labs/claude-code-plugins#42';
  desk = await open(browser, {data: data({body: '## What it does\n\nThe first account.\n'})});
  await desk.page.waitForSelector('#sheet h2');
  await desk.context('body', {text: '## What it does\n\nThe second account.\n'});
  await desk.page.waitForFunction(() => !document.querySelector('#revbar').hidden);
  await desk.page.click('[data-view="read"]');
  await marked();

  // Another page, rewritten after the toggle went on: no second press.
  await desk.document('docs~notes.md', NOTES, SECOND);
  await desk.page.waitForFunction(() => document.querySelector('.leaf:nth-child(2) .fresh.show'));
  await openNotes();
  await marked();
  assert.deepEqual(await arrived(), ['has been rewritten by the session.']);
  assert.equal(await desk.page.evaluate(k => JSON.parse(sessionStorage.getItem(k)).changes, DRAFTS),
    'read');
});

test('the third view is the request’s own diff, against the base branch', async () => {
  // Here main says FIRST, the request's head says SECOND, and the reviewer has
  // read SECOND already: nothing is new to them, and the request still changed
  // the file.
  desk = await open(browser, {
    data: payload({baseRefName: 'main', documents: [{name: NOTES, text: SECOND, base: FIRST}]}),
  });
  await desk.page.waitForSelector('#sheet h2, #sheet h1');
  await openNotes();
  assert.match(await bar().textContent(), /Changed by this request\. You have read what it says now/);
  assert.equal(await desk.page.$eval('[data-view="read"]', el => el.disabled), true,
    'nothing has changed since this tab read it');
  assert.match(await desk.page.textContent('[data-view="base"]'), /^Against main$/);

  await desk.page.click('[data-view="base"]');
  await marked();
  // Grouped, not alternated: the phrase that went, then the phrase that came.
  assert.deepEqual(await went(), ['is the line that moves.']);
  assert.deepEqual(await arrived(), ['has been rewritten by the session.']);

  // A rewrite under the reviewer keeps both views true.
  const third = SECOND.replace('Eight stays as it is.', 'Eight has moved too.');
  await desk.document('docs~notes.md', NOTES, third, {base: FIRST});
  // In a redline the new phrase sits beside the old one, so the page reads
  // "Eight stays as it is. has moved too." -- the arrival is what to wait for.
  await desk.page.waitForFunction(() => [...document.querySelectorAll('#sheet ins.rl')]
    .some(e => e.textContent.includes('moved too')));
  const both = (await arrived()).join(' | ');
  assert.match(both, /rewritten/, 'against main keeps the earlier change');
  assert.match(both, /moved/, 'and has the new one');

  await desk.page.click('[data-view="read"]');
  await marked();
  assert.deepEqual(await arrived(), ['has moved too.'],
    'since you read has only what arrived after they read it');
});

test('a file the request adds says so, and the whole of it is new', async () => {
  desk = await open(browser, {data: data()});
  await desk.page.waitForSelector('#sheet h2, #sheet h1');
  await desk.document('tools~new.py', 'tools/new.py', 'x = 1\ny = 2\n', {base: null});
  await desk.page.waitForFunction(() => document.querySelectorAll('.leaf').length === 3);
  await desk.page.click('[data-leaf="2"]');
  await desk.page.waitForFunction(() => document.querySelector('#sheet').textContent.includes('x = 1'));
  assert.match(await bar().textContent(), /This request adds this file/);

  await desk.page.click('[data-view="base"]');
  await desk.page.waitForSelector('#sheet pre.redline');
  assert.match(await desk.page.textContent('#sheet .rlnote'), /This request adds this file/);
  assert.deepEqual((await codeLines()).map(([kind]) => kind), ['add', 'add', 'ctx']);
  assert.deepEqual(await went(), [], 'nothing was removed');
});

test('a document carried with no base text offers no comparison with the branch', async () => {
  desk = await open(browser, {data: data()});
  await desk.page.waitForSelector('#sheet h2, #sheet h1');
  await desk.document('tools~old.py', 'tools/old.py', 'x = 1\n');
  await desk.page.waitForFunction(() => document.querySelectorAll('.leaf').length === 3);
  await desk.page.click('[data-leaf="2"]');
  await desk.page.waitForFunction(() => document.querySelector('#sheet').textContent.includes('x = 1'));
  assert.equal(await barShown(), false, 'nothing to compare with, so nothing is claimed');
});

test('a desk opened fresh claims nothing you have read, and still has the request’s diff', async () => {
  desk = await open(browser, {data: data(), seed: {[PR + '/documents/docs~notes.md']:
    {name: NOTES, text: SECOND, base: FIRST, at: '2026-09-17T10:00:00.000Z'}}});
  await desk.page.waitForFunction(() => document.querySelector('#sheet') !== null);
  await openNotes();
  await desk.page.waitForFunction(() => document.querySelector('#sheet').textContent.includes('rewritten by the session'));
  assert.equal(await desk.page.locator('#sheet ins.rl').count(), 0);
  assert.equal(await desk.page.$eval('[data-view="read"]', el => el.disabled), true);
  assert.match(await bar().textContent(), /Changed by this request/);

  await desk.page.click('[data-view="base"]');
  await marked();
  assert.deepEqual(await arrived(), ['has been rewritten by the session.']);
});

test('a wholesale rewrite past the diff table’s cap says so', async () => {
  const long = n => Array.from({length: 900}, (_, i) => n + ' line ' + i).join('\n');
  desk = await open(browser, {data: payload({baseRefName: 'main',
    documents: [{name: 'docs/big.md', text: long('new'), base: long('old')}]})});
  await desk.page.waitForSelector('#sheet');
  await openNotes();
  await desk.page.click('[data-view="base"]');
  await marked();
  assert.match(await desk.page.textContent('#sheet .rlnote'), /rewritten wholesale/);
  assert.ok((await went()).some(t => t.includes('old line 0')), 'the old text is struck through');
  assert.ok((await arrived()).some(t => t.includes('new line 0')), 'the new text is underlined');
});
