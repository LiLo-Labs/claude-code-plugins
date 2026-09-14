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

// The passage between two long runs of filler, so the page can scroll it to
// either edge of the window before it is selected.
const filler = n => Array.from({length: n}, (_, i) => 'Filler paragraph ' + (i + 1)
  + ' takes up a line of the sheet so that the page has room to scroll.').join('\n\n');
const scrollingPassage = () => payload({body: '## What it does\n\n' + filler(30) + '\n\n'
  + PASSAGE + '\n\n' + filler(30) + '\n'});

// Scrolls the passage to the top or bottom edge of the window, selects it, and
// returns the pop's and the selection's rectangles and the window height.
async function selectAtEdge(d, edge){
  await d.page.evaluate(edge => {
    const p = [...document.querySelectorAll('#sheet p')].find(x => x.textContent.startsWith('The retry loop'));
    const r = p.getBoundingClientRect();
    const want = edge === 'bottom' ? innerHeight - 8 - r.height : 4;
    window.scrollTo(0, scrollY + r.top - want);
    const range = document.createRange();
    range.selectNodeContents(p);
    const s = getSelection(); s.removeAllRanges(); s.addRange(range);
  }, edge);
  await d.page.waitForSelector('#pop', {state: 'visible'});
  await d.page.waitForTimeout(100);
  return d.page.evaluate(() => {
    const box = r => ({top: r.top, bottom: r.bottom, left: r.left, right: r.right});
    return {pop: box(document.getElementById('pop').getBoundingClientRect()),
      sel: box(getSelection().getRangeAt(0).getBoundingClientRect()), height: innerHeight, width: innerWidth};
  });
}
const apart = (a, b) => a.bottom <= b.top || a.top >= b.bottom;

test('touch: with no room below the selection, the pop goes above it rather than over it', async () => {
  desk = await open(browser, {data: scrollingPassage(), context: IPAD});
  const {pop, sel, height} = await selectAtEdge(desk, 'bottom');
  assert.ok(height - sel.bottom < 40, `the selection is not near the bottom (${sel.bottom} of ${height})`);
  assert.ok(apart(pop, sel), `pop ${JSON.stringify(pop)} overlaps selection ${JSON.stringify(sel)}`);
  assert.ok(pop.bottom <= sel.top, 'the pop is above the selection');
  assert.ok(pop.top >= 0 && pop.bottom <= height, `pop ${JSON.stringify(pop)} leaves the window`);
  await desk.page.tap('#pop');
  await desk.page.waitForSelector('#carrySlot .carry');
  assert.equal(await desk.page.textContent('#carrySlot .carry span'), PASSAGE);
  assert.deepEqual(desk.errors, []);
});

test('desktop: a selection at the top of the window keeps the pop inside it, clear of the selection', async () => {
  desk = await open(browser, {data: scrollingPassage()});
  const {pop, sel, height, width} = await selectAtEdge(desk, 'top');
  assert.ok(sel.top < 40, `the selection is not near the top (${sel.top})`);
  assert.ok(pop.top >= 0 && pop.bottom <= height, `pop ${JSON.stringify(pop)} leaves the window`);
  assert.ok(pop.left >= 0 && pop.right <= width, `pop ${JSON.stringify(pop)} leaves the window sideways`);
  assert.ok(apart(pop, sel), `pop ${JSON.stringify(pop)} overlaps selection ${JSON.stringify(sel)}`);
  assert.deepEqual(desk.errors, []);
});

/* ---------------- keyboard focus across repaints ---------------- */

// What holds focus, as a selector-like name: an id, or the data-* key that names a
// control. BODY is what a rebuild that drops focus leaves.
const focused = d => d.page.evaluate(() => {
  const a = document.activeElement;
  if (!a || a === document.body) return 'BODY';
  if (a.id) return '#' + a.id;
  const k = Object.keys(a.dataset)[0];
  return k ? '[data-' + k + '="' + a.dataset[k] + '"]' : a.tagName;
});
const ready = d => d.page.waitForFunction('restore === "done"', null, {timeout: 5000});
const withDoc = () => payload({documents: [{name: 'docs/a.md', text: '# A\n\nAlpha'}]});
const waitingSeed = () => ({[PR]: {pr: 42, title: 'Harness desk', decision: null, reason: null, decidedAt: null,
  threads: [{id: 't1', name: 'Only', turns: [
    {id: 'u1', role: 'user', content: 'Is the lease needed?', to: 'session'},
    {role: 'assistant', via: 'session', answers: 'u1', status: 'sent', sentAt: 1000, rungAt: 1400}]}]}});

