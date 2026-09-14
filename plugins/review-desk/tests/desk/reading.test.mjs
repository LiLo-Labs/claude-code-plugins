// Reading the panel and the page while answers arrive: the badge says an answer
// came, the stream keeps the reviewer's place, and the page keeps track of which
// section they are reading.
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
const REPLIES = PR + '/replies';
const AT = '2026-09-13T10:00:00.000Z';

/* ---------------- the badge ---------------- */

// One thread, one message the session has not answered yet. rungAt is set so
// nothing rings for it on load.
const oneWaiting = () => ({[PR]: {pr: 42, title: 'Harness desk', decision: null, reason: null,
  decidedAt: null, threads: [{id: 't1', name: 'Only', turns: [
    {id: 'u1', role: 'user', content: 'Is the lease needed?', to: 'session'},
    {role: 'assistant', via: 'session', answers: 'u1', status: 'sent', sentAt: 1000, rungAt: 1400}]}]}});

test('with one thread and the panel closed, a reply lights the badge', async () => {
  desk = await open(browser, {seed: oneWaiting()});
  await desk.page.waitForFunction(p => window.__desk.log().some(e => e.op === 'subscribe' && e.path === p),
    REPLIES);
  await desk.page.waitForTimeout(300);                // the first, historical, delivery
  assert.equal(await desk.page.locator('#dot.show').count(), 0);

  await desk.reply('u1', 'Yes: two views ring otherwise.');
  await desk.page.waitForSelector('#dot.show', {timeout: 3000});
  assert.equal(await desk.page.textContent('#dot'), '1');

  // Opening the panel reads it.
  await desk.page.click('#fab');
  await desk.page.waitForSelector('.said.rich >> text=two views ring');
  await desk.page.click('#shut');
  assert.equal(await desk.page.locator('#dot.show').count(), 0);
  assert.deepEqual(desk.errors, []);
});

test('a reply with the panel open on that thread lights nothing', async () => {
  desk = await open(browser, {seed: oneWaiting()});
  await desk.page.click('#fab');
  await desk.page.waitForSelector('text=Is the lease needed?');
  await desk.reply('u1', 'Answered while you watched.');
  await desk.page.waitForSelector('text=Answered while you watched.');
  await desk.page.click('#shut');
  assert.equal(await desk.page.locator('#dot.show').count(), 0);
  assert.deepEqual(desk.errors, []);
});

/* ---------------- the stream keeps its place ---------------- */

const LONG = Array.from({length: 60}, (_, i) => 'Paragraph ' + (i + 1) + ' of the long answer.').join('\n\n');
const twoInOne = () => ({[PR]: {pr: 42, title: 'Harness desk', decision: null, reason: null,
  decidedAt: null, threads: [{id: 't1', name: 'Long', turns: [
    {id: 'u1', role: 'user', content: 'Explain the lease.', to: 'session'},
    {role: 'assistant', via: 'session', answers: 'u1', status: 'done', sentAt: 1000, rungAt: 1400},
    {id: 'u2', role: 'user', content: 'And the retry?', to: 'session'},
    {role: 'assistant', via: 'session', answers: 'u2', status: 'working', sentAt: 2000, rungAt: 2400}]}]},
  [REPLIES + '/u1']: {turn: 'u1', status: 'done', text: LONG, at: AT},
  [REPLIES + '/u2']: {turn: 'u2', status: 'working', text: 'Step 1', at: AT}});

const scroll = to => desk.page.$eval('#stream', (el, to) => {
  el.scrollTop = to === 'end' ? el.scrollHeight : to;
  return el.scrollTop;
}, to);
const scrollTop = () => desk.page.$eval('#stream', el => el.scrollTop);
const gap = () => desk.page.$eval('#stream', el => el.scrollHeight - el.scrollTop - el.clientHeight);

test('a reply rewrite leaves a reader scrolled up where they were, and keeps one at the end there', async () => {
  desk = await open(browser, {seed: twoInOne()});
  await desk.page.click('#fab');
  await desk.page.waitForSelector('text=Step 1');
  assert.ok(await gap() < 2, 'opening the panel starts at the end');

  assert.equal(await scroll(0), 0);
  await desk.reply('u2', 'Step 2', 'working');
  await desk.page.waitForSelector('text=Step 2');
  assert.equal(await scrollTop(), 0);

  // Part way up, too: not only the top, which a clamp would also leave alone.
  const mid = await scroll(300);
  assert.ok(mid > 0, 'the stream is long enough to scroll');
  await desk.reply('u2', 'Step 3', 'working');
  await desk.page.waitForSelector('text=Step 3');
  assert.equal(await scrollTop(), mid);

  await scroll('end');
  await desk.reply('u2', 'Done.\n\n' + LONG.replace(/long answer/g, 'retry answer'));
  await desk.page.waitForSelector('text=Paragraph 60 of the retry answer.');
  assert.ok(await gap() < 2, 'a reader at the end follows the new text');
  assert.deepEqual(desk.errors, []);
});

