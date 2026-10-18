'use strict';
// Unit tests for plugin/code.js against a fake Figma API (see figma_mock.js for what it models).
// Run: node --test adapters/figma_adapter/tests/
const test = require('node:test');
const assert = require('node:assert/strict');
const plugin = require('../plugin/code.js');
const { MockFigma } = require('./figma_mock.js');

/** Fresh fake Figma per test. */
function setup({ evalOk = true, readOnly = false } = {}) {
  const F = new MockFigma();
  plugin.setFigma(F);
  plugin._state.evalOk = evalOk;
  plugin._state.readOnly = readOnly;
  for (const k of Object.keys(plugin._state.S)) delete plugin._state.S[k];
  return { F, run: (job) => plugin.runJob(job) };
}

const CARD = {
  op: 'build',
  nodes: [{
    t: 'frame', name: 'Card', w: 320, layout: 'v', gap: 8, pad: 16, fill: '#ffffff', radius: 12,
    shadow: '0 4 12 #00000033', as: 'card',
    c: [
      { t: 'text', text: 'Title', size: 20, weight: 700, fill: '#111111', as: 'title' },
      { t: 'rect', name: 'Divider', w: 'fill', h: 1, fill: '#eeeeee' },
      { t: 'text', text: 'Body copy that wraps', size: 14, w: 'fill' },
    ],
  }],
};

// ------------------------------------------------------------------ colors

test('parseColor handles short, long and alpha forms; rejects junk', () => {
  assert.deepEqual(plugin.parseColor('#f00'), { r: 1, g: 0, b: 0, a: 1 });
  const c = plugin.parseColor('#00ff0080');
  assert.equal(c.g, 1);
  assert.ok(Math.abs(c.a - 128 / 255) < 1e-9);
  assert.throws(() => plugin.parseColor('red'), /bad color/);
  assert.equal(plugin.toHex({ r: 1, g: 0.5, b: 0 }), '#ff8000');
});

// ------------------------------------------------------------------ ctx

test('ctx: compact context with capabilities', async () => {
  const { run } = setup();
  const r = await run({ op: 'ctx' });
  assert.equal(r.ok, true);
  assert.equal(r.file, 'Test file');
  assert.deepEqual(r.pages, ['Page 1', 'Page 2']);
  assert.equal(r.page[1], 'Page 1');
  assert.deepEqual(r.sel, []);
  assert.equal(r.caps.eval, true);
  assert.equal(r.ro, false);
});

// ------------------------------------------------------------------ build

test('build: card is constructed correctly and deterministically', async () => {
  const { F, run } = setup();
  const r = await run(structuredClone(CARD));
  assert.equal(r.ok, true, JSON.stringify(r));
  assert.equal(r.created, 4);
  assert.ok(r.ids.card && r.ids.title);
  assert.equal(F.undoCommits, 1, 'one undo step per build');

  const card = F.nodes.get(r.ids.card);
  assert.equal(card.layoutMode, 'VERTICAL');
  assert.equal(card.itemSpacing, 8);
  assert.equal(card.paddingLeft, 16);
  assert.equal(card.cornerRadius, 12);
  assert.equal(card.width, 320);
  assert.equal(card.layoutSizingVertical, 'HUG', 'height hugs when only width was given');
  assert.equal(card.effects[0].type, 'DROP_SHADOW');
  assert.equal(card.effects[0].offset.y, 4);
  assert.ok(Math.abs(card.effects[0].color.a - 0.2) < 0.01);

  const [title, divider, body] = card.children;
  assert.deepEqual(title.fontName, { family: 'Inter', style: 'Bold' });
  assert.equal(title.characters, 'Title');
  assert.equal(title.fontSize, 20);
  assert.equal(divider.fills.length, 1);
  assert.notEqual(divider.fills[0].color.r, 0.77, 'default grey fill must be overridden');
  assert.equal(divider.layoutSizingHorizontal, 'FILL');
  assert.equal(body.layoutSizingHorizontal, 'FILL');
  assert.equal(body.textAutoResize, 'HEIGHT', 'filled text wraps');

  // top-level node was placed at the viewport centre
  assert.equal(card.x, 500 - 160);
  assert.ok(Math.abs(card.y - (300 - card.height / 2)) < 1e-9);
});

