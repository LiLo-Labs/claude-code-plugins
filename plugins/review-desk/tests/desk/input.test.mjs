// Input on the reviewer's main device, an iPad: keys, opener chips, the
// selection pop and closing a thread. Runs in Chromium with the rest (npm test)
// and in WebKit (npm run test:webkit). The native iOS edit menu and a real
// input method cannot be driven from here; see the PR's "not verified".
import {test, before, after, afterEach} from 'node:test';
import assert from 'node:assert/strict';
import {launch, open, payload} from './harness.mjs';

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
const IPAD = {hasTouch: true, isMobile: true, viewport: {width: 1024, height: 768}};
const PASSAGE = 'The retry loop gives up after three attempts and reports the last error.';
const withPassage = (extra = {}) => payload({body: '## What it does\n\n' + PASSAGE + '\n', ...extra});
const asked = store => ((store[PR] && store[PR].threads) || [])
  .flatMap(t => t.turns).filter(m => m.role === 'user');
const settle = d => d.page.waitForTimeout(600);        // past the 400 ms save debounce

// Dispatched rather than pressed: Playwright's keyboard cannot set isComposing
// or keyCode. Returns whether the page took the key (preventDefault).
const dispatchEnter = (d, init) => d.page.$eval('#box', (el, init) => {
  const e = new KeyboardEvent('keydown', {key: 'Enter', bubbles: true, cancelable: true, ...init});
  el.dispatchEvent(e);
  return e.defaultPrevented;
}, init);

async function selectPassage(d){
  await d.page.evaluate(() => {
    const r = document.createRange();
    r.selectNodeContents(document.querySelector('#sheet p'));
    const s = getSelection(); s.removeAllRanges(); s.addRange(r);
  });
  await d.page.waitForSelector('#pop', {state: 'visible'});
}

/* ---------------- keys ---------------- */

test('desktop: Enter sends once and Shift+Enter makes a newline', async () => {
  desk = await open(browser);
  await desk.page.click('#fab');
  await desk.page.click('#box');
  await desk.page.keyboard.type('line one');
  await desk.page.keyboard.press('Shift+Enter');
  await desk.page.keyboard.type('line two');
  await settle(desk);
  assert.equal(await desk.page.inputValue('#box'), 'line one\nline two');
  assert.deepEqual(await desk.store(), {});

  await desk.page.keyboard.press('Enter');
  await desk.page.waitForFunction(() => window.__desk.rings().length === 1);
  assert.equal(await desk.page.inputValue('#box'), '');
  assert.deepEqual(asked(await desk.store()).map(m => m.content), ['line one\nline two']);
  assert.deepEqual(desk.errors, []);
});

test('desktop: an input method\'s Enter (isComposing, or keyCode 229) sends nothing', async () => {
  desk = await open(browser);
  await desk.page.click('#fab');
  await desk.page.fill('#box', 'かな');
  assert.equal(await dispatchEnter(desk, {isComposing: true}), false);
  // WebKit's commit Enter: after compositionend, isComposing false, keyCode 229.
  assert.equal(await dispatchEnter(desk, {keyCode: 229}), false);
  await settle(desk);
  assert.equal(await desk.page.inputValue('#box'), 'かな');
  assert.deepEqual(await desk.store(), {});
  assert.deepEqual(await desk.rings(), []);
  // The same dispatch without either mark does send, so the two above were
  // refused for the mark and not because a dispatched key is ignored.
  assert.equal(await dispatchEnter(desk, {keyCode: 13}), true);
  await desk.page.waitForFunction(() => window.__desk.rings().length === 1);
});

test('touch (pointer: coarse): Enter still sends exactly once, and the key is labelled Send', async () => {
  desk = await open(browser, {context: IPAD});
  assert.equal(await desk.page.evaluate(() => matchMedia('(pointer: coarse)').matches), true,
    'the context does not emulate a coarse pointer, so this test would prove nothing');
  assert.equal(await desk.page.getAttribute('#box', 'enterkeyhint'), 'send');
  await desk.page.tap('#fab');
  await desk.page.tap('#box');
  await desk.page.fill('#box', 'Sent from the iPad');
  await desk.page.keyboard.press('Enter');
  await desk.page.waitForFunction(() => window.__desk.rings().length === 1);
  await desk.page.waitForTimeout(1000);
  assert.equal((await desk.rings()).length, 1);
  assert.deepEqual(asked(await desk.store()).map(m => m.content), ['Sent from the iPad']);
  assert.equal(await desk.page.inputValue('#box'), '');
  assert.deepEqual(desk.errors, []);
});

/* ---------------- opener chips ---------------- */

