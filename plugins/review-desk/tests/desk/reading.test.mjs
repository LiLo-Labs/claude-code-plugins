// What the reviewer reads: the tabs, the marks on them, and the one renderer
// every document goes through. The chat these once shared a page with is gone;
// what is left is the reading surface, which is the half of the desk that was
// never in question.
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

test('a change to a page the reviewer is not reading leaves the sheet alone, and its mark stays until that page is opened', async () => {
  desk = await open(browser, {data: payload({documents: [{name: 'docs/a.md', text: '# A\n\nAlpha'}]})});
  await desk.page.waitForSelector('#sheet h2');
  const hold = sel => desk.page.evaluate(sel => { window.__held = document.querySelector(sel); }, sel);
  const held = sel => desk.page.evaluate(sel =>
    window.__held.isConnected && document.querySelector(sel) === window.__held, sel);

  await hold('#sheet h2');
  await desk.document('docs~a.md', 'docs/a.md', '# A\n\nAlpha revised', {at: new Date().toISOString()});
  await desk.page.waitForSelector('.leaf:nth-child(2) .fresh.show');
  assert.equal(await held('#sheet h2'), true, 'the description was repainted for a change to docs/a.md');

  // Past the 5 s after which the mark used to go, reviewer or no reviewer.
  await desk.page.waitForTimeout(6000);
  assert.equal(await desk.page.locator('.leaf:nth-child(2) .fresh.show').count(), 1, 'the mark went before the page was opened');
  assert.equal(await held('#sheet h2'), true);

  await desk.page.click('.leaf:nth-child(2)');
  await desk.page.waitForSelector('#sheet >> text=Alpha revised');
  assert.equal(await desk.page.locator('.leaf .fresh.show').count(), 0);

  // The same the other way: the description rewritten while docs/a.md is on screen.
  await hold('#sheet h1');
  await desk.context('body', {text: '## Revised\n\nNew words.'});
  await desk.page.waitForSelector('.leaf:nth-child(1) .fresh.show');
  assert.equal(await held('#sheet h1'), true, 'docs/a.md was repainted for a change to the description');
  await desk.page.click('.leaf:nth-child(1)');
  await desk.page.waitForSelector('#sheet >> text=New words.');
  assert.equal(await desk.page.locator('.leaf .fresh.show').count(), 0);
  assert.deepEqual(desk.errors, []);
});


test('on a desk with no documents, a description rewrite leaves no changed dot that survives clicking the only tab', async () => {
  desk = await open(browser);
  await desk.page.waitForSelector('#sheet h2');
  assert.equal(await desk.page.locator('.leaf').count(), 1);
  await desk.context('body', {text: '## Revised\n\nNew words.'});
  await desk.page.waitForSelector('#sheet >> text=New words.');
  await desk.page.click('.leaf[data-leaf="0"]');
  await desk.page.waitForTimeout(300);
  assert.equal(await desk.page.locator('.leaf .fresh.show').count(), 0, 'the only tab kept a dot nothing can clear');
  assert.deepEqual(desk.errors, []);
});

/* ---------------- day wording across midnight ---------------- */


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
  assert.equal(await link.getAttribute('rel'), 'noopener noreferrer');
  // The harness refuses the mermaid script, so the source block stays, marked for it.
  assert.equal(await desk.page.textContent('#sheet li:nth-child(3) pre > code.language-mermaid'),
    'graph TD\n  A["<b>x</b>"] --> B');
  assert.equal(await desk.page.textContent('#sheet li:nth-child(4) pre > code'),
    '<script>window.__ran=1</script>');
  assert.deepEqual(desk.errors, []);
});

/* ---------------- which link targets become links ---------------- */