test('Enter on a document tab keeps focus on the new tab, and a documents row arriving keeps it there', async () => {
  desk = await open(browser, {data: withDoc()});
  await ready(desk);
  await desk.page.focus('[data-leaf="1"]');
  await desk.page.keyboard.press('Enter');
  await desk.page.waitForSelector('.leaf.on[data-leaf="1"]');
  assert.equal(await focused(desk), '[data-leaf="1"]');

  // A new document, which redraws the strip only, and a rewrite of the one on screen,
  // which repaints the sheet and the strip.
  await desk.document('docs~b.md', 'docs/b.md', '# B\n\nBeta', {at: new Date().toISOString()});
  await desk.page.waitForSelector('[data-leaf="2"]');
  assert.equal(await focused(desk), '[data-leaf="1"]');
  await desk.document('docs~a.md', 'docs/a.md', '# A\n\nAlpha revised', {at: new Date().toISOString()});
  await desk.page.waitForSelector('#sheet >> text=Alpha revised');
  assert.equal(await focused(desk), '[data-leaf="1"]');
  assert.deepEqual(desk.errors, []);
});

test('Enter on Approve focuses Confirm, and Enter on Confirm leaves focus on the recorded line through the ring', async () => {
  desk = await open(browser);
  await ready(desk);
  await desk.page.focus('#ok');
  await desk.page.keyboard.press('Enter');
  await desk.page.waitForSelector('#approveConfirm');
  assert.equal(await focused(desk), '#approveConfirm');
  await desk.page.keyboard.press('Enter');
  await desk.page.waitForFunction(() => window.__desk.rings().length === 1);
  await desk.page.waitForSelector('#decide .pickup >> text=Waiting for the working session');
  assert.ok(['#decisionLine', '#redo'].includes(await focused(desk)), 'focus is ' + await focused(desk));

  // Change this goes back to the choice with focus on Approve, and Back from the
  // reason form does the same.
  await desk.page.focus('#redo');
  await desk.page.keyboard.press('Enter');
  await desk.page.waitForSelector('#ok');
  assert.equal(await focused(desk), '#ok');
  await desk.page.click('#changes');
  await desk.page.focus('#back');
  await desk.page.keyboard.press('Enter');
  await desk.page.waitForSelector('#ok');
  assert.equal(await focused(desk), '#ok');
  assert.deepEqual(desk.errors, []);
});

test('Enter on Check keeps focus on Check', async () => {
  desk = await open(browser);
  await ready(desk);
  await desk.page.click('#fab');
  await desk.page.focus('#check');
  await desk.page.keyboard.press('Enter');
  await desk.page.waitForSelector('#presence >> text=Checking the working session');
  await desk.page.waitForFunction(() => window.__desk.rings().length === 1);
  assert.equal(await focused(desk), '#check');
  assert.deepEqual(desk.errors, []);
});

test('a reply landing while a thread tab has focus keeps it, and Keep it returns focus to that thread\'s close button', async () => {
  const seed = waitingSeed();
  seed[PR].threads.push({id: 't2', name: 'Second', turns: [{id: 'u2', role: 'user', content: 'Two', to: 'session'}]});
  desk = await open(browser, {seed});
  await desk.page.click('#fab');
  await desk.page.waitForSelector('text=Is the lease needed?');
  await desk.page.focus('.tab[data-go="0"]');
  await desk.reply('u1', 'Yes: two views ring otherwise.');
  await desk.page.waitForSelector('.said.rich >> text=two views ring');
  assert.equal(await focused(desk), '[data-go="0"]');

  await desk.page.focus('.tab[data-go="1"]');
  await desk.page.keyboard.press('Enter');
  await desk.page.waitForSelector('.tab.on[data-go="1"]');
  assert.equal(await focused(desk), '[data-go="1"]');

  await desk.page.focus('[data-shut="1"]');
  await desk.page.keyboard.press('Enter');
  await desk.page.waitForSelector('#closeNo');
  await desk.page.keyboard.press('Enter');
  await desk.page.waitForSelector('#closeNo', {state: 'detached'});
  assert.equal(await focused(desk), '[data-shut="1"]');
  assert.deepEqual(desk.errors, []);
});