test('a reply for another thread leaves the open thread\'s stream nodes in place', async () => {
  const seed = twoInOne();
  const turns = seed[PR].threads[0].turns;
  seed[PR].threads = [{id: 't1', name: 'First', turns: turns.slice(0, 2)},
                      {id: 't2', name: 'Second', turns: turns.slice(2)}];
  desk = await open(browser, {seed});
  await desk.page.click('#fab');
  await desk.page.waitForSelector('text=Paragraph 60 of the long answer.');
  await desk.page.waitForTimeout(300);
  await desk.page.evaluate(() => {
    window.__held = document.querySelector('#stream .turn.theirs');
    window.__tabsRedrawn = new Promise(done => new MutationObserver((_, o) => { o.disconnect(); done(); })
      .observe(document.getElementById('tabs'), {childList: true}));
  });

  await desk.reply('u2', 'The retry is bounded.');
  await desk.page.evaluate(() => window.__tabsRedrawn);
  await desk.page.waitForTimeout(100);
  assert.equal(await desk.page.evaluate(() =>
    window.__held.isConnected && document.querySelector('#stream .turn.theirs') === window.__held), true,
    'the open thread\'s stream was rebuilt for a reply to another thread');

  // Nothing is stale: the other thread shows the new answer when opened.
  await desk.page.click('.tab[data-go="1"]');
  await desk.page.waitForSelector('.said.rich >> text=The retry is bounded.');
  // And a later one, while the panel is shut on the first thread, lights the badge.
  await desk.page.click('.tab[data-go="0"]');
  await desk.page.click('#shut');
  await desk.reply('u2', 'The retry is bounded, twice.');
  await desk.page.waitForSelector('#dot.show', {timeout: 3000});
  assert.deepEqual(desk.errors, []);
});

/* ---------------- where the reviewer is reading ---------------- */

// Counts, from inside the page, the IntersectionObservers made and not yet
// disconnected, and the scroll handlers on window not yet removed.
function countWatchers(){
  const IO = window.IntersectionObserver;
  window.__watch = {made: 0, live: 0, scroll: new Set()};
  window.IntersectionObserver = class extends IO {
    constructor(...a){ super(...a); window.__watch.made++; window.__watch.live++; this.__on = true; }
    disconnect(){ if (this.__on){ this.__on = false; window.__watch.live--; } return super.disconnect(); }
  };
  const add = window.addEventListener, remove = window.removeEventListener;
  window.addEventListener = function(type, fn, o){
    // A {once: true} handler removes itself; those are the test's own.
    if (type === 'scroll' && !(o && o.once)) window.__watch.scroll.add(fn);
    return add.call(this, type, fn, o);
  };
  window.removeEventListener = function(type, fn, o){
    if (type === 'scroll') window.__watch.scroll.delete(fn);
    return remove.call(this, type, fn, o);
  };
}

const sections = (label, n) => Array.from({length: n}, (_, i) => '## ' + label + ' ' + (i + 1) + '\n\n'
  + Array.from({length: 6}, () => 'A sentence long enough to take up a line of the sheet. ').join('')
  + '\n').join('\n');

