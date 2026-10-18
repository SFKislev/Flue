'use strict';
// A small fake of the Figma Plugin API, used to unit-test plugin/code.js without Figma.
//
// It is NOT Figma. It models the API rules that most often break scripts so ordering and
// precondition bugs show up here: FILL needs an auto-layout parent, HUG only exists on
// auto-layout frames and text, fonts must be loaded before text is edited, new shapes arrive
// with default fills, and resize() on an auto-layout frame pins both axes. Anything the
// mock does not model must still be confirmed in real Figma (see APP.md "First run").

const AL = (n) => !!n && n.layoutMode !== undefined && n.layoutMode !== 'NONE';

class MockNode {
  constructor(F, type, props = {}) {
    this.F = F;
    this.id = `${F.pageSeq}:${F.seq++}`;
    this.type = type;
    this.name = type.toLowerCase();
    this.parent = null;
    this.visible = true;
    this.x = 0;
    this.y = 0;
    this._w = 100;
    this._h = 100;
    this.rotation = 0;
    this.opacity = 1;
    this._lsh = 'FIXED';
    this._lsv = 'FIXED';
    this.layoutPositioning = 'AUTO';
    Object.assign(this, props);
    F.nodes.set(this.id, this);
  }
  get width() {
    if (this._lsh === 'FILL' && this.parent) return this.parent.width - (this.parent.paddingLeft || 0) - (this.parent.paddingRight || 0);
    if (this._lsh === 'HUG') return this._hug('w');
    return this._w;
  }
  get height() {
    if (this._lsv === 'FILL' && this.parent) return this.parent.height - (this.parent.paddingTop || 0) - (this.parent.paddingBottom || 0);
    if (this._lsv === 'HUG') return this._hug('h');
    return this._h;
  }
  _hug(axis) {
    if (this.type === 'TEXT') return axis === 'w' ? Math.max(1, this.characters.length) * this.fontSize * 0.5 : this.fontSize * 1.2;
    const kids = this.children.filter((c) => c.layoutPositioning !== 'ABSOLUTE');
    const horiz = this.layoutMode === 'HORIZONTAL';
    const size = (c) => (axis === 'w' ? (c._lsh === 'FILL' ? 0 : c.width) : c._lsv === 'FILL' ? 0 : c.height);
    const padA = axis === 'w' ? this.paddingLeft + this.paddingRight : this.paddingTop + this.paddingBottom;
    const along = (axis === 'w') === horiz;
    const vals = kids.map(size);
    const body = along ? vals.reduce((a, b) => a + b, 0) + this.itemSpacing * Math.max(0, vals.length - 1) : Math.max(0, ...vals);
    return body + padA;
  }
  set layoutSizingHorizontal(v) { this._lsh = this._checkSizing(v); }
  get layoutSizingHorizontal() { return this._lsh; }
  set layoutSizingVertical(v) { this._lsv = this._checkSizing(v); }
  get layoutSizingVertical() { return this._lsv; }
  _checkSizing(v) {
    if (v === 'FILL' && !AL(this.parent)) throw new Error('FILL can only be set on children of auto-layout frames');
    if (v === 'HUG' && !(this.type === 'TEXT' || AL(this))) throw new Error('HUG can only be set on auto-layout frames and text nodes');
    return v;
  }
  resize(w, h) {
    this._w = w;
    this._h = h;
    if (AL(this)) {
      this._lsh = 'FIXED';
      this._lsv = 'FIXED';
    }
    if (this.type === 'TEXT') {
      // fixed width + auto height is textAutoResize "HEIGHT"; anything else pins both
      this._lsh = 'FIXED';
      this._lsv = this.textAutoResize === 'HEIGHT' ? 'HUG' : 'FIXED';
    }
  }
  remove() {
    if (this.parent) this.parent.children.splice(this.parent.children.indexOf(this), 1);
    this.parent = null;
    const drop = (n) => { this.F.nodes.delete(n.id); (n.children || []).forEach(drop); };
    drop(this);
  }
  setPluginData(k, v) { (this._pd = this._pd || {})[k] = v; }
  getPluginData(k) { return (this._pd || {})[k] || ''; }
  async exportAsync(opts) {
    this.F.lastExport = opts;
    (this.F.exports = this.F.exports || []).push({ id: this.id, opts });
    return new Uint8Array([137, 80, 78, 71, 1, 2, 3]);
  }
}