// Every link a scheme the page must not follow: the description, carried files
// and replies are written by whoever opened the pull request. The entity forms
// are as typed in the PR text, so they arrive escaped once more by the renderer.
const UNSAFE = [
  ['a', 'javascript:alert(1)'], ['b', 'JavaScript:alert(1)'], ['c', '  javascript:alert(1)'],
  ['d', 'java&#x09;script:alert(1)'], ['g', 'javascript&colon;alert(1)'], ['h', '&#106;avascript:alert(1)'],
  ['e', 'data:text/html;base64,PHNjcmlwdD4='], ['f', 'vbscript:msgbox'],
  // An HTML comment with a / ? or # in it makes the target look scheme-less to
  // the check; the renderer used to strip the comment out of the finished href.
  ['i', 'javascript<!--/-->:window.__ran=1'], ['j', '<!--#-->javascript:window.__ran=1'],
  ['k', '<!--?-->JavaScript:window.__ran=1'], ['l', 'data<!--?-->:text/html,hi'],
];
const unsafeText = UNSAFE.map(([label, url]) => '- [' + label + '](' + url + ') after').join('\n');
const links = sel => desk.page.$$eval(sel + ' a', as => as.map(a => ({href: a.getAttribute('href'),
  protocol: a.protocol, text: a.textContent, target: a.getAttribute('target'), rel: a.getAttribute('rel')})));
// No link in `sel` goes anywhere but http, https or mailto, and every label is on
// the page as text.
const neutralised = async sel => {
  for (const l of await links(sel)) assert.ok(['http:', 'https:', 'mailto:'].includes(l.protocol),
    'a link to ' + l.href + ' (' + l.protocol + ')');
  assert.deepEqual(await links(sel), [], 'an unsafe target still became a link');
  const text = await desk.page.textContent(sel);
  for (const [label] of UNSAFE) assert.ok(text.includes('[' + label + ']'), 'the text of link ' + label + ' is gone');
  assert.equal(await desk.page.evaluate(() => window.__ran), undefined);
};


test('a description\'s javascript:, data: and vbscript: links render as text, not links', async () => {
  await describe(unsafeText + '\n\nAnd [inline](javascript:window.__ran=1) in a paragraph.');
  await neutralised('#sheet');
  assert.ok((await desk.page.textContent('#sheet li:nth-child(1)')).includes('[a](javascript:alert(1)) after'),
    'the reviewer does not see where the link pointed');
  assert.deepEqual(desk.errors, []);
});


test('http, https, mailto, fragment and relative links keep their exact hrefs and open away', async () => {
  await describe([
    '- [ok](https://example.com/x?a=1&b=2)', '- [mail](mailto:a@b.c)', '- [frag](#section)',
    '- [rel](docs/design.md)', '- bare https://example.com here',
    // A colon after the path has started is not a scheme.
    '- [colon](docs/a:b.md)', '- [up](../notes.md?at=10:30)', '- [query](?q=a:b)', '- [plain](HTTP://EXAMPLE.COM/Up)',
  ].join('\n'));
  const got = await links('#sheet');
  assert.deepEqual(got.map(l => [l.text, l.href]), [
    ['ok', 'https://example.com/x?a=1&b=2'], ['mail', 'mailto:a@b.c'], ['frag', '#section'],
    ['rel', 'docs/design.md'], ['https://example.com', 'https://example.com'],
    ['colon', 'docs/a:b.md'], ['up', '../notes.md?at=10:30'], ['query', '?q=a:b'], ['plain', 'HTTP://EXAMPLE.COM/Up'],
  ]);
  for (const l of got){
    assert.equal(l.target, '_blank', l.href);
    assert.deepEqual(l.rel.split(/\s+/).sort(), ['noopener', 'noreferrer'], l.href);
  }
  assert.deepEqual(desk.errors, []);
});