test('after many repaints the message says the section of the page on screen, and one observer is live', async () => {
  const data = payload({body: sections('Section', 10),
    documents: [{name: 'docs/notes.md', text: '# Notes\n\n' + sections('Part', 8)},
                {name: 'tools/a.py', text: Array.from({length: 150}, (_, i) => 'x_' + i + ' = ' + i).join('\n')}]});
  desk = await open(browser, {data, init: countWatchers});
  await desk.page.waitForSelector('#sheet h2');
  const PAGE = '#sheet';

  // Ten rewrites of the description, each a repaint, and each followed 5 s later
  // by another one that clears the fresh mark.
  for (let i = 1; i <= 10; i++){
    await desk.context('body', {text: sections('Section', 10) + '\nRevision ' + i + '\n'});
    await desk.page.waitForFunction(([sel, i]) =>
      document.querySelector(sel).textContent.includes('Revision ' + i), [PAGE, i]);
  }
  await desk.page.waitForTimeout(5400);
  const made = await desk.page.evaluate(() => window.__watch.made);
  assert.ok(made >= 20, 'the wrapped constructor saw the page\'s repaints (' + made + ')');

  const scrollTo = y => desk.page.evaluate(y => new Promise(done => {
    addEventListener('scroll', () => requestAnimationFrame(() => done()), {once: true});
    window.scrollTo({top: y, behavior: 'instant'});
  }), y);
  const headingY = text => desk.page.evaluate(text => {
    const h = [...document.querySelectorAll('#sheet h1, #sheet h2')].find(x => x.textContent.trim() === text);
    return h.getBoundingClientRect().top + scrollY;
  }, text);
  const sendAndRead = async question => {
    await desk.page.fill('#box', question);
    await desk.page.press('#box', 'Enter');
    const store = await desk.until(s => ((s[PR] && s[PR].threads) || [])
      .some(t => t.turns.some(m => m.content === question)));
    return store[PR].threads.flatMap(t => t.turns).find(m => m.content === question).reading;
  };

  await scrollTo(await headingY('Section 6') - 60);
  assert.equal(await desk.page.textContent('#where'), '¶ Section 6');

  // A source file has no headings; scrolling it must not bring back the description's.
  await desk.page.click('.leaf:nth-child(3)');
  await desk.page.waitForTimeout(800);                  // the switch's smooth scroll to the top
  await scrollTo(400);
  await desk.page.click('#fab');
  assert.equal(await sendAndRead('Asked from the source file'), 'tools/a.py');

  await desk.page.click('#shut');
  await desk.page.click('.leaf:nth-child(2)');
  await desk.page.waitForTimeout(800);
  await scrollTo(await headingY('Part 3') - 60);
  await desk.page.click('#fab');
  assert.equal(await sendAndRead('Asked from the notes'), 'docs/notes.md — Part 3');

  const watch = await desk.page.evaluate(() => ({live: window.__watch.live, scroll: window.__watch.scroll.size}));
  assert.ok(watch.live <= 1, 'live IntersectionObservers: ' + watch.live);
  assert.ok(watch.scroll <= 1, 'window scroll handlers: ' + watch.scroll);
  assert.deepEqual(desk.errors, []);
});

/* ---------------- how markdown renders ---------------- */

// The description and the session's replies go through the one renderer, so
// these read the rendered DOM rather than the markup string: what the reviewer
// sees is the shape the browser built.
const describe = async (body, options = {}) => {
  desk = await open(browser, {data: payload({body}), ...options});
  await desk.page.waitForSelector('#sheet > *');
};
// A compact outline of an element's children: tag, attributes that matter here,
// and text for leaves, so a test states the whole shape it expects.
const shape = sel => desk.page.$eval(sel, root => {
  const walk = el => [...el.childNodes].map(n => {
    if (n.nodeType === 3) return n.textContent;
    const tag = n.tagName.toLowerCase() + (n.getAttribute('start') ? '[start=' + n.getAttribute('start') + ']' : '')
      + (n.className ? '.' + n.className : '');
    return n.children.length || n.tagName === 'CODE' ? {[tag]: walk(n)} : {[tag]: n.textContent};
  });
  return walk(root);
});

test('a loose numbered list, blank lines between its steps, is one list counting 1, 2, 3', async () => {
  await describe('1. Run the tests\n\n2. Open the desk\n\n3. Approve');
  assert.deepEqual(await shape('#sheet'),
    [{ol: [{li: 'Run the tests'}, {li: 'Open the desk'}, {li: 'Approve'}]}]);

  // Steps that carry on past a blank line stay in their item, and a list that
  // does not start at 1 keeps its number.
  await desk.context('body', {text: '3. Build it\n\n   The build takes a minute.\n\n4. Ship it'});
  await desk.page.waitForSelector('#sheet ol[start="3"]');
  assert.deepEqual(await shape('#sheet'), [{'ol[start=3]': [
    {li: [{p: 'Build it'}, {p: 'The build takes a minute.'}]}, {li: 'Ship it'}]}]);
  assert.deepEqual(desk.errors, []);
});

test('a fenced block inside a list item is a code block in that item, newlines and all', async () => {
  await describe('Test plan:\n\n'
    + '1. Install\n   ```bash\n   npm ci\n     npm test -- --watch\n   ```\n'
    + '2. Open the desk\n\n'
    + '   ```\n   untagged\n\n   second line\n   ```\n'
    + '3. Approve\n');
  const items = desk.page.locator('#sheet ol > li');
  assert.equal(await desk.page.locator('#sheet ol').count(), 1);
  assert.equal(await items.count(), 3);

  const code = items.nth(0).locator(':scope > pre > code');
  assert.equal(await code.textContent(), 'npm ci\n  npm test -- --watch');
  assert.equal(await code.getAttribute('class'), 'language-bash');
  // Only a tagged block is marked for the highlighter.
  const plain = items.nth(1).locator(':scope > pre > code');
  assert.equal(await plain.textContent(), 'untagged\n\nsecond line');
  assert.equal(await plain.getAttribute('class'), null);
  assert.equal(await items.nth(2).textContent(), 'Approve');
  assert.ok(!(await desk.page.textContent('#sheet')).includes('```'), 'a fence mark shows as text');

  // A bulleted item takes the same, indented by the bullet's two columns.
  await desk.context('body', {text: '- Install\n  ```bash\n  npm ci\n  npm test\n  ```\n- Run'});
  await desk.page.waitForFunction(() => document.querySelector('#sheet ul'));
  assert.deepEqual(await shape('#sheet'), [{ul: [
    {li: ['Install', {pre: [{'code.language-bash': ['npm ci\nnpm test']}]}]}, {li: 'Run'}]}]);
  assert.deepEqual(desk.errors, []);
});