test('typing in the box is never interrupted by a reply, a document row, a presence stamp or a redrawn decision', async () => {
  desk = await open(browser, {seed: waitingSeed(), data: withDoc()});
  await desk.page.click('#fab');
  await desk.page.waitForSelector('text=Is the lease needed?');
  await desk.page.click('#box');
  await desk.page.keyboard.type('first half ');
  await desk.reply('u1', 'An answer while you type.');
  await desk.document('docs~a.md', 'docs/a.md', '# A\n\nAlpha revised', {at: new Date().toISOString()});
  await desk.presence(String(Math.floor(Date.now() / 1000)));
  await desk.context('body', {text: '## Revised\n\nNew words.'});
  await desk.page.waitForSelector('.said.rich >> text=An answer while you type.');
  await desk.page.waitForSelector('.leaf[data-leaf="1"] .fresh.show');
  await desk.page.waitForSelector('#presence >> text=Working session last answered');
  await desk.page.keyboard.type('second half');
  assert.equal(await focused(desk), '#box');
  assert.equal(await desk.page.inputValue('#box'), 'first half second half');
  assert.deepEqual(desk.errors, []);
});

/* ---------------- what a reload gives back ---------------- */

const DRAFT = 'review-desk draft LiLo-Labs/claude-code-plugins#42';
const draftEntry = d => d.page.evaluate(k => JSON.parse(sessionStorage.getItem(k) || '{}'), DRAFT);
const twoThreadSeed = () => ({[PR]: {pr: 42, title: 'Harness desk', decision: null, reason: null, decidedAt: null,
  threads: [{id: 't1', name: 'The argument', turns: [{id: 'm-old', role: 'user', content: 'The important argument', to: 'session'},
    {role: 'assistant', via: 'session', answers: 'm-old', status: 'sent', sentAt: 1000, rungAt: 1400}]},
    {id: 't2', name: 'Another', turns: []}]}});
const readyAgain = d => d.page.waitForFunction('typeof restore !== "undefined" && restore === "done"', null, {timeout: 5000});

test('a draft, a reason being written, a carried quote, the open thread and the open page survive a reload, and each clears once sent', async () => {
  const data = withPassage({documents: [{name: 'docs/notes.md', text: '# Notes\n\nOther text.\n'}]});
  desk = await open(browser, {seed: twoThreadSeed(), data});
  await ready(desk);
  await selectPassage(desk);
  await desk.page.click('#pop');                                  // carries it, and opens the panel
  await desk.page.waitForSelector('#carrySlot .carry');
  await desk.page.click('.tab[data-go="1"]');
  await desk.page.fill('#box', 'Half a question');
  await desk.page.click('.leaf[data-leaf="1"]');
  await desk.page.waitForSelector('#sheet >> text=Other text.');
  await desk.page.click('#changes');
  await desk.page.fill('#why', 'Rename the flag');

  await desk.reload();
  await readyAgain(desk);
  await desk.page.waitForSelector('#why');
  assert.equal(await desk.page.inputValue('#why'), 'Rename the flag');
  assert.equal(await desk.page.inputValue('#box'), 'Half a question');
  assert.equal(await desk.page.getAttribute('.leaf.on', 'data-leaf'), '1');
  assert.match(await desk.page.textContent('#sheet'), /Other text\./);
  await desk.page.click('#fab');
  assert.equal(await desk.page.textContent('.tab.on'), 'Another');
  assert.equal(await desk.page.textContent('#carrySlot .carry span'), PASSAGE);

  // Sent: the message carries the restored quote, and the box and quote entries go.
  await desk.page.press('#box', 'Enter');
  const store = await desk.until(s => asked(s).some(m => m.content === 'Half a question'));
  assert.equal(asked(store).find(m => m.content === 'Half a question').quote, PASSAGE);
  assert.equal(store[PR].threads.find(t => t.id === 't2').turns[0].content, 'Half a question');
  await desk.page.waitForFunction(k => { const d = JSON.parse(sessionStorage.getItem(k) || '{}'); return !('box' in d) && !('quote' in d); },
    DRAFT, {timeout: 3000});
  const afterSend = await draftEntry(desk);
  assert.equal(afterSend.why, 'Rename the flag');
  assert.equal(afterSend.thread, 't2');

  // Decided: the reason entry goes.
  await desk.page.click('#shut');
  await desk.page.click('#recordReason');
  await desk.until(s => s[PR].decision === 'needs changes');
  await desk.page.waitForFunction(k => !('why' in JSON.parse(sessionStorage.getItem(k) || '{}')), DRAFT, {timeout: 3000});

  // A reload now brings back neither the message nor the reason. The stub's store
  // starts from the seed again, so the decision is not there either: the slab offers
  // the choice, with no reason form.
  await desk.reload();
  await readyAgain(desk);
  assert.equal(await desk.page.inputValue('#box'), '');
  assert.equal(await desk.page.locator('#why').count(), 0);
  assert.equal(await desk.page.innerHTML('#carrySlot'), '');
  assert.deepEqual(desk.errors, []);
});