test('a chip tapped with a draft in the box joins the draft and sends nothing', async () => {
  desk = await open(browser);
  await desk.page.click('#fab');
  await desk.page.fill('#box', 'My own half-written question ');
  const opener = await desk.page.textContent('#seed button:nth-child(4)');
  await desk.page.click('#seed button:nth-child(4)');
  await settle(desk);
  assert.equal(await desk.page.inputValue('#box'), 'My own half-written question\n' + opener);
  assert.deepEqual(await desk.rings(), []);
  assert.deepEqual(await desk.store(), {});
  // The draft is the reviewer's to send.
  await desk.page.click('#send');
  await desk.page.waitForFunction(() => window.__desk.rings().length === 1);
  assert.deepEqual(asked(await desk.store()).map(m => m.content),
    ['My own half-written question\n' + opener]);
});

test('a chip tapped with an empty box sends the opener, as before', async () => {
  desk = await open(browser);
  await desk.page.click('#fab');
  const opener = await desk.page.textContent('#seed button:nth-child(1)');
  await desk.page.click('#seed button:nth-child(1)');
  await desk.page.waitForFunction(() => window.__desk.rings().length === 1);
  assert.deepEqual(asked(await desk.store()).map(m => m.content), [opener]);
  assert.equal(await desk.page.inputValue('#box'), '');
  assert.deepEqual(desk.errors, []);
});

/* ---------------- the selection ---------------- */

test('a selection that was dismissed is not carried when the panel opens later', async () => {
  desk = await open(browser, {data: withPassage()});
  await selectPassage(desk);
  await desk.page.click('#title');                    // dismisses the selection
  await desk.page.waitForSelector('#pop', {state: 'hidden'});
  await desk.page.waitForTimeout(1200);               // past the press grace, as "later" is
  await desk.page.click('#fab');
  assert.equal(await desk.page.innerHTML('#carrySlot'), '');
  await desk.page.fill('#box', 'A general question');
  await desk.page.press('#box', 'Enter');
  const store = await desk.until(s => asked(s).length === 1);
  assert.equal(asked(store)[0].quote, null);
});

test('a selection is dropped by a leaf switch', async () => {
  desk = await open(browser, {data: withPassage({documents: [{name: 'docs/notes.md', text: '# Notes\n\nOther text.\n'}]})});
  await selectPassage(desk);
  // Clicked from script so no press collapses the selection first: this is the
  // repaint dropping it, not the click.
  await desk.page.$eval('.leaf:nth-child(2)', b => b.click());
  await desk.page.waitForSelector('#pop', {state: 'hidden'});
  await desk.page.$eval('#fab', b => b.click());
  assert.equal(await desk.page.innerHTML('#carrySlot'), '');
});

test('a live selection is still carried by the panel button', async () => {
  desk = await open(browser, {data: withPassage()});
  await selectPassage(desk);
  await desk.page.click('#fab');
  assert.equal(await desk.page.textContent('#carrySlot .carry span'), PASSAGE);
});

// A tap on an iPad dismisses the selection between the press and the click.
// Neither headless engine does that on its own (a press on the button leaves
// the selection alone), so the order is replayed from script. Inferred from how
// iOS is described to behave, not observed on a device.
const press = (d, id) => d.page.$eval('#' + id,
  b => b.dispatchEvent(new PointerEvent('pointerdown', {bubbles: true})));
// Resolves after the page's own selectionchange handler has run.
const collapse = d => d.page.evaluate(() => new Promise(done => {
  document.addEventListener('selectionchange', done, {once: true});
  getSelection().removeAllRanges();
}));

test('a selection collapsed by the press on the panel button itself is still carried', async () => {
  desk = await open(browser, {data: withPassage()});
  await selectPassage(desk);
  await press(desk, 'fab');
  await collapse(desk);
  await desk.page.$eval('#fab', b => b.click());
  assert.equal(await desk.page.textContent('#carrySlot .carry span'), PASSAGE);
});

test('a selection collapsed by the press on the pop keeps the pop up for that press\'s click', async () => {
  desk = await open(browser, {data: withPassage()});
  await selectPassage(desk);
  await press(desk, 'pop');
  await collapse(desk);
  assert.equal(await desk.page.isVisible('#pop'), true, 'hidden, the pop would never receive the click');
  await desk.page.$eval('#pop', b => b.click());
  assert.equal(await desk.page.textContent('#carrySlot .carry span'), PASSAGE);
});

for (const id of ['pop', 'fab']){
  test(`a press on #${id} that never becomes a click drops the passage once the grace runs out`, async () => {
    desk = await open(browser, {data: withPassage()});
    await selectPassage(desk);
    await press(desk, id);
    await collapse(desk);
    await desk.page.waitForSelector('#pop', {state: 'hidden', timeout: 2000});
    await desk.page.$eval('#fab', b => b.click());
    assert.equal(await desk.page.innerHTML('#carrySlot'), '');
    await desk.page.fill('#box', 'A general question');
    await desk.page.press('#box', 'Enter');
    const store = await desk.until(s => asked(s).length === 1);
    assert.equal(asked(store)[0].quote, null);
  });
}

