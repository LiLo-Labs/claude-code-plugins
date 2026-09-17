// What changed since you read it. The working session rewrites a document while
// the desk is open -- because the reviewer asked, or because someone pushed --
// and the page used to say only that something had: a mark on the tab, and a new
// text where the old one was. It now keeps the text each page had when this tab
// last read it and draws the difference against it, as a patch, behind a toggle.
//
// The toggle is one setting for the desk and it sticks, so asking what changed is
// a single press and then it is simply how the desk reads. The baseline is per
// tab, in sessionStorage, because a ring reloads the tab.
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

const data = (extra = {}) => payload({documents: [{name: NOTES, text: FIRST}], ...extra});
const bar = () => desk.page.locator('#revbar');
const barShown = () => desk.page.$eval('#revbar', el => !el.hidden);
const diffText = () => desk.page.textContent('#sheet .diff');
const openNotes = () => desk.page.click('[data-leaf="1"]');
// The rows of the patch, each with the sign the page drew.
const rows = () => desk.page.$$eval('#sheet .diff .row',
  els => els.map(e => e.textContent.replace(/ /g, ' ')));

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
  assert.equal(await desk.page.locator('#sheet .diff').count(), 0);
  await desk.page.click('[data-view="changes"]');
  await desk.page.waitForSelector('#sheet .diff');
  const drawn = await rows();
  assert.ok(drawn.some(r => r.startsWith('−') && r.includes('Three is the line that moves')), drawn);
  assert.ok(drawn.some(r => r.startsWith('+') && r.includes('Three has been rewritten')), drawn);
  // Context either side, and the rest of the file collapsed rather than redrawn.
  assert.ok(drawn.some(r => r.startsWith(' ') && r.includes('Two stays as it is')), drawn);
  assert.match(await diffText(), /unchanged lines?/);
  assert.equal(await desk.page.locator('#sheet h1').count(), 0, 'the patch is source, not prose');
});

test('the words that changed inside a rewritten line are marked', async () => {
  desk = await open(browser, {data: data()});
  await desk.page.waitForSelector('#sheet h2, #sheet h1');
  await desk.document('docs~notes.md', NOTES, SECOND);
  await desk.page.waitForFunction(() => document.querySelector('.leaf .fresh.show'));
  await openNotes();
  await desk.page.click('[data-view="changes"]');
  await desk.page.waitForSelector('#sheet .diff');
  // Each changed word is its own mark, so the line reads with the shared words
  // unmarked between them.
  // Each changed word is its own mark, and the spaces between them are not
  // marked, so the line still reads as a line.
  const marks = sel => desk.page.$$eval(sel, els => els.map(e => e.textContent));
  assert.deepEqual(await marks('#sheet .diff del'), ['is', 'the', 'line', 'that', 'moves.']);
  assert.deepEqual(await marks('#sheet .diff ins'),
    ['has', 'been', 'rewritten', 'by', 'the', 'session.']);
  // "Three" is shared, so it is marked on neither side, and both rows still
  // carry the whole line.
  const drawn = await rows();
  assert.ok(drawn.includes('\u2212Three is the line that moves.'), drawn);
  assert.ok(drawn.includes('+Three has been rewritten by the session.'), drawn);
});

test('a rewrite of the page on screen leaves the prose alone until the changes are asked for', async () => {
  desk = await open(browser, {data: data({body: '## What it does\n\nThe first account.\n'})});
  await desk.page.waitForSelector('#sheet h2');
  await desk.context('body', {text: '## What it does\n\nThe second account.\n'});
  await desk.page.waitForFunction(() => document.querySelector('#sheet').textContent.includes('second account'));

  // The bar is there; the document is still a document. Swapping it for a patch
  // under someone reading takes away the prose and the passage they were about
  // to quote.
  assert.equal(await barShown(), true);
  assert.equal(await desk.page.locator('#sheet h2').count(), 1);
  assert.equal(await desk.page.locator('#sheet .diff').count(), 0);

  await desk.page.click('[data-view="changes"]');
  await desk.page.waitForSelector('#sheet .diff');
  const drawn = await rows();
  assert.ok(drawn.some(r => r.startsWith('−') && r.includes('The first account.')), drawn);
  assert.ok(drawn.some(r => r.startsWith('+') && r.includes('The second account.')), drawn);
  assert.equal(await desk.page.$eval('[data-view="changes"]', el => el.getAttribute('aria-pressed')), 'true');

  await desk.page.click('[data-view="full"]');
  await desk.page.waitForSelector('#sheet h2');
  assert.equal(await desk.page.locator('#sheet .diff').count(), 0);
  // Looking at the document is not saying you have read the change: the bar stays.
  assert.equal(await barShown(), true);
});

test('Mark as read takes the bar away, and the next rewrite is drawn against what was read', async () => {
  desk = await open(browser, {data: data()});
  await desk.page.waitForSelector('#sheet h2, #sheet h1');
  await desk.document('docs~notes.md', NOTES, SECOND);
  await desk.page.waitForFunction(() => document.querySelector('.leaf .fresh.show'));
  await openNotes();
  await desk.page.click('[data-view="changes"]');
  await desk.page.waitForSelector('#sheet .diff');

  await desk.page.click('[data-view="read"]');
  await desk.page.waitForSelector('#sheet h1');
  assert.equal(await barShown(), false);
  assert.equal(await desk.page.locator('#sheet .diff').count(), 0);

  // A second rewrite, of a different line, while this page is on screen. The
  // toggle was left on, so the changes are drawn as soon as they are asked for.
  const third = SECOND.replace('Eight stays as it is.', 'Eight has moved too.');
  await desk.document('docs~notes.md', NOTES, third);
  await desk.page.waitForFunction(() => !document.querySelector('#revbar').hidden);
  await desk.page.waitForSelector('#sheet .diff');
  const drawn = await rows();
  assert.ok(drawn.some(r => r.startsWith('+') && r.includes('Eight has moved too')), drawn);
  assert.ok(!drawn.some(r => r.startsWith('+') && r.includes('Three has been rewritten')),
    'the first rewrite was read, so it is not drawn again: ' + JSON.stringify(drawn));
});