test('tight lists, nested bullets, wrapped items and a list followed by a paragraph keep their shape', async () => {
  await describe([
    '- one', '- two', '- three', '',
    'Between.', '',
    '- parent', '  - child a', '  - child b', '- sibling', '',
    '1. wrapped item that', '   carries on', '2. next', '',
    'After the list, with a blank line.', '',
    '- tight', 'Straight after, no blank line.', '',
    '    indented code after a paragraph',
  ].join('\n'));
  assert.deepEqual(await shape('#sheet'), [
    {ul: [{li: 'one'}, {li: 'two'}, {li: 'three'}]},
    {p: 'Between.'},
    {ul: [{li: ['parent', {ul: [{li: 'child a'}, {li: 'child b'}]}]}, {li: 'sibling'}]},
    {ol: [{li: 'wrapped item that carries on'}, {li: 'next'}]},
    {p: 'After the list, with a blank line.'},
    {ul: [{li: 'tight'}]},
    {p: 'Straight after, no blank line.'},
    {pre: [{code: ['indented code after a paragraph']}]},
  ]);
  assert.deepEqual(desk.errors, []);
});

test('inside list items, markup is escaped, links open away, and a mermaid fence stays a diagram source', async () => {
  await describe('- <img src=x onerror="window.__ran=1"> and **bold**\n'
    + '- see [the docs](https://example.com/docs)\n'
    + '- a diagram\n  ```mermaid\n  graph TD\n    A["<b>x</b>"] --> B\n  ```\n'
    + '- code\n  ```\n  <script>window.__ran=1</script>\n  ```');
  assert.equal(await desk.page.locator('#sheet img, #sheet script, #sheet b').count(), 0);
  assert.equal(await desk.page.evaluate(() => window.__ran), undefined);
  assert.ok((await desk.page.textContent('#sheet li:nth-child(1)')).startsWith('<img src=x'));
  assert.equal(await desk.page.textContent('#sheet li:nth-child(1) strong'), 'bold');
  const link = desk.page.locator('#sheet li:nth-child(2) a');
  assert.equal(await link.getAttribute('href'), 'https://example.com/docs');
  assert.equal(await link.getAttribute('target'), '_blank');
  assert.equal(await link.getAttribute('rel'), 'noopener');
  // The harness refuses the mermaid script, so the source block stays, marked for it.
  assert.equal(await desk.page.textContent('#sheet li:nth-child(3) pre > code.language-mermaid'),
    'graph TD\n  A["<b>x</b>"] --> B');
  assert.equal(await desk.page.textContent('#sheet li:nth-child(4) pre > code'),
    '<script>window.__ran=1</script>');
  assert.deepEqual(desk.errors, []);
});

/* ---------------- contrast ---------------- */

// WCAG 2 contrast of each element's computed text colour on its computed
// background, both opaque in these rules.
const contrasts = selectors => desk.page.evaluate(selectors => {
  const lum = css => {
    const [r, g, b] = css.match(/[\d.]+/g).slice(0, 3).map(v => {
      const c = +v / 255;
      return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
    });
    return 0.2126 * r + 0.7152 * g + 0.0722 * b;
  };
  return Object.fromEntries(selectors.map(sel => {
    const st = getComputedStyle(document.querySelector(sel));
    const [hi, lo] = [lum(st.color), lum(st.backgroundColor)].sort((a, b) => b - a);
    return [sel, Math.round((hi + 0.05) / (lo + 0.05) * 100) / 100];
  }));
}, selectors);

for (const scheme of ['dark', 'light']){
  test(`${scheme} mode: Approve, Send, the active tab and the reviewer's own message clear 4.5:1`, async () => {
    desk = await open(browser, {context: {colorScheme: scheme}});
    assert.equal(await desk.page.evaluate(() => matchMedia('(prefers-color-scheme: dark)').matches),
      scheme === 'dark', 'the context does not emulate the colour scheme, so this test would prove nothing');
    await desk.page.click('#fab');
    await desk.page.fill('#box', 'Mine, in my own bubble');
    await desk.page.press('#box', 'Enter');
    await desk.page.waitForSelector('.turn.mine .said');
    const got = await contrasts(['#ok', '#send', '.tab.on', '.turn.mine .said']);
    for (const [sel, ratio] of Object.entries(got)) assert.ok(ratio >= 4.5, `${sel} is ${ratio}:1`);
    assert.deepEqual(desk.errors, []);
  });
}