function containerMixin(node) {
  node.children = [];
  node.appendChild = function (child) {
    if (child.parent) child.parent.children.splice(child.parent.children.indexOf(child), 1);
    child.parent = this;
    this.children.push(child);
  };
  node.findAllWithCriteria = function ({ types }) {
    const out = [];
    const walk = (n) => (n.children || []).forEach((c) => { if (types.includes(c.type)) out.push(c); walk(c); });
    walk(this);
    return out;
  };
  return node;
}

function frameLike(F, type, extra = {}) {
  const n = new MockNode(F, type, {
    layoutMode: 'NONE', itemSpacing: 0, paddingTop: 0, paddingRight: 0, paddingBottom: 0, paddingLeft: 0,
    primaryAxisAlignItems: 'MIN', counterAxisAlignItems: 'MIN', layoutWrap: 'NO_WRAP', clipsContent: true,
    fills: [{ type: 'SOLID', color: { r: 1, g: 1, b: 1 } }], strokes: [], strokeWeight: 1, strokeAlign: 'INSIDE',
    cornerRadius: 0, effects: [], ...extra,
  });
  return containerMixin(n);
}

class MockFigma {
  constructor() {
    this.mixed = Symbol('mixed');
    this.apiVersion = '1.0.0';
    this.editorType = 'figma';
    this.seq = 1;
    this.pageSeq = 0;
    this.nodes = new Map();
    this.undoCommits = 0;
    this.lastExport = null;
    this.fonts = { Inter: ['Regular', 'Medium', 'Semi Bold', 'Bold'], Georgia: ['Regular', 'Bold Italic'] };
    this.loaded = new Set();
    this.viewport = { center: { x: 500, y: 300 }, zoom: 1 };
    this.colorVars = [];
    this.paintStyles = [];
    this.textStyles = [];
    const self = this;
    this.variables = {
      getLocalVariablesAsync: async () => self.colorVars,
      setBoundVariableForPaint: (paint, field, v) => ({ ...paint, boundVariables: { [field]: { type: 'VARIABLE_ALIAS', id: v.id } } }),
    };
    this.root = containerMixin(new MockNode(this, 'DOCUMENT', { name: 'Test file' }));
    this.pageSeq = 0;
    this.page1 = this._page('Page 1');
    this.page2 = this._page('Page 2');
    this._current = this.page1;
  }
  _page(name) {
    const p = containerMixin(new MockNode(this, 'PAGE', { name, selection: [] }));
    p.loadAsync = async () => {};
    this.root.appendChild(p);
    return p;
  }
  get currentPage() { return this._current; }
  async setCurrentPageAsync(p) { this._current = p; }
  async loadAllPagesAsync() {}
  async getNodeByIdAsync(id) { return this.nodes.get(id) || null; }
  commitUndo() { this.undoCommits++; }
  base64Encode(bytes) { return Buffer.from(bytes).toString('base64'); }
  base64Decode(b64) { return new Uint8Array(Buffer.from(b64, 'base64')); }
  createImage(bytes) { this.lastImageBytes = bytes; return { hash: 'hash-' + bytes.length, getSizeAsync: async () => ({ width: 200, height: 100 }) }; }
  async saveVersionHistoryAsync(title, description) { (this.versions = this.versions || []).push({ title, description }); return { id: 'v1' }; }
  on() {}