test('the baseline a reload comes back to is what this tab had read', async () => {
  // The case the whole view exists for: a ring reloads the tab, so the page it
  // comes back to is built from the payload again and the store hands it a text
  // a revision ahead. The baseline in sessionStorage is the only record of what
  // the reviewer had actually read, and this is the reload seen from the other
  // side -- a tab that had read the payload's copy before the ring arrived.
  const READ_KEY = 'review-desk read LiLo-Labs/claude-code-plugins#42';
  desk = await open(browser, {
    data: data(),
    seed: {[PR + '/documents/docs~notes.md']:
      {name: NOTES, text: SECOND, at: '2026-09-17T10:00:00.000Z'}},
    init: 'sessionStorage.setItem(' + JSON.stringify(READ_KEY) + ', '
      + JSON.stringify(JSON.stringify([{k: NOTES, t: FIRST}])) + ')',
  });
  await desk.page.waitForFunction(() => document.querySelector('.leaf .fresh.show'));
  await openNotes();
  await desk.page.click('[data-view="changes"]');
  await desk.page.waitForSelector('#sheet .diff');
  const drawn = await rows();
  assert.ok(drawn.some(r => r.startsWith('+') && r.includes('Three has been rewritten')), drawn);
  assert.ok(drawn.some(r => r.startsWith('\u2212') && r.includes('Three is the line that moves')), drawn);
});

test('the toggle holds for the whole desk, and comes back after a reload', async () => {
  desk = await open(browser, {data: data({body: '## What it does\n\nThe first account.\n'})});
  await desk.page.waitForSelector('#sheet h2');
  await desk.context('body', {text: '## What it does\n\nThe second account.\n'});
  await desk.page.waitForFunction(() => !document.querySelector('#revbar').hidden);
  await desk.page.click('[data-view="changes"]');
  await desk.page.waitForSelector('#sheet .diff');

  // Another page, rewritten after the toggle went on: no second press.
  await desk.document('docs~notes.md', NOTES, SECOND);
  await desk.page.waitForFunction(() => document.querySelector('.leaf:nth-child(2) .fresh.show'));
  await openNotes();
  await desk.page.waitForSelector('#sheet .diff');
  assert.ok((await rows()).some(r => r.startsWith('+') && r.includes('Three has been rewritten')));

  // And the setting itself is a draft, so the reload a ring causes keeps it.
  assert.equal(await desk.page.evaluate(() => JSON.parse(
    sessionStorage.getItem('review-desk draft LiLo-Labs/claude-code-plugins#42')).changes), true);
});

test('a desk opened fresh on a store already ahead of its payload claims no changes', async () => {
  // The session rewrote a document while no tab was open. The reviewer has read
  // neither text, so there is nothing to show them as a change.
  desk = await open(browser, {data: data(), seed: {[PR + '/documents/docs~notes.md']:
    {name: NOTES, text: SECOND, at: '2026-09-17T10:00:00.000Z'}}});
  await desk.page.waitForFunction(() => document.querySelector('#sheet') !== null);
  await openNotes();
  await desk.page.waitForFunction(() => document.querySelector('#sheet').textContent.includes('rewritten by the session'));
  assert.equal(await barShown(), false);
  assert.equal(await desk.page.locator('#sheet .diff').count(), 0);
});

test('a file the desk never carried arrives as a document, not as a change', async () => {
  desk = await open(browser, {data: data()});
  await desk.page.waitForSelector('#sheet h2, #sheet h1');
  await desk.document('tools~new.py', 'tools/new.py', 'x = 1\ny = 2\n');
  await desk.page.waitForFunction(() => document.querySelectorAll('.leaf').length === 3);
  await desk.page.click('[data-leaf="2"]');
  await desk.page.waitForFunction(() => document.querySelector('#sheet').textContent.includes('x = 1'));
  assert.equal(await barShown(), false);
});

test('a wholesale rewrite past the diff table\u2019s cap says so', async () => {
  // Past the table's cap the page stops trying to pair lines up: a quadratic
  // walk of a thousand-line rewrite would hang the tab.
  const long = n => Array.from({length: 900}, (_, i) => n + ' line ' + i).join('\n');
  desk = await open(browser, {data: payload({documents: [{name: NOTES, text: long('old')}]})});
  await desk.page.waitForSelector('#sheet');
  await desk.document('docs~notes.md', NOTES, long('new'));
  await desk.page.waitForFunction(() => document.querySelector('.leaf .fresh.show'));
  await openNotes();
  await desk.page.click('[data-view="changes"]');
  await desk.page.waitForSelector('#sheet .diff');
  assert.match(await diffText(), /rewritten wholesale/);
  const drawn = await rows();
  assert.ok(drawn.some(r => r.startsWith('−') && r.includes('old line 0')), 'the old text is removed');
  assert.ok(drawn.some(r => r.startsWith('+') && r.includes('new line 0')), 'the new text is added');
});