test('build: failure rolls everything back and reports the path', async () => {
  const { F, run } = setup();
  const before = F.page1.children.length;
  const r = await run({ op: 'build', nodes: [{ t: 'frame', name: 'Bad', c: [{ t: 'text', text: 'ok' }, { t: 'rect', bogus: 1 }] }] });
  assert.equal(r.ok, false);
  assert.equal(r.code, 'BAD_PROP');
  assert.equal(r.at, 'nodes[0].c[1]');
  assert.ok(r.valid.includes('fill'), 'error lists valid properties');
  assert.equal(F.page1.children.length, before);
  assert.ok(![...F.nodes.values()].some((n) => n.name === 'Bad'));
  assert.equal(F.undoCommits, 0);
});

test('build: fill sizing under a non-auto-layout parent is a clear error and rolls back', async () => {
  const { F, run } = setup();
  const r = await run({ op: 'build', nodes: [{ t: 'frame', c: [{ t: 'rect', w: 'fill', h: 10 }] }] });
  assert.equal(r.ok, false);
  assert.equal(r.code, 'SIZING');
  assert.match(r.error, /auto-layout/);
  assert.equal(F.page1.children.length, 0);
});

test('build: single node shorthand, line, svg, and text-only properties are validated', async () => {
  const { F, run } = setup();
  let r = await run({ op: 'build', t: 'line', w: 200, stroke: '#000000', sw: 2 });
  assert.equal(r.ok, true, JSON.stringify(r));
  const line = F.page1.children[0];
  assert.equal(line.width, 200);
  assert.equal(line.strokeWeight, 2);

  r = await run({ op: 'build', t: 'svg', svg: '<svg/>', name: 'Icon' });
  assert.equal(r.ok, true);

  r = await run({ op: 'build', t: 'rect', text: 'nope' });
  assert.equal(r.ok, false);
  assert.equal(r.code, 'BAD_PROP');
  assert.match(r.error, /only apply to text nodes/);
});

test('build: x/y inside an auto-layout parent is ignored with a warning', async () => {
  const { run } = setup();
  const r = await run({ op: 'build', nodes: [{ t: 'frame', layout: 'h', c: [{ t: 'rect', w: 10, h: 10, x: 50 }] }] });
  assert.equal(r.ok, true, JSON.stringify(r));
  assert.match(r.warn[0], /auto-layout/);
});

test('build: parent id places nodes inside an existing frame at 0,0 (no viewport centring)', async () => {
  const { F, run } = setup();
  const a = await run({ op: 'build', nodes: [{ t: 'frame', name: 'Host', w: 500, h: 500, as: 'host' }] });
  const r = await run({ op: 'build', parent: a.ids.host, nodes: [{ t: 'rect', w: 20, h: 20, fill: '#ff0000' }] });
  assert.equal(r.ok, true, JSON.stringify(r));
  const kid = F.nodes.get(a.ids.host).children[0];
  assert.equal(kid.x, 0);
  assert.equal(kid.y, 0);
});

test('build: instances resolve by name, map friendly property names, and report unknown components', async () => {
  const { F, run } = setup();
  await run({ op: 'build', nodes: [{ t: 'component', name: 'Button/Primary', w: 100, h: 40 }] });
  let r = await run({ op: 'build', nodes: [{ t: 'instance', of: 'Button/Primary', props: { Label: 'Go' } }] });
  assert.equal(r.ok, true, JSON.stringify(r));
  const inst = F.page1.children.find((n) => n.type === 'INSTANCE');
  assert.deepEqual(inst.props, { 'Label#1:0': 'Go' });

  r = await run({ op: 'build', nodes: [{ t: 'instance', of: 'Button/Primry' }] });
  assert.equal(r.code, 'REF_NOT_FOUND');
});