test('touch: the pop sits below the selection, and a tap on it carries the passage', async () => {
  desk = await open(browser, {data: withPassage(), context: IPAD});
  await selectPassage(desk);
  const [pop, sel] = await desk.page.evaluate(() => {
    const p = document.getElementById('pop').getBoundingClientRect();
    const s = getSelection().getRangeAt(0).getBoundingClientRect();
    return [{top: p.top, left: p.left, right: p.right}, {top: s.top, bottom: s.bottom}];
  });
  assert.ok(pop.top >= sel.bottom, `pop top ${pop.top} is above the selection bottom ${sel.bottom}`);
  assert.ok(pop.left >= 0 && pop.right <= 1024, 'the pop is inside the window');
  await desk.page.tap('#pop');
  await desk.page.waitForSelector('#carrySlot .carry');
  assert.equal(await desk.page.textContent('#carrySlot .carry span'), PASSAGE);
  assert.deepEqual(desk.errors, []);
});

test('desktop: the pop sits above the selection', async () => {
  desk = await open(browser, {data: withPassage()});
  await selectPassage(desk);
  const [popBottom, selTop] = await desk.page.evaluate(() => [
    document.getElementById('pop').getBoundingClientRect().bottom,
    getSelection().getRangeAt(0).getBoundingClientRect().top]);
  assert.ok(popBottom <= selTop, `pop bottom ${popBottom} overlaps the selection top ${selTop}`);
});

/* ---------------- closing a thread ---------------- */

const twoThreads = () => ({[PR]: {pr: 42, title: 'Harness desk', decision: null, reason: null,
  decidedAt: null, threads: [
    {id: 't1', name: 'The argument', turns: [
      {id: 'm-old', role: 'user', content: 'The important argument', to: 'session'}]},
    {id: 't2', name: 'Another', turns: []}]}});

test('the close control is its own 44px button, and closing a thread with turns asks first', async () => {
  const seed = twoThreads();
  desk = await open(browser, {seed});
  await desk.page.click('#fab');
  await desk.page.waitForSelector('text=The important argument');

  const shape = await desk.page.$eval('[data-shut="0"]', el => ({tag: el.tagName,
    inTab: !!el.closest('.tab'), label: el.getAttribute('aria-label'),
    besideTab: !!(el.previousElementSibling && el.previousElementSibling.matches('.tab'))}));
  assert.deepEqual(shape, {tag: 'BUTTON', inTab: false, label: 'Close The argument', besideTab: true});
  const box = await desk.page.locator('[data-shut="0"]').boundingBox();
  assert.ok(box.width >= 44 && box.height >= 44, `close button is ${box.width}x${box.height}`);

  const setsBefore = (await desk.log()).filter(e => e.op === 'set').length;
  // Reachable from the keyboard now that it is a button of its own.
  await desk.page.focus('[data-shut="0"]');
  await desk.page.keyboard.press('Enter');
  await desk.page.waitForSelector('#closeYes');
  assert.equal(await desk.page.locator('.tab').count(), 2);
  await desk.page.click('#closeNo');
  await desk.page.waitForSelector('#closeYes', {state: 'detached'});
  await settle(desk);
  assert.equal(await desk.page.locator('.tab').count(), 2);
  assert.equal((await desk.log()).filter(e => e.op === 'set').length, setsBefore);
  assert.deepEqual(await desk.store(), seed);

  await desk.page.click('[data-shut="0"]');
  await desk.page.click('#closeYes');
  const store = await desk.until(s => s[PR].threads.length === 1);
  assert.deepEqual(store[PR].threads.map(t => t.id), ['t2']);
  assert.equal(await desk.page.locator('.tab').count(), 1);
  assert.deepEqual(desk.errors, []);
});

test('closing an empty thread needs no confirmation, and the open thread stays open', async () => {
  const seed = twoThreads();
  desk = await open(browser, {seed});
  await desk.page.click('#fab');
  await desk.page.waitForSelector('text=The important argument');
  await desk.page.click('.tab[data-go="1"]');
  await desk.page.click('#more');                     // a third, empty, now open
  await desk.page.click('.tab[data-go="0"]');         // back to the argument
  await desk.page.click('[data-shut="1"]');           // the empty "Another"
  assert.equal(await desk.page.locator('#closeYes').count(), 0);
  assert.equal(await desk.page.locator('.tab').count(), 2);
  assert.equal(await desk.page.textContent('.tab.on'), 'The argument');
  const store = await desk.until(s => s[PR].threads.length === 2);
  assert.deepEqual(store[PR].threads.map(t => t.id)[0], 't1');
});