  createFrame() { return frameLike(this, 'FRAME'); }
  createComponent() {
    const c = frameLike(this, 'COMPONENT');
    c.createInstance = () => {
      const inst = new MockNode(this, 'INSTANCE', { name: c.name, componentProperties: { 'Label#1:0': { type: 'TEXT', value: 'Button' } }, layoutMode: 'NONE', fills: [], strokes: [], effects: [], clipsContent: true });
      inst.children = [];
      inst.appendChild = () => { throw new Error('instances are not containers in this mock'); };
      inst.getMainComponentAsync = async () => c;
      inst.setProperties = (m) => { for (const k of Object.keys(m)) if (!(k in inst.componentProperties)) throw new Error(`no such property ${k}`); inst.props = m; };
      return inst;
    };
    return c;
  }
  createRectangle() {
    // Real shapes arrive with a default fill; the builder must not depend on it.
    return new MockNode(this, 'RECTANGLE', { fills: [{ type: 'SOLID', color: { r: 0.77, g: 0.77, b: 0.77 } }], strokes: [], strokeWeight: 1, strokeAlign: 'INSIDE', cornerRadius: 0, effects: [] });
  }
  createEllipse() {
    return new MockNode(this, 'ELLIPSE', { fills: [{ type: 'SOLID', color: { r: 0.77, g: 0.77, b: 0.77 } }], strokes: [], strokeWeight: 1, strokeAlign: 'INSIDE', effects: [] });
  }
  createLine() {
    return new MockNode(this, 'LINE', { _h: 0, strokes: [{ type: 'SOLID', color: { r: 0, g: 0, b: 0 } }], strokeWeight: 1, strokeAlign: 'CENTER', effects: [] });
  }
  createNodeFromSvg() { const f = frameLike(this, 'FRAME'); f.name = 'svg'; return f; }
  createText() {
    const F = this;
    const t = new MockNode(this, 'TEXT', { _lsh: 'HUG', _lsv: 'HUG', fills: [{ type: 'SOLID', color: { r: 0, g: 0, b: 0 } }], strokes: [], effects: [], textAutoResize: 'WIDTH_AND_HEIGHT', textAlignHorizontal: 'LEFT', lineHeight: { unit: 'AUTO' }, letterSpacing: { unit: 'PIXELS', value: 0 } });
    const key = (f) => `${f.family}|${f.style}`;
    let chars = '';
    let font = { family: 'Inter', style: 'Regular' };
    let size = 12;
    const need = () => { if (!F.loaded.has(key(font))) throw new Error(`unloaded font ${key(font)}`); };
    Object.defineProperty(t, 'characters', { get: () => chars, set: (v) => { need(); chars = v; }, enumerable: true });
    Object.defineProperty(t, 'fontName', { get: () => font, set: (v) => { if (!F.loaded.has(key(v))) throw new Error(`unloaded font ${key(v)}`); font = v; }, enumerable: true });
    Object.defineProperty(t, 'fontSize', { get: () => size, set: (v) => { need(); size = v; }, enumerable: true });
    t.getRangeAllFontNames = () => [font];
    t.setTextStyleIdAsync = async (id) => { t.textStyleId = id; };
    return t;
  }
  async loadFontAsync(f) {
    if (!(this.fonts[f.family] || []).includes(f.style)) throw new Error(`font not found ${f.family} ${f.style}`);
    this.loaded.add(`${f.family}|${f.style}`);
  }
  async listAvailableFontsAsync() {
    return Object.entries(this.fonts).flatMap(([family, styles]) => styles.map((style) => ({ fontName: { family, style } })));
  }
  async getLocalPaintStylesAsync() { return this.paintStyles; }
  async getLocalTextStylesAsync() { return this.textStyles; }
  async importComponentByKeyAsync() { throw new Error('not modelled'); }
}

// shared helpers for paint/fill assertions
for (const proto of [MockNode.prototype]) {
  proto.setFillStyleIdAsync = async function (id) { this.fillStyleId = id; };
  proto.setStrokeStyleIdAsync = async function (id) { this.strokeStyleId = id; };
}

module.exports = { MockFigma, MockNode };