// ------------------------------------------------------------------ fonts, colors, refs

test('fonts: weight maps to style names; italic works; failures list what exists', async () => {
  const { run } = setup();
  let r = await run({ op: 'build', nodes: [{ t: 'text', text: 'a', weight: 600 }] });
  assert.equal(r.ok, true, JSON.stringify(r)); // "Semi Bold" is the second candidate for 600? first is 'Semi Bold'
  r = await run({ op: 'build', nodes: [{ t: 'text', text: 'a', weight: 650 }] });
  assert.equal(r.code, 'BAD_VALUE');
  r = await run({ op: 'build', nodes: [{ t: 'text', text: 'a', font: 'Georgia', weight: 700 }] });
  assert.equal(r.code, 'FONT_NOT_FOUND');
  assert.deepEqual(r.styles, ['Regular', 'Bold Italic']);
  r = await run({ op: 'build', nodes: [{ t: 'text', text: 'a', font: 'Georgia', weight: 700, italic: true }] });
  assert.equal(r.ok, true, JSON.stringify(r));
  r = await run({ op: 'build', nodes: [{ t: 'text', text: 'a', font: 'Nope' }] });
  assert.equal(r.code, 'FONT_NOT_FOUND');
  assert.match(r.hint, /not installed/);
});

test('refs: $name binds a colour variable, falls back to paint styles, suggests near matches', async () => {
  const { F, run } = setup();
  F.colorVars.push({ id: 'V1', name: 'brand/primary' });
  F.paintStyles.push({ id: 'S1', name: 'Surface' });
  let r = await run({ op: 'build', nodes: [{ t: 'rect', fill: '$brand/primary' }] });
  assert.equal(r.ok, true, JSON.stringify(r));
  assert.equal(F.page1.children[0].fills[0].boundVariables.color.id, 'V1');

  r = await run({ op: 'build', nodes: [{ t: 'rect', fill: '$Surface' }] });
  assert.equal(r.ok, true, JSON.stringify(r));
  assert.equal(F.page1.children[1].fillStyleId, 'S1');

  r = await run({ op: 'build', nodes: [{ t: 'rect', fill: '$brand' }] });
  assert.equal(r.code, 'REF_NOT_FOUND');
  assert.deepEqual(r.near, ['brand/primary']);
});

// ------------------------------------------------------------------ reading

test('tree: tabular rows, depth and truncation hints', async () => {
  const { run } = setup();
  await run(structuredClone(CARD));
  let r = await run({ op: 'tree', depth: 5 });
  assert.equal(r.ok, true);
  assert.deepEqual(r.cols.slice(0, 9), ['d', 'id', 'type', 'name', 'x', 'y', 'w', 'h', 'ch']);
  assert.equal(r.rows.length, 4);
  assert.equal(r.rows[0][0], 0);
  assert.equal(r.rows[1][0], 1);
  assert.equal(r.rows[0][2], 'FRAME');
  assert.equal(r.rows[0][8], 3, 'ch = child count');

  r = await run({ op: 'tree', depth: 0 });
  assert.equal(r.rows.length, 1);

  r = await run({ op: 'tree', depth: 5, max: 2 });
  assert.equal(r.trunc, true);
  assert.equal(r.rows.length, 2);
  assert.match(r.hint, /drill/);

  r = await run({ op: 'tree', depth: 1, fields: ['fill', 'text'] });
  assert.deepEqual(r.cols.slice(9), ['fill', 'text']);
  const title = r.rows.find((row) => row[3] === 'text' || row[2] === 'TEXT');
  assert.ok(title);
});