test('Back from the reason form forgets the reason, and a message that could not be saved keeps its words for a reload', async () => {
  desk = await open(browser, {setFailures: {[PR]: ['unavailable', 'unavailable']}});
  await ready(desk);
  await desk.page.click('#changes');
  await desk.page.fill('#why', 'Not this after all');
  await desk.page.click('#back');
  assert.equal('why' in await draftEntry(desk), false);

  await desk.page.click('#fab');
  await desk.page.fill('#box', 'Refused twice');
  await desk.page.press('#box', 'Enter');
  await desk.page.waitForSelector('#stream >> text=Not saved');
  assert.equal((await draftEntry(desk)).box, 'Refused twice');
  assert.deepEqual(desk.errors, []);
});

function refuseSessionStorage(){
  const refuse = () => { throw new DOMException('The operation is insecure.', 'SecurityError'); };
  try { Object.defineProperty(window, 'sessionStorage', {get: refuse, configurable: true}); } catch (e) {}
  for (const k of ['getItem', 'setItem', 'removeItem', 'key', 'clear']) Storage.prototype[k] = refuse;
}

test('with sessionStorage refused the page loads, sends, records a reason and reloads without errors', async () => {
  desk = await open(browser, {init: refuseSessionStorage});
  assert.equal(await desk.page.evaluate(() => { try { sessionStorage.getItem('x'); return 'read'; } catch (e) { return 'refused'; } }),
    'refused', 'the init script did not take storage away');
  await ready(desk);
  await desk.page.click('#fab');
  await desk.page.fill('#box', 'Does it still work?');
  await desk.page.press('#box', 'Enter');
  await desk.page.waitForFunction(() => window.__desk.rings().length === 1);
  await desk.page.click('#shut');
  await desk.page.click('#changes');
  await desk.page.fill('#why', 'A reason');
  await desk.page.click('#recordReason');
  await desk.until(s => s[PR] && s[PR].decision === 'needs changes');
  await desk.reload();
  await readyAgain(desk);
  assert.equal(await desk.page.inputValue('#box'), '');
  assert.deepEqual(desk.errors, []);
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

test('closing a thread before the open one keeps the same thread open', async () => {
  // Three threads, so an index left undecremented lands on a different thread
  // rather than being clamped back onto the right one.
  const seed = {[PR]: {pr: 42, title: 'Harness desk', decision: null, reason: null, decidedAt: null,
    threads: [{id: 't0', name: 'Empty before', turns: []},
      {id: 't1', name: 'The argument', turns: [
        {id: 'm-old', role: 'user', content: 'The important argument', to: 'session'}]},
      {id: 't2', name: 'Empty after', turns: []}]}};
  desk = await open(browser, {seed});
  await desk.page.click('#fab');
  await desk.page.click('.tab[data-go="1"]');
  await desk.page.waitForSelector('text=The important argument');
  await desk.page.click('[data-shut="0"]');            // empty, so no confirmation
  const store = await desk.until(s => s[PR].threads.length === 2);
  assert.deepEqual(store[PR].threads.map(t => t.id), ['t1', 't2']);
  assert.equal(await desk.page.textContent('.tab.on'), 'The argument');
  assert.match(await desk.page.textContent('#stream'), /The important argument/);
  assert.deepEqual(desk.errors, []);
});