test('safeHref, called directly, allows only http, https, mailto and scheme-less targets', async () => {
  desk = await open(browser);
  // Each input is the text as it sits between the href's quotes; a literal & is
  // written &amp;, as the renderer's escaping leaves it.
  const cases = [
    ['https://example.com/x?a=1&amp;b=2', true], ['HTTP://EXAMPLE.COM', true], ['HtTpS://example.com', true],
    ['mailto:a@b.c', true], ['#section', true], ['#note:1', true], ['docs/design.md', true],
    ['docs/a:b.md', true], ['../up.md?at=10:30', true], ['?q=a:b', true], ['//example.com/x', true],
    ['ht&#x09;tps://example.com', true],
    ['javascript:alert(1)', false], ['JavaScript:alert(1)', false], ['JAVASCRIPT:alert(1)', false],
    ['  javascript:alert(1)', false], ['\u0001\u0008 javascript:alert(1)', false],
    ['java\tscript:alert(1)', false], ['java\nscript:alert(1)', false], ['\njavascript:alert(1)', false],
    ['jav&#x09;ascript:alert(1)', false], ['javascript&colon;alert(1)', false], ['&#106;avascript:alert(1)', false],
    ['java&Tab;script:alert(1)', false], ['&#x20;javascript:alert(1)', false], ['java&amp;#x09;script:alert(1)', false],
    ['data:text/html;base64,PHNjcmlwdD4=', false], ['vbscript:msgbox', false], ['VBScript:msgbox', false],
    ['file:///etc/passwd', false], ['a:b.md', false],
    // Still decoding after four rounds: refused, not decoded without end.
    ['&amp;amp;amp;amp;amp;#106;avascript:alert(1)', false],
  ];
  const got = await desk.page.evaluate(cases => cases.map(([attr]) => {
    // What the browser itself makes of the attribute, resolved against this page:
    // a template's content has no base URL of its own, so its anchors report about:.
    const t = document.createElement('template');
    t.innerHTML = '<a href="' + attr + '"></a>';
    let protocol = null;
    try { protocol = new URL(t.content.firstChild.getAttribute('href'), location.href).protocol; } catch (e) {}
    return {attr, allowed: safeHref(attr), protocol};
  }), cases);
  assert.deepEqual(got.map(g => [g.attr, g.allowed]), cases);
  for (const g of got.filter(g => g.allowed))
    assert.ok(['http:', 'https:', 'mailto:'].includes(g.protocol), JSON.stringify(g));
  // The blocked ones include the forms the browser would really run.
  assert.equal(got.find(g => g.attr === 'java\tscript:alert(1)').protocol, 'javascript:');
  assert.equal(got.find(g => g.attr === 'javascript&colon;alert(1)').protocol, 'javascript:');
});


test('no rewrite after the link check changes an href: comments, bold markers and code spans', async () => {
  desk = await open(browser);
  const got = await desk.page.evaluate(srcs => srcs.map(src => {
    const t = document.createElement('template');
    t.innerHTML = markdown(src);
    return [...t.content.querySelectorAll('a')].map(a =>
      [a.getAttribute('href'), new URL(a.getAttribute('href'), location.href).protocol]);
  }), [
    '[x](javascript<!--/-->:window.__ran=1)', 'see [x](data<!--?-->:text/html,hi) ok',
    '- [x](<!--#-->javascript:alert(1))', 'bare https://e.com/<!--x-->javascript:1',
    '**[y](https://e.com/**z)', 'a `code` [x](docs/`a:b`.md)', 'x\u00000\u0000 [x](https://e.com/\u00000\u0000)',
  ]);
  assert.deepEqual(got, [
    [], [], [],
    [['https://e.com/javascript:1', 'https:']],
    [['https://e.com/**z', 'https:']],
    [],
    [['https://e.com/0', 'https:']],
  ]);
});

// One thread whose one question has an answer stored; the quote is what the
// reviewer highlighted.
const answered = (text, quote) => ({[PR]: {pr: 42, title: 'Harness desk', decision: null, reason: null,
  decidedAt: null, threads: [{id: 't1', name: 'Only', turns: [
    {id: 'u1', role: 'user', content: 'What did you run?', to: 'session', ...(quote ? {quote} : {})},
    {role: 'assistant', via: 'session', answers: 'u1', status: 'done', sentAt: 1000, rungAt: 1400}]}]},
  [REPLIES + '/u1']: {turn: 'u1', status: 'done', text, at: AT}});