test('tree: by id, by page name, and unknown page', async () => {
  const { F, run } = setup();
  const b = await run(structuredClone(CARD));
  let r = await run({ op: 'tree', id: b.ids.title });
  assert.equal(r.rows.length, 1);
  r = await run({ op: 'tree', page: 'Page 2' });
  assert.deepEqual(r.rows, []);
  r = await run({ op: 'tree', page: 'Nope' });
  assert.equal(r.code, 'PAGE_NOT_FOUND');
  assert.deepEqual(r.pages, ['Page 1', 'Page 2']);
  r = await run({ op: 'tree', id: '9:99' });
  assert.equal(r.code, 'NODE_NOT_FOUND');
  void F;
});

test('get: compact normalized properties, only what applies', async () => {
  const { run } = setup();
  const b = await run(structuredClone(CARD));
  let r = await run({ op: 'get', id: b.ids.card });
  assert.equal(r.ok, true);
  const n = r.node;
  assert.equal(n.fill, '#ffffff');
  assert.equal(n.layout, 'v');
  assert.equal(n.gap, 8);
  assert.equal(n.pad, 16);
  assert.equal(n.sizeV, 'hug');
  assert.equal(n.radius, 12);
  assert.match(n.shadow, /^0 4 12 0 #00000033$/);
  assert.equal(n.text, undefined, 'text fields absent on a frame');

  r = await run({ op: 'get', id: b.ids.title });
  assert.equal(r.node.text, 'Title');
  assert.deepEqual(r.node.font, ['Inter', 'Bold']);
  assert.equal(r.node.layout, undefined);

  r = await run({ op: 'get', ids: [b.ids.card, b.ids.title], fields: 'x,y' });
  assert.equal(r.nodes.length, 2);
  r = await run({ op: 'get', id: b.ids.card, fields: ['wat'] });
  assert.equal(r.code, 'BAD_FIELD');
});

test('find: by type, name, text, with limit', async () => {
  const { run } = setup();
  await run(structuredClone(CARD));
  let r = await run({ op: 'find', type: 'text' });
  assert.equal(r.rows.length, 2);
  r = await run({ op: 'find', name: 'divid' });
  assert.equal(r.rows.length, 1);
  assert.equal(r.rows[0][2], 'Divider');
  r = await run({ op: 'find', text: 'wraps' });
  assert.equal(r.rows.length, 1);
  r = await run({ op: 'find', type: ['TEXT'], limit: 1 });
  assert.equal(r.rows.length, 1);
  assert.equal(r.more, true);
});

test('shot: scale is capped by maxpx and the image comes back as base64', async () => {
  const { F, run } = setup();
  const b = await run({ op: 'build', nodes: [{ t: 'rect', w: 2000, h: 1000, as: 'big' }] });
  let r = await run({ op: 'shot', id: b.ids.big });
  assert.equal(r.ok, true, JSON.stringify(r));
  assert.equal(r.w, 1024);
  assert.equal(r.h, 512);
  assert.ok(Math.abs(F.lastExport.constraint.value - 0.512) < 1e-9);
  assert.equal(Buffer.from(r.bin.b64, 'base64')[1], 80);
  assert.equal(r.bin.mime, 'image/png');

  const s = await run({ op: 'build', nodes: [{ t: 'rect', w: 10, h: 10, as: 'tiny' }] });
  r = await run({ op: 'shot', id: s.ids.tiny, scale: 100 });
  assert.equal(F.lastExport.constraint.value, 4, 'scale capped at 4x');

  r = await run({ op: 'shot' });
  assert.equal(r.code, 'NO_TARGET');
});

// ------------------------------------------------------------------ set

test('set: changes text, colour and weight; warns about x/y in auto-layout', async () => {
  const { F, run } = setup();
  const b = await run(structuredClone(CARD));
  let r = await run({ op: 'set', id: b.ids.title, props: { text: 'New title', fill: '#ff0000', weight: 500 } });
  assert.equal(r.ok, true, JSON.stringify(r));
  const t = F.nodes.get(b.ids.title);
  assert.equal(t.characters, 'New title');
  assert.deepEqual(t.fontName, { family: 'Inter', style: 'Medium' });
  assert.equal(t.fills[0].color.r, 1);

  r = await run({ op: 'set', ids: [b.ids.title], props: { x: 5 } });
  assert.match(r.warn[0], /auto-layout/);

  r = await run({ op: 'set', id: b.ids.card, props: { shadow: '0 1 2 #000000', blur: 4 } });
  assert.equal(r.ok, true);
  assert.equal(F.nodes.get(b.ids.card).effects.length, 2);
  // replacing only the shadow keeps the blur
  r = await run({ op: 'set', id: b.ids.card, props: { shadow: '0 2 4 #000000' } });
  const fx = F.nodes.get(b.ids.card).effects;
  assert.deepEqual(fx.map((e) => e.type).sort(), ['DROP_SHADOW', 'LAYER_BLUR']);

  r = await run({ op: 'set', id: b.ids.card, props: { layout: 'diagonal' } });
  assert.equal(r.code, 'BAD_VALUE');
  r = await run({ op: 'set', id: b.ids.card });
  assert.equal(r.code, 'BAD_SPEC');
});

// ------------------------------------------------------------------ eval

test('eval: results are JSON-safe, nodes become stubs, logs and S persist', async () => {
  const { F, run } = setup();
  await run(structuredClone(CARD));
  let r = await run({ op: 'eval', code: 'S.card = figma.currentPage.children[0]; console.log("hi", 1); return { node: S.card, n: figma.currentPage.children.length, m: figma.mixed };' });
  assert.equal(r.ok, true, JSON.stringify(r));
  assert.deepEqual(Object.keys(r.result.node).sort(), ['id', 'name', 'type']);
  assert.equal(r.result.n, 1);
  assert.equal(r.result.m, 'mixed');
  assert.deepEqual(r.logs, ['hi 1']);
  assert.equal(F.undoCommits, 2, 'eval commits one undo step');

  r = await run({ op: 'eval', code: 'return S.card.name' });
  assert.equal(r.result, 'Card');

  r = await run({ op: 'eval', code: 'const n = await H.node(S.card.id); return H.hex(n.fills[0].color)' });
  assert.equal(r.result, '#ffffff');

  r = await run({ op: 'eval', code: 'throw new Error("boom")' });
  assert.equal(r.ok, false);
  assert.equal(r.code, 'SCRIPT_ERROR');
  assert.equal(r.error, 'boom');
});

test('eval: reports clearly when the sandbox cannot run code strings', async () => {
  const { run } = setup({ evalOk: false });
  const r = await run({ op: 'eval', code: 'return 1' });
  assert.equal(r.ok, false);
  assert.equal(r.code, 'EVAL_UNSUPPORTED');
  assert.match(r.error, /fixed ops/);
});

// ------------------------------------------------------------------ safety / dispatch

test('read-only mode blocks set, build and eval but not reads', async () => {
  const { run } = setup({ readOnly: true });
  for (const job of [{ op: 'set', id: '1:1', props: {} }, { op: 'build', t: 'rect' }, { op: 'eval', code: 'return 1' }]) {
    const r = await run(job);
    assert.equal(r.code, 'READ_ONLY', job.op);
  }
  assert.equal((await run({ op: 'ctx' })).ok, true);
  assert.equal((await run({ op: 'tree' })).ok, true);
});

test('unknown op lists the valid ones', async () => {
  const { run } = setup();
  const r = await run({ op: 'explode' });
  assert.equal(r.code, 'UNKNOWN_OP');
  assert.ok(r.ops.includes('build'));
});

// ------------------------------------------------------------------ v0.2 ops

test('build tags top-level nodes; find --tagged lists only those', async () => {
  const { F, run } = setup();
  const made = await run({ op: 'build', nodes: [{ t: 'frame', name: 'Mine', w: 50, h: 50, c: [{ t: 'rect', name: 'Inner', w: 10, h: 10 }] }] });
  const manual = F.createFrame(); manual.name = 'Theirs'; F.currentPage.appendChild(manual);
  const all = await run({ op: 'find', type: 'FRAME' });
  assert.equal(all.rows.length, 2);
  const tagged = await run({ op: 'find', tagged: true });
  assert.deepEqual(tagged.rows.map((r) => r[2]), ['Mine']);
  assert.ok(made.ok);
});

test('sheet: exports every node at one width and hands bytes to the UI; nothing is created', async () => {
  const { F, run } = setup();
  const b = await run({ op: 'build', nodes: [{ t: 'frame', name: 'A', w: 100, h: 200, as: 'a' }, { t: 'frame', name: 'B', w: 300, h: 100, as: 'b' }] });
  const before = F.nodes.size;
  const r = await run({ op: 'sheet', ids: [b.ids.a, b.ids.b], cell: 240, cols: 2 });
  assert.ok(r.ok);
  assert.equal(r.n, 2);
  assert.equal(r.sheet.parts.length, 2);
  assert.equal(r.sheet.parts[0].name, 'A');
  assert.equal(r.sheet.cell, 240);
  assert.deepEqual(F.exports.map((e) => e.opts.constraint), [{ type: 'WIDTH', value: 240 }, { type: 'WIDTH', value: 240 }]);
  assert.equal(F.nodes.size, before, 'sheet must not touch the document');
});

test('sheet: children mode shows the children of one node, capped at 24', async () => {
  const { run } = setup();
  const kids = Array.from({ length: 30 }, (_, i) => ({ t: 'rect', name: 'k' + i, w: 10, h: 10 }));
  const b = await run({ op: 'build', nodes: [{ t: 'frame', name: 'Wrap', w: 500, h: 500, as: 'w', c: kids }] });
  const r = await run({ op: 'sheet', ids: [b.ids.w], children: true });
  assert.equal(r.n, 24);
  assert.equal(r.skipped, 6);
});

test('image: creates a rectangle with the image fill, keeps the aspect ratio and tags it', async () => {
  const { F, run } = setup();
  const png = Buffer.from([137, 80, 78, 71, 9, 9]).toString('base64');
  const r = await run({ op: 'image', b64: png, w: 400, name: 'Photo' });
  assert.ok(r.ok);
  assert.equal(r.w, 400);
  assert.equal(r.h, 200); // 200x100 source
  const node = F.nodes.get(r.id);
  assert.equal(node.fills[0].type, 'IMAGE');
  assert.equal(node.fills[0].scaleMode, 'FILL');
  assert.equal(node.getPluginData('flue') !== '', true);
});

test('image: --fill puts the image on an existing node', async () => {
  const { F, run } = setup();
  const b = await run({ op: 'build', nodes: [{ t: 'rect', w: 80, h: 80, as: 'r' }] });
  const png = Buffer.from([1, 2, 3]).toString('base64');
  const r = await run({ op: 'image', b64: png, fill: b.ids.r, mode: 'FIT' });
  assert.ok(r.ok);
  assert.equal(F.nodes.get(b.ids.r).fills[0].scaleMode, 'FIT');
});

test('checkpoint saves a named version; image and checkpoint are blocked in read-only mode', async () => {
  const { F, run } = setup();
  const r = await run({ op: 'checkpoint', title: 'Before cleanup', note: 'n' });
  assert.ok(r.ok);
  assert.deepEqual(F.versions, [{ title: 'Before cleanup', description: 'n' }]);
  plugin._state.readOnly = true;
  assert.equal((await run({ op: 'checkpoint', title: 'x' })).code, 'READ_ONLY');
  assert.equal((await run({ op: 'image', b64: 'AA==' })).code, 'READ_ONLY');
  assert.equal((await run({ op: 'sheet', ids: ['1:1'] })).code !== 'READ_ONLY', true, 'sheet only reads');
});
