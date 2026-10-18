// @ts-check
// (Type-check with: cd plugin && npm i && npx tsc -p .   - see tsconfig.json)
//
// Flue Bridge for Figma - plugin main thread. Plain JS, no build step.
//
// Data flow:  agent shell -> figma_bridge.py -> local daemon <- (poll) ui.html <-> this file -> figma.*
//
// Jobs arrive as {id, op, ...args}; results leave as {ok, ...} (JSON-safe).
// Ops: ctx, tree, get, find, set, build, shot, sheet, image, checkpoint, eval.
//
// Design goals: small outputs (tabular rows, short keys, rounded numbers), deterministic
// builds (no reliance on API defaults), atomic builds (roll back on error), one undo step.

'use strict';

const VERSION = '0.2.0';
const TAG = 'flue';

/** @type {PluginAPI} */
let F = typeof figma !== 'undefined' ? figma : /** @type {any} */ (null);
/** Swap the Figma API object (used by tests). @param {any} f */
function setFigma(f) {
  F = f;
}

/** Scratch object that survives between eval calls. @type {Record<string, any>} */
const S = {};
let READ_ONLY = false;
let EVAL_OK = false;
/** Per-job lookup cache (variables, styles, components). @type {Record<string, any>} */
let CACHE = {};

const AsyncFunction = Object.getPrototypeOf(async function () {}).constructor;

// ---------------------------------------------------------------- errors

class FlueError extends Error {
  /** @param {string} code @param {string} message @param {any} [extra] */
  constructor(code, message, extra) {
    super(message);
    this.code = code;
    this.extra = extra;
  }
}

/** @param {string} code @param {string} message @param {any} [extra] @returns {never} */
function fail(code, message, extra) {
  throw new FlueError(code, message, extra);
}

// ---------------------------------------------------------------- small helpers

/** @param {any} n */
const r2 = (n) => (typeof n === 'number' ? Math.round(n * 100) / 100 : n);

/** @param {any} v @param {string} what */
function num(v, what) {
  if (typeof v !== 'number' || !isFinite(v)) fail('BAD_VALUE', `${what} must be a number, got ${JSON.stringify(v)}`);
  return v;
}

/** @param {string} s */
function parseColor(s) {
  const m = /^#([0-9a-f]{3,4}|[0-9a-f]{6}|[0-9a-f]{8})$/i.exec(String(s).trim());
  if (!m) fail('BAD_COLOR', `bad color ${JSON.stringify(s)}: use #rgb, #rrggbb, #rrggbbaa, "none" or "$name"`);
  let h = m[1];
  if (h.length <= 4) h = h.split('').map((c) => c + c).join('');
  const n = (/** @type {number} */ i) => parseInt(h.slice(i, i + 2), 16) / 255;
  return { r: n(0), g: n(2), b: n(4), a: h.length === 8 ? n(6) : 1 };
}

/** @param {number} v */
const h2 = (v) => Math.round(Math.min(1, Math.max(0, v)) * 255).toString(16).padStart(2, '0');

/** @param {{r:number,g:number,b:number}} c @param {number} [a] */
function toHex(c, a) {
  let s = '#' + h2(c.r) + h2(c.g) + h2(c.b);
  if (a !== undefined && a < 1) s += h2(a);
  return s;
}

/** @param {string} str @returns {SolidPaint} */
function solid(str) {
  const c = parseColor(str);
  return c.a < 1
    ? { type: 'SOLID', color: { r: c.r, g: c.g, b: c.b }, opacity: c.a }
    : { type: 'SOLID', color: { r: c.r, g: c.g, b: c.b } };
}

/** Is this node an auto-layout container? @param {any} n */
const isAL = (n) => !!n && 'layoutMode' in n && n.layoutMode !== 'NONE';

// ---------------------------------------------------------------- node lookup

/** Make sure the page that holds `n` is loaded (documentAccess: dynamic-page). @param {any} n */
async function ensureLoaded(n) {
  let p = n;
  while (p && p.type !== 'PAGE' && p.type !== 'DOCUMENT') p = p.parent;
  if (p && p.type === 'PAGE' && typeof p.loadAsync === 'function') await p.loadAsync();
}

/** @param {string} id */
async function nodeById(id) {
  if (typeof id !== 'string' || !id) fail('BAD_ID', 'missing node id');
  const n = await F.getNodeByIdAsync(id);
  if (!n) fail('NODE_NOT_FOUND', `no node with id ${id}`);
  await ensureLoaded(n);
  return n;
}

// ---------------------------------------------------------------- paints / effects (read)

/** @param {any} p */
function paintOut(p) {
  if (p.type === 'SOLID') return toHex(p.color, p.opacity === undefined ? 1 : p.opacity);
  if (String(p.type).startsWith('GRADIENT')) {
    return {
      g: String(p.type).slice(9).toLowerCase(),
      stops: p.gradientStops.map((/** @type {any} */ s) => [r2(s.position), toHex(s.color, s.color.a)]),
    };
  }
  if (p.type === 'IMAGE') return { img: p.imageHash, mode: p.scaleMode };
  return { type: p.type };
}

/** @param {any} paints */
function paintsOut(paints) {
  if (paints === F.mixed) return 'mixed';
  const out = paints.filter((/** @type {any} */ p) => p.visible !== false).map(paintOut);
  if (!out.length) return 'none';
  return out.length === 1 ? out[0] : out;
}

/** @param {any} e */
function shadowOut(e) {
  const c = toHex(e.color, e.color.a);
  return `${e.type === 'INNER_SHADOW' ? 'inner ' : ''}${r2(e.offset.x)} ${r2(e.offset.y)} ${r2(e.radius)} ${r2(e.spread || 0)} ${c}`;
}

/** @param {any} n */
function padOut(n) {
  const { paddingTop: t, paddingRight: r, paddingBottom: b, paddingLeft: l } = n;
  if (t === r && r === b && b === l) return t;
  if (t === b && l === r) return [t, l];
  return [t, r, b, l];
}

const MAIN_OUT = { MIN: 'start', CENTER: 'center', MAX: 'end', SPACE_BETWEEN: 'between', SPACE_EVENLY: 'evenly', SPACE_AROUND: 'around' };
const CROSS_OUT = { MIN: 'start', CENTER: 'center', MAX: 'end', BASELINE: 'base' };
const TA_OUT = { LEFT: 'left', CENTER: 'center', RIGHT: 'right', JUSTIFIED: 'justify' };

/** @param {any} v */
function lineOut(v) {
  if (v === F.mixed) return 'mixed';
  if (v.unit === 'AUTO') return 'auto';
  return v.unit === 'PERCENT' ? `${r2(v.value)}%` : r2(v.value);
}

/**
 * Field readers. Each returns undefined when the field does not apply to the node,
 * so serialized objects only carry what is meaningful.
 * @type {Record<string, (n: any) => any>}
 */
const FIELDS = {
  x: (n) => ('x' in n ? r2(n.x) : undefined),
  y: (n) => ('y' in n ? r2(n.y) : undefined),
  w: (n) => ('width' in n ? r2(n.width) : undefined),
  h: (n) => ('height' in n ? r2(n.height) : undefined),
  rot: (n) => ('rotation' in n && n.rotation ? r2(n.rotation) : undefined),
  fill: (n) => ('fills' in n ? paintsOut(n.fills) : undefined),
  stroke: (n) => ('strokes' in n && n.strokes.length ? paintsOut(n.strokes) : undefined),
  sw: (n) => ('strokes' in n && n.strokes.length ? r2(n.strokeWeight === F.mixed ? 'mixed' : n.strokeWeight) : undefined),
  sa: (n) => ('strokes' in n && n.strokes.length && n.strokeAlign ? String(n.strokeAlign).toLowerCase() : undefined),
  radius: (n) => {
    if (!('cornerRadius' in n)) return undefined;
    if (n.cornerRadius === F.mixed) return [n.topLeftRadius, n.topRightRadius, n.bottomRightRadius, n.bottomLeftRadius];
    return n.cornerRadius || undefined;
  },
  opacity: (n) => ('opacity' in n && n.opacity !== 1 ? r2(n.opacity) : undefined),
  vis: (n) => (n.visible === false ? false : undefined),
  clip: (n) => (n.type === 'FRAME' || n.type === 'COMPONENT' || n.type === 'INSTANCE' ? n.clipsContent : undefined),
  layout: (n) => {
    if (!('layoutMode' in n)) return undefined;
    return n.layoutMode === 'NONE' ? 'none' : n.layoutMode === 'HORIZONTAL' ? 'h' : 'v';
  },
  gap: (n) => (isAL(n) ? n.itemSpacing : undefined),
  pad: (n) => (isAL(n) ? padOut(n) : undefined),
  main: (n) => (isAL(n) ? /** @type {any} */ (MAIN_OUT)[n.primaryAxisAlignItems] : undefined),
  cross: (n) => (isAL(n) ? /** @type {any} */ (CROSS_OUT)[n.counterAxisAlignItems] : undefined),
  wrap: (n) => (isAL(n) && n.layoutWrap === 'WRAP' ? true : undefined),
  sizeH: (n) => ('layoutSizingHorizontal' in n && n.layoutSizingHorizontal !== 'FIXED' ? String(n.layoutSizingHorizontal).toLowerCase() : undefined),
  sizeV: (n) => ('layoutSizingVertical' in n && n.layoutSizingVertical !== 'FIXED' ? String(n.layoutSizingVertical).toLowerCase() : undefined),
  abs: (n) => (n.layoutPositioning === 'ABSOLUTE' ? true : undefined),
  text: (n) => (n.type === 'TEXT' ? n.characters : undefined),
  font: (n) => (n.type === 'TEXT' ? (n.fontName === F.mixed ? 'mixed' : [n.fontName.family, n.fontName.style]) : undefined),
  size: (n) => (n.type === 'TEXT' ? r2(n.fontSize === F.mixed ? 'mixed' : n.fontSize) : undefined),
  lh: (n) => (n.type === 'TEXT' ? lineOut(n.lineHeight) : undefined),
  ls: (n) => {
    if (n.type !== 'TEXT') return undefined;
    const v = n.letterSpacing;
    if (v === F.mixed) return 'mixed';
    return v.value ? (v.unit === 'PERCENT' ? `${r2(v.value)}%` : r2(v.value)) : undefined;
  },
  ta: (n) => (n.type === 'TEXT' ? /** @type {any} */ (TA_OUT)[n.textAlignHorizontal] : undefined),
  shadow: (n) => {
    if (!('effects' in n)) return undefined;
    const s = n.effects.filter((/** @type {any} */ e) => e.visible !== false && e.type.endsWith('SHADOW')).map(shadowOut);
    return s.length ? (s.length === 1 ? s[0] : s) : undefined;
  },
  blur: (n) => {
    if (!('effects' in n)) return undefined;
    const b = n.effects.find((/** @type {any} */ e) => e.visible !== false && e.type === 'LAYER_BLUR');
    return b ? r2(b.radius) : undefined;
  },
  of: async (n) => {
    if (n.type !== 'INSTANCE') return undefined;
    const m = await n.getMainComponentAsync();
    return m ? [m.id, m.name] : null;
  },
  ch: (n) => ('children' in n ? n.children.length : undefined),
  pid: (n) => (n.parent ? n.parent.id : undefined),
};

const COMMON = ['x', 'y', 'w', 'h', 'fill', 'stroke', 'sw', 'radius', 'opacity', 'layout', 'gap', 'pad', 'main', 'cross', 'sizeH', 'sizeV', 'text', 'font', 'size', 'shadow', 'of', 'ch'];

/** @param {any} fields */
function resolveFields(fields) {
  if (fields === undefined || fields === null) return COMMON;
  if (fields === 'all') return Object.keys(FIELDS);
  const list = Array.isArray(fields) ? fields : String(fields).split(',').map((s) => s.trim()).filter(Boolean);
  const out = [];
  for (const f of list) {
    if (f === 'all') return Object.keys(FIELDS);
    if (!FIELDS[f]) fail('BAD_FIELD', `unknown field "${f}"`, { valid: Object.keys(FIELDS) });
    out.push(f);
  }
  return out;
}

/** @param {any} n @param {string[]} fields */
async function ser(n, fields) {
  /** @type {Record<string, any>} */
  const out = { id: n.id, type: n.type, name: n.name };
  for (const f of fields) {
    const v = await FIELDS[f](n);
    if (v !== undefined) out[f] = v;
  }
  return out;
}

// ---------------------------------------------------------------- property writers

const KNOWN = new Set([
  'name', 'vis', 'opacity', 'x', 'y', 'w', 'h', 'rot', 'fill', 'stroke', 'sw', 'sa', 'radius', 'clip',
  'layout', 'gap', 'pad', 'main', 'cross', 'wrap', 'sizeH', 'sizeV', 'abs',
  'text', 'font', 'weight', 'style', 'italic', 'size', 'lh', 'ls', 'ta', 'ts',
  'shadow', 'blur',
]);

const WEIGHT_STYLES = /** @type {Record<number, string[]>} */ ({
  100: ['Thin'],
  200: ['Extra Light', 'ExtraLight', 'Ultra Light'],
  300: ['Light'],
  400: ['Regular'],
  500: ['Medium'],
  600: ['Semi Bold', 'SemiBold', 'Semibold', 'Demi Bold'],
  700: ['Bold'],
  800: ['Extra Bold', 'ExtraBold', 'Ultra Bold'],
  900: ['Black', 'Heavy'],
});

const MAIN_IN = /** @type {Record<string, string>} */ ({ start: 'MIN', center: 'CENTER', end: 'MAX', between: 'SPACE_BETWEEN', evenly: 'SPACE_EVENLY', around: 'SPACE_AROUND' });
const CROSS_IN = /** @type {Record<string, string>} */ ({ start: 'MIN', center: 'CENTER', end: 'MAX', base: 'BASELINE' });
const TA_IN = /** @type {Record<string, string>} */ ({ left: 'LEFT', center: 'CENTER', right: 'RIGHT', justify: 'JUSTIFIED' });
const SA_IN = /** @type {Record<string, string>} */ ({ inside: 'INSIDE', center: 'CENTER', outside: 'OUTSIDE' });
const SIZING_IN = /** @type {Record<string, string>} */ ({ fill: 'FILL', hug: 'HUG', fixed: 'FIXED' });

/** Look up a map entry or fail with the valid choices. @param {Record<string,string>} map @param {any} key @param {string} what */
function pick(map, key, what) {
  const v = map[String(key)];
  if (!v) fail('BAD_VALUE', `${what}: "${key}" is not one of ${Object.keys(map).join('|')}`);
  return v;
}

/** @param {any} node @param {string} family @param {any} p */
async function pickFont(node, family, p) {
  const italic = !!p.italic;
  let styles;
  if (p.style) {
    styles = [String(p.style)];
  } else {
    const w = p.weight === undefined ? 400 : Number(p.weight);
    const base = WEIGHT_STYLES[w];
    if (!base) fail('BAD_VALUE', `weight ${p.weight}: use 100..900 in steps of 100`);
    styles = base.map((s) => (italic ? (s === 'Regular' ? 'Italic' : s + ' Italic') : s));
  }
  for (const style of styles) {
    try {
      await F.loadFontAsync({ family, style });
      return { family, style };
    } catch (e) {
      /* try next candidate */
    }
  }
  const all = await F.listAvailableFontsAsync();
  const avail = all.filter((/** @type {any} */ f) => f.fontName.family === family).map((/** @type {any} */ f) => f.fontName.style);
  fail('FONT_NOT_FOUND', `font "${family}" with style ${styles.join('/')} is not available`, avail.length ? { styles: avail.slice(0, 30) } : { hint: 'family not installed or misspelled' });
}

/** Load every font used by a text node so it can be edited. @param {any} node */
async function loadNodeFonts(node) {
  if (node.fontName !== F.mixed) {
    await F.loadFontAsync(node.fontName);
    return;
  }
  const names = node.getRangeAllFontNames(0, node.characters.length);
  for (const fn of names) await F.loadFontAsync(fn);
}

/** @param {any} v @param {string} what */
function lineInput(v, what) {
  if (v === 'auto') return { unit: 'AUTO' };
  if (typeof v === 'string' && v.endsWith('%')) return { unit: 'PERCENT', value: num(parseFloat(v), what) };
  return { unit: 'PIXELS', value: num(v, what) };
}

/** @param {any} node @param {any} p */
async function applyText(node, p) {
  const fontChange = p.font !== undefined || p.weight !== undefined || p.style !== undefined || p.italic !== undefined;
  if (fontChange) {
    const cur = node.fontName === F.mixed ? { family: 'Inter', style: 'Regular' } : node.fontName;
    const target = await pickFont(node, p.font !== undefined ? String(p.font) : cur.family, p);
    await loadNodeFonts(node); // current fonts must be loaded before replacing them
    node.fontName = target;
  } else {
    await loadNodeFonts(node);
  }
  if (p.ts !== undefined) {
    const st = (await getTextStyles()).find((/** @type {any} */ s) => s.name === p.ts);
    if (!st) fail('REF_NOT_FOUND', `no text style named "${p.ts}"`, { near: near(await getTextStyles(), p.ts) });
    await F.loadFontAsync(st.fontName);
    await node.setTextStyleIdAsync(st.id);
  }
  if (p.text !== undefined) node.characters = String(p.text);
  if (p.size !== undefined) node.fontSize = num(p.size, 'size');
  if (p.lh !== undefined) node.lineHeight = lineInput(p.lh, 'lh');
  if (p.ls !== undefined) {
    const l = lineInput(p.ls, 'ls');
    if (l.unit === 'AUTO') fail('BAD_VALUE', 'ls: use a number (px) or "12%"');
    node.letterSpacing = l;
  }
  if (p.ta !== undefined) node.textAlignHorizontal = pick(TA_IN, p.ta, 'ta');
}

/** @param {any[]} list @param {string} name */
function near(list, name) {
  const q = String(name).toLowerCase();
  return list.filter((x) => x.name.toLowerCase().includes(q) || q.includes(x.name.toLowerCase())).slice(0, 5).map((x) => x.name);
}

async function getColorVars() {
  if (!CACHE.vars) CACHE.vars = await F.variables.getLocalVariablesAsync('COLOR');
  return CACHE.vars;
}
async function getPaintStyles() {
  if (!CACHE.paintStyles) CACHE.paintStyles = await F.getLocalPaintStylesAsync();
  return CACHE.paintStyles;
}
async function getTextStyles() {
  if (!CACHE.textStyles) CACHE.textStyles = await F.getLocalTextStylesAsync();
  return CACHE.textStyles;
}

/** @param {any} node @param {'fills'|'strokes'} prop @param {any} value */
async function setPaints(node, prop, value) {
  if (!(prop in node)) fail('BAD_PROP', `${prop === 'fills' ? 'fill' : 'stroke'} is not supported on ${node.type}`);
  if (value === 'none' || value === null || value === false) {
    node[prop] = [];
    return;
  }
  if (typeof value === 'string' && value[0] === '$') {
    const name = value.slice(1);
    const v = (await getColorVars()).find((/** @type {any} */ x) => x.name === name);
    if (v) {
      node[prop] = [F.variables.setBoundVariableForPaint(solid('#000000'), 'color', v)];
      return;
    }
    const st = (await getPaintStyles()).find((/** @type {any} */ x) => x.name === name);
    if (st) {
      if (prop === 'fills') await node.setFillStyleIdAsync(st.id);
      else await node.setStrokeStyleIdAsync(st.id);
      return;
    }
    const pool = [...(await getColorVars()), ...(await getPaintStyles())];
    fail('REF_NOT_FOUND', `no color variable or paint style named "${name}"`, { near: near(pool, name) });
  }
  if (typeof value === 'string') {
    node[prop] = [solid(value)];
    return;
  }
  if (Array.isArray(value) && value.every((v) => typeof v === 'string' && v[0] === '#')) {
    node[prop] = value.map(solid);
    return;
  }
  fail('BAD_FILL', 'gradients and images are not supported by the fill shorthand; use an eval script');
}

/** @param {string} s */
function shadowIn(s) {
  const toks = String(s).trim().split(/\s+/);
  const inner = toks[0] === 'inner';
  if (inner) toks.shift();
  const color = toks.pop();
  const nums = toks.map(Number);
  if (!color || nums.length < 3 || nums.length > 4 || nums.some((x) => !isFinite(x))) {
    fail('BAD_VALUE', `shadow "${s}": use "[inner] x y blur [spread] #color", e.g. "0 4 12 #00000033"`);
  }
  const c = parseColor(color);
  return {
    type: inner ? 'INNER_SHADOW' : 'DROP_SHADOW',
    color: { r: c.r, g: c.g, b: c.b, a: c.a },
    offset: { x: nums[0], y: nums[1] },
    radius: nums[2],
    spread: nums[3] || 0,
    visible: true,
    blendMode: 'NORMAL',
  };
}

/** @param {any} node @param {any} pad */
function setPad(node, pad) {
  /** @type {number[]} */
  let [t, r, b, l] = [0, 0, 0, 0];
  if (typeof pad === 'number') [t, r, b, l] = [pad, pad, pad, pad];
  else if (Array.isArray(pad) && pad.length === 2) [t, r, b, l] = [pad[0], pad[1], pad[0], pad[1]];
  else if (Array.isArray(pad) && pad.length === 4) [t, r, b, l] = pad;
  else fail('BAD_VALUE', 'pad: use n, [vertical, horizontal] or [top, right, bottom, left]');
  node.paddingTop = num(t, 'pad');
  node.paddingRight = num(r, 'pad');
  node.paddingBottom = num(b, 'pad');
  node.paddingLeft = num(l, 'pad');
}

/**
 * Apply properties to a node. Sizing keywords ("fill"/"hug") and absolute positioning
 * depend on the parent, so they are returned for the caller to apply after attaching.
 * @param {any} node @param {Record<string, any>} p @param {string[]} warn
 * @returns {Promise<{h?: string, v?: string, abs?: boolean}>}
 */
async function applyProps(node, p, warn) {
  for (const k of Object.keys(p)) {
    if (!KNOWN.has(k)) fail('BAD_PROP', `unknown property "${k}"`, { valid: [...KNOWN] });
  }
  const isText = node.type === 'TEXT';
  const textKeys = ['text', 'font', 'weight', 'style', 'italic', 'size', 'lh', 'ls', 'ta', 'ts'];
  if (isText) await applyText(node, p);
  else if (textKeys.some((k) => k in p)) fail('BAD_PROP', `text properties (${textKeys.filter((k) => k in p).join(', ')}) only apply to text nodes, not ${node.type}`);

  if (p.layout !== undefined) {
    if (!('layoutMode' in node)) fail('BAD_PROP', `layout is not supported on ${node.type}`);
    node.layoutMode = pick({ h: 'HORIZONTAL', v: 'VERTICAL', none: 'NONE' }, p.layout, 'layout');
  }
  if (['gap', 'pad', 'main', 'cross', 'wrap'].some((k) => k in p) && !isAL(node)) {
    fail('BAD_PROP', 'gap/pad/main/cross/wrap need layout:"h" or "v" on the same node');
  }
  if (p.gap !== undefined) node.itemSpacing = num(p.gap, 'gap');
  if (p.pad !== undefined) setPad(node, p.pad);
  if (p.main !== undefined) node.primaryAxisAlignItems = pick(MAIN_IN, p.main, 'main');
  if (p.cross !== undefined) node.counterAxisAlignItems = pick(CROSS_IN, p.cross, 'cross');
  if (p.wrap !== undefined) node.layoutWrap = p.wrap ? 'WRAP' : 'NO_WRAP';

  if (p.radius !== undefined) {
    if (!('cornerRadius' in node)) fail('BAD_PROP', `radius is not supported on ${node.type}`);
    if (Array.isArray(p.radius) && p.radius.length === 4) {
      [node.topLeftRadius, node.topRightRadius, node.bottomRightRadius, node.bottomLeftRadius] = p.radius.map((/** @type {any} */ v) => num(v, 'radius'));
    } else {
      node.cornerRadius = num(p.radius, 'radius');
    }
  }
  if (p.clip !== undefined) node.clipsContent = !!p.clip;
  if (p.fill !== undefined) await setPaints(node, 'fills', p.fill);
  if (p.stroke !== undefined) await setPaints(node, 'strokes', p.stroke);
  if (p.sw !== undefined) node.strokeWeight = num(p.sw, 'sw');
  if (p.sa !== undefined) node.strokeAlign = pick(SA_IN, p.sa, 'sa');

  if (p.shadow !== undefined || p.blur !== undefined) {
    if (!('effects' in node)) fail('BAD_PROP', `shadow/blur are not supported on ${node.type}`);
    const keep = node.effects.filter((/** @type {any} */ e) => {
      const isShadow = String(e.type).endsWith('SHADOW');
      if (p.shadow !== undefined && isShadow) return false;
      if (p.blur !== undefined && e.type === 'LAYER_BLUR') return false;
      return true;
    });
    const add = [];
    if (p.shadow) for (const s of [].concat(p.shadow)) add.push(shadowIn(s));
    if (p.blur) add.push({ type: 'LAYER_BLUR', blurType: 'NORMAL', radius: num(p.blur, 'blur'), visible: true });
    node.effects = [...keep, ...add];
  }
  if (p.opacity !== undefined) node.opacity = num(p.opacity, 'opacity');
  if (p.vis !== undefined) node.visible = !!p.vis;
  if (p.rot !== undefined) node.rotation = num(p.rot, 'rot');
  if (p.name !== undefined) node.name = String(p.name);

  // Geometry. Numeric w/h resize; keywords are returned as deferred sizing.
  /** @type {{h?: string, v?: string, abs?: boolean}} */
  const deferred = {};
  const sizeH = p.sizeH !== undefined ? p.sizeH : typeof p.w === 'string' ? p.w : undefined;
  const sizeV = p.sizeV !== undefined ? p.sizeV : typeof p.h === 'string' ? p.h : undefined;
  if (sizeH !== undefined) deferred.h = pick(SIZING_IN, sizeH, 'w');
  if (sizeV !== undefined) deferred.v = pick(SIZING_IN, sizeV, 'h');
  const hasW = typeof p.w === 'number';
  const hasH = typeof p.h === 'number';
  if (hasW || hasH) {
    const w = hasW ? p.w : node.width;
    const h = hasH ? p.h : node.height;
    if (isText) node.textAutoResize = hasW && hasH ? 'NONE' : hasW ? 'HEIGHT' : 'WIDTH_AND_HEIGHT';
    if (node.type === 'LINE') node.resize(Math.max(0.01, w), 0);
    else node.resize(Math.max(0.01, w), Math.max(0.01, h));
  }
  if (p.abs) deferred.abs = true;

  if (p.x !== undefined || p.y !== undefined) {
    const parent = node.parent;
    if (parent && isAL(parent) && node.layoutPositioning !== 'ABSOLUTE' && !p.abs) {
      warn.push('x/y ignored: parent is auto-layout (use abs:true to position freely)');
    } else {
      if (p.x !== undefined) node.x = num(p.x, 'x');
      if (p.y !== undefined) node.y = num(p.y, 'y');
    }
  }
  return deferred;
}

/** Apply parent-dependent sizing after the node is attached. @param {any} node @param {{h?: string, v?: string, abs?: boolean}} d */
function applySizing(node, d) {
  try {
    if (d.abs) node.layoutPositioning = 'ABSOLUTE';
    if (node.type === 'TEXT' && (d.h === 'FILL' || d.v === 'FILL' || d.h === 'FIXED')) {
      if (node.textAutoResize === 'WIDTH_AND_HEIGHT') node.textAutoResize = 'HEIGHT';
    }
    if (d.h) node.layoutSizingHorizontal = d.h;
    if (d.v) node.layoutSizingVertical = d.v;
  } catch (e) {
    const msg = /** @type {any} */ (e).message || String(e);
    fail('SIZING', `could not apply fill/hug sizing: ${msg}. "fill" needs an auto-layout parent; "hug" needs an auto-layout frame or text.`);
  }
}

// ---------------------------------------------------------------- build

/** @param {any} ref */
async function findComponent(ref) {
  const s = String(ref);
  if (s.startsWith('key:')) return F.importComponentByKeyAsync(s.slice(4));
  if (/^\d+:\d+$/.test(s)) {
    const n = await nodeById(s);
    return n.type === 'COMPONENT_SET' ? n.defaultVariant : n;
  }
  if (!CACHE.components) {
    let list = F.currentPage.findAllWithCriteria({ types: ['COMPONENT', 'COMPONENT_SET'] });
    if (!list.some((/** @type {any} */ c) => c.name === s)) {
      await F.loadAllPagesAsync();
      list = F.root.findAllWithCriteria({ types: ['COMPONENT', 'COMPONENT_SET'] });
    }
    CACHE.components = list;
  }
  const hit = CACHE.components.find((/** @type {any} */ c) => c.name === s);
  if (!hit) fail('REF_NOT_FOUND', `no component named "${s}"`, { near: near(CACHE.components, s) });
  return hit.type === 'COMPONENT_SET' ? hit.defaultVariant : hit;
}

/** @param {any} inst @param {Record<string, any>} props */
function setInstanceProps(inst, props) {
  const have = Object.keys(inst.componentProperties);
  /** @type {Record<string, any>} */
  const map = {};
  for (const [k, v] of Object.entries(props)) {
    const key = have.find((h) => h === k) || have.find((h) => h.split('#')[0] === k);
    if (!key) fail('BAD_PROP', `component has no property "${k}"`, { have: have.map((h) => h.split('#')[0]) });
    map[key] = v;
  }
  inst.setProperties(map);
}

/**
 * Build a node tree from a spec.
 * @param {any} spec @param {any} parent @param {string} path
 * @param {{top: any[], count: number, ids: Record<string,string>, warn: string[]}} st
 * @param {boolean} isTop
 */
async function make(spec, parent, path, st, isTop) {
  if (!spec || typeof spec !== 'object') fail('BAD_SPEC', `${path}: expected an object`);
  const { t, c, as, of, props, svg, ...p } = spec;
  /** @type {any} */
  let node;
  switch (t) {
    case 'frame': node = F.createFrame(); break;
    case 'component': node = F.createComponent(); break;
    case 'rect': node = F.createRectangle(); break;
    case 'ellipse': node = F.createEllipse(); break;
    case 'line': node = F.createLine(); break;
    case 'text': node = F.createText(); break;
    case 'svg':
      if (typeof svg !== 'string') fail('BAD_SPEC', `${path}: t:"svg" needs an svg string`);
      node = F.createNodeFromSvg(svg);
      break;
    case 'instance': {
      if (of === undefined) fail('BAD_SPEC', `${path}: t:"instance" needs of:"<component name | id | key:...>"`);
      node = (await findComponent(of)).createInstance();
      break;
    }
    default:
      fail('BAD_SPEC', `${path}: unknown type "${t}" (use frame|component|rect|ellipse|line|text|svg|instance)`);
  }
  if (isTop) st.top.push(node);
  st.count++;

  // Deterministic defaults: do not depend on what the API gives new nodes.
  if (t === 'frame' || t === 'component' || t === 'rect' || t === 'ellipse') node.fills = [];
  if (t === 'text') node.fills = [solid('#000000')];

  try {
    parent.appendChild(node);
    const deferred = await applyProps(node, p, st.warn);
    if (props) setInstanceProps(node, props);
    // Auto-layout containers hug along any axis the spec did not size explicitly.
    if (isAL(node)) {
      if (deferred.h === undefined && typeof p.w !== 'number') deferred.h = 'HUG';
      if (deferred.v === undefined && typeof p.h !== 'number') deferred.v = 'HUG';
    }
    applySizing(node, deferred);
    if (as) st.ids[as] = node.id;
    if (c !== undefined) {
      if (!Array.isArray(c)) fail('BAD_SPEC', `${path}.c must be an array`);
      if (!('appendChild' in node) || node.type === 'INSTANCE') fail('BAD_SPEC', `${path}: ${t} cannot have children`);
      for (let i = 0; i < c.length; i++) await make(c[i], node, `${path}.c[${i}]`, st, false);
    }
  } catch (e) {
    const err = /** @type {any} */ (e);
    if (err && typeof err === 'object' && !err.path) err.path = path;
    throw err;
  }
  return node;
}

/** @param {any} a */
async function opBuild(a) {
  // Shorthand: a lone node spec at the top level (op/parent/at/select belong to the job, not the node).
  const { op: _op, parent: _parent, at: _at, select: _select, ...single } = a;
  const nodes = Array.isArray(a.nodes) ? a.nodes : a.t ? [single] : null;
  if (!nodes || !nodes.length) fail('BAD_SPEC', 'build needs {nodes:[...]} or a single node object with "t"');
  const parent = a.parent ? await nodeById(a.parent) : F.currentPage;
  if (!('appendChild' in parent) || parent.type === 'INSTANCE') fail('BAD_PARENT', `cannot add children to ${parent.type}`);
  const st = { top: /** @type {any[]} */ ([]), count: 0, ids: /** @type {Record<string,string>} */ ({}), warn: /** @type {string[]} */ ([]) };
  try {
    for (let i = 0; i < nodes.length; i++) await make(nodes[i], parent, `nodes[${i}]`, st, true);
  } catch (e) {
    for (const n of st.top) {
      try { n.remove(); } catch (_) { /* already gone */ }
    }
    throw e;
  }
  // Place top-level nodes that did not ask for a position: near the viewport centre (or `at`).
  if (!isAL(parent)) {
    const free = st.top.filter((n, i) => nodes[i].x === undefined && nodes[i].y === undefined);
    if (free.length) {
      const gap = 40;
      const total = free.reduce((s, n) => s + n.width, 0) + gap * (free.length - 1);
      const c = parent.type === 'PAGE' ? F.viewport.center : { x: 0, y: 0 };
      let x = a.at ? a.at[0] : parent.type === 'PAGE' ? c.x - total / 2 : 0;
      const y0 = a.at ? a.at[1] : null;
      for (const n of free) {
        n.x = x;
        n.y = y0 !== null ? y0 : parent.type === 'PAGE' ? c.y - n.height / 2 : 0;
        x += n.width + gap;
      }
    }
  }
  for (const n of st.top) n.setPluginData(TAG, String(Date.now())); // `find --tagged` lists what Flue built
  if (a.select) F.currentPage.selection = st.top;
  F.commitUndo();
  return {
    created: st.count,
    roots: st.top.map((n) => [n.id, n.name, r2(n.width), r2(n.height)]),
    ...(Object.keys(st.ids).length ? { ids: st.ids } : {}),
    ...(st.warn.length ? { warn: st.warn } : {}),
  };
}

// ---------------------------------------------------------------- read ops

async function opCtx() {
  const pages = F.root.children.map((/** @type {any} */ p) => p.name);
  const sel = F.currentPage.selection.slice(0, 10).map((/** @type {any} */ n) => [n.id, n.type, n.name, r2(n.width), r2(n.height)]);
  return {
    v: VERSION,
    editor: F.editorType,
    file: F.root.name,
    page: [F.currentPage.id, F.currentPage.name],
    pages: pages.slice(0, 30),
    sel,
    ...(F.currentPage.selection.length > 10 ? { selMore: F.currentPage.selection.length - 10 } : {}),
    view: { c: [r2(F.viewport.center.x), r2(F.viewport.center.y)], z: r2(F.viewport.zoom) },
    caps: { eval: EVAL_OK, api: F.apiVersion },
    ro: READ_ONLY,
  };
}

/** @param {any} a */
async function opTree(a) {
  const depth = a.depth === undefined ? 2 : num(a.depth, 'depth');
  const max = a.max === undefined ? 150 : num(a.max, 'max');
  const extra = resolveFields(a.fields === undefined ? [] : a.fields).filter((f) => !['x', 'y', 'w', 'h', 'ch'].includes(f));
  const cols = ['d', 'id', 'type', 'name', 'x', 'y', 'w', 'h', 'ch', ...extra];
  let roots;
  if (a.id) {
    roots = [await nodeById(a.id)];
  } else if (a.page) {
    const pg = F.root.children.find((/** @type {any} */ p) => p.name === a.page || p.id === a.page);
    if (!pg) fail('PAGE_NOT_FOUND', `no page "${a.page}"`, { pages: F.root.children.map((/** @type {any} */ p) => p.name) });
    await pg.loadAsync();
    roots = pg.children;
  } else if (F.currentPage.selection.length) {
    roots = F.currentPage.selection;
  } else {
    roots = F.currentPage.children;
  }
  /** @type {any[][]} */
  const rows = [];
  let trunc = false;
  /** @param {any} n @param {number} d */
  async function visit(n, d) {
    if (rows.length >= max) {
      trunc = true;
      return;
    }
    const row = [d, n.id, n.type, n.name];
    for (const f of cols.slice(4)) {
      const v = await FIELDS[f](n);
      row.push(v === undefined ? null : v);
    }
    rows.push(row);
    if (d < depth && 'children' in n) {
      for (const ch of n.children) {
        await visit(ch, d + 1);
        if (trunc) return;
      }
    }
  }
  for (const r of roots) {
    await visit(r, 0);
    if (trunc) break;
  }
  return { cols, rows, ...(trunc ? { trunc: true, hint: 'raise max, lower depth, or pass an id to drill down' } : {}) };
}

/** @param {any} a */
async function opGet(a) {
  const fields = resolveFields(a.fields);
  const ids = a.ids || (a.id ? [a.id] : null);
  if (!ids) fail('BAD_ID', 'get needs id or ids');
  const out = [];
  for (const id of ids) out.push(await ser(await nodeById(id), fields));
  return a.ids ? { nodes: out } : { node: out[0] };
}

/** @param {any} a */
async function opFind(a) {
  const scope = a.in ? await nodeById(a.in) : F.currentPage;
  const types = a.type ? [].concat(a.type).map((/** @type {any} */ t) => String(t).toUpperCase()) : null;
  const sub = a.name ? String(a.name).toLowerCase() : null;
  const re = a.re ? new RegExp(a.re, 'i') : null;
  const txt = a.text ? String(a.text).toLowerCase() : null;
  const limit = a.limit === undefined ? 30 : num(a.limit, 'limit');
  const extra = resolveFields(a.fields === undefined ? [] : a.fields).filter((f) => !['x', 'y', 'w', 'h'].includes(f));
  const cols = ['id', 'type', 'name', 'x', 'y', 'w', 'h', ...extra];
  /** @type {any[][]} */
  const rows = [];
  let more = false;
  /** @param {any} n */
  async function walk(n) {
    for (const ch of n.children || []) {
      const ok =
        (!types || types.includes(ch.type)) &&
        (!sub || ch.name.toLowerCase().includes(sub)) &&
        (!re || re.test(ch.name)) &&
        (!a.tagged || (typeof ch.getPluginData === 'function' && ch.getPluginData(TAG))) &&
        (!txt || (ch.type === 'TEXT' && ch.characters.toLowerCase().includes(txt)));
      if (ok) {
        if (rows.length >= limit) {
          more = true;
          return;
        }
        const row = [ch.id, ch.type, ch.name];
        for (const f of cols.slice(3)) {
          const v = await FIELDS[f](ch);
          row.push(v === undefined ? null : v);
        }
        rows.push(row);
      }
      if ('children' in ch) {
        await walk(ch);
        if (more) return;
      }
    }
  }
  await walk(scope);
  return { cols, rows, ...(more ? { more: true } : {}) };
}

/** @param {any} a */
async function opShot(a) {
  /** @type {any} */
  const node = a.id ? await nodeById(a.id) : F.currentPage.selection[0];
  if (!node) fail('NO_TARGET', 'pass an id or select a node first');
  if (!('exportAsync' in node)) fail('NO_TARGET', `${node.type} cannot be exported`);
  const w = node.width;
  const h = node.height;
  const maxpx = a.maxpx === undefined ? 1024 : num(a.maxpx, 'maxpx');
  let scale = a.scale === undefined ? 1 : num(a.scale, 'scale');
  if (Math.max(w, h) * scale > maxpx) scale = maxpx / Math.max(w, h);
  scale = Math.min(4, Math.max(0.01, scale));
  const fmt = String(a.fmt || 'PNG').toUpperCase() === 'JPG' ? 'JPG' : 'PNG';
  const bytes = await node.exportAsync({ format: fmt, constraint: { type: 'SCALE', value: scale } });
  return {
    id: node.id,
    w: Math.round(w * scale),
    h: Math.round(h * scale),
    scale: r2(scale),
    bin: { mime: fmt === 'JPG' ? 'image/jpeg' : 'image/png', b64: F.base64Encode(bytes) },
  };
}

/**
 * Contact sheet, step 1 (main thread): export each node at a common width and hand the PNG bytes to the
 * UI, which has a canvas and stitches them into ONE labelled image. Nothing is created in the file.
 * @param {any} a
 */
async function opSheet(a) {
  const ids = [].concat(a.ids || []);
  if (!ids.length) fail('BAD_ARGS', 'sheet needs node ids');
  /** @type {any[]} */
  let nodes = [];
  if (a.children) nodes = ((await nodeById(ids[0])).children || []).slice();
  else for (const id of ids) nodes.push(await nodeById(id));
  nodes = nodes.filter((n) => 'exportAsync' in n);
  if (!nodes.length) fail('NO_TARGET', 'nothing exportable to show');
  const MAX = 24;
  const more = nodes.length > MAX ? nodes.length - MAX : 0;
  nodes = nodes.slice(0, MAX);
  const cell = Math.min(1000, Math.max(120, a.cell === undefined ? 360 : num(a.cell, 'cell')));
  const parts = [];
  for (const n of nodes) {
    const bytes = await n.exportAsync({ format: 'PNG', constraint: { type: 'WIDTH', value: Math.round(cell) } });
    parts.push({ id: n.id, name: n.name, b64: F.base64Encode(bytes) });
  }
  return {
    sheet: { parts, cols: a.cols === undefined ? 0 : num(a.cols, 'cols'), cell, maxpx: a.maxpx === undefined ? 1600 : num(a.maxpx, 'maxpx'), labels: a.labels !== false },
    n: parts.length,
    ...(more ? { skipped: more } : {}),
  };
}

// ---------------------------------------------------------------- write ops

/** Put image bytes into the file: an image fill on `fill`, or a new rectangle. @param {any} a */
async function opImage(a) {
  if (!a.b64) fail('BAD_ARGS', 'image needs bytes');
  const image = F.createImage(F.base64Decode(a.b64));
  const size = await image.getSizeAsync();
  const mode = ['FILL', 'FIT', 'CROP', 'TILE'].includes(a.mode) ? a.mode : 'FILL';
  const paint = { type: 'IMAGE', imageHash: image.hash, scaleMode: mode };
  if (a.fill) {
    const node = await nodeById(a.fill);
    if (!('fills' in node)) fail('BAD_TARGET', `${node.type} has no fills`);
    node.fills = [paint];
    F.commitUndo();
    return { id: node.id, img: [size.width, size.height] };
  }
  const parent = a.parent ? await nodeById(a.parent) : F.currentPage;
  if (!('appendChild' in parent) || parent.type === 'INSTANCE') fail('BAD_PARENT', `cannot add children to ${parent.type}`);
  const w = a.w ? num(a.w, 'w') : Math.min(size.width, 800);
  const h = (w * size.height) / size.width;
  const rect = F.createRectangle();
  rect.name = a.name || 'Image';
  rect.resize(w, h);
  rect.fills = [paint];
  parent.appendChild(rect);
  const c = parent.type === 'PAGE' ? F.viewport.center : { x: 0, y: 0 };
  rect.x = a.at ? a.at[0] : c.x - w / 2;
  rect.y = a.at ? a.at[1] : c.y - h / 2;
  rect.setPluginData(TAG, String(Date.now()));
  F.commitUndo();
  return { id: rect.id, name: rect.name, w: r2(w), h: r2(h), img: [size.width, size.height] };
}

/** Save a named version in the file's history. @param {any} a */
async function opCheckpoint(a) {
  if (!a.title) fail('BAD_ARGS', 'checkpoint needs a title');
  const res = await F.saveVersionHistoryAsync(String(a.title), a.note ? String(a.note) : undefined);
  return { saved: true, title: String(a.title), ...(res && res.id ? { id: res.id } : {}) };
}

/** @param {any} a */
async function opSet(a) {
  const ids = a.ids || (a.id ? [a.id] : null);
  if (!ids) fail('BAD_ID', 'set needs id or ids');
  const props = a.props;
  if (!props || typeof props !== 'object') fail('BAD_SPEC', 'set needs props:{...}');
  const warn = /** @type {string[]} */ ([]);
  const nodes = [];
  for (const id of ids) nodes.push(await nodeById(id));
  for (const n of nodes) {
    const d = await applyProps(n, props, warn);
    applySizing(n, d);
  }
  F.commitUndo();
  return { set: nodes.length, ...(warn.length ? { warn: [...new Set(warn)] } : {}) };
}

/** Turn arbitrary script results into JSON-safe data; Figma nodes become {id,type,name}. @param {any} v */
function clean(v) {
  const seen = new WeakSet();
  const text = JSON.stringify(v, (k, val) => {
    if (val === F.mixed) return 'mixed';
    if (typeof val === 'bigint') return String(val);
    if (typeof val === 'function' || typeof val === 'symbol') return undefined;
    if (val && typeof val === 'object') {
      if (typeof val.id === 'string' && typeof val.type === 'string' && 'parent' in val) return { id: val.id, type: val.type, name: val.name };
      if (seen.has(val)) return '[circular]';
      seen.add(val);
    }
    return val;
  });
  return text === undefined ? null : JSON.parse(text);
}

/** @param {any} x */
const fmtLog = (x) => (typeof x === 'string' ? x : (() => { try { return JSON.stringify(clean(x)); } catch (_) { return String(x); } })());

/** @param {any} a */
async function opEval(a) {
  if (!EVAL_OK) {
    fail('EVAL_UNSUPPORTED', 'this Figma plugin sandbox does not allow running code strings; use the fixed ops (tree, get, find, set, build, shot)');
  }
  if (typeof a.code !== 'string' || !a.code.trim()) fail('BAD_SPEC', 'eval needs code');
  /** @type {string[]} */
  const logs = [];
  const con = {
    log: (/** @type {any[]} */ ...x) => logs.push(x.map(fmtLog).join(' ')),
    warn: (/** @type {any[]} */ ...x) => logs.push('warn: ' + x.map(fmtLog).join(' ')),
    error: (/** @type {any[]} */ ...x) => logs.push('error: ' + x.map(fmtLog).join(' ')),
  };
  const fn = new AsyncFunction('figma', 'H', 'S', 'console', a.code);
  const result = await fn(F, H, S, con);
  const out = /** @type {Record<string, any>} */ ({ result: clean(result) });
  if (logs.length) out.logs = logs.slice(0, 50);
  F.commitUndo();
  return out;
}

/** Helpers exposed to eval scripts as `H`. */
const H = {
  node: nodeById,
  hex: toHex,
  solid,
  ser,
  fields: FIELDS,
  applyProps,
  applySizing,
  build: opBuild,
  tree: opTree,
  find: opFind,
};

// ---------------------------------------------------------------- dispatch

/** @type {Record<string, (a: any) => Promise<any>>} */
const OPS = { ctx: opCtx, tree: opTree, get: opGet, find: opFind, set: opSet, build: opBuild, shot: opShot, sheet: opSheet, image: opImage, checkpoint: opCheckpoint, eval: opEval };
const MUTATING = new Set(['set', 'build', 'image', 'checkpoint', 'eval']);

/** @param {any} e */
function errOut(e) {
  if (e instanceof FlueError) {
    return { ok: false, error: e.message, code: e.code, ...(e.extra || {}), ...(/** @type {any} */ (e).path ? { at: /** @type {any} */ (e).path } : {}) };
  }
  const err = /** @type {any} */ (e);
  const stack = String((err && err.stack) || '').split('\n').slice(0, 4).join('\n');
  return { ok: false, error: String((err && err.message) || err), code: 'SCRIPT_ERROR', stack };
}

/** Run one job. Never throws. @param {any} job */
async function runJob(job) {
  CACHE = {};
  try {
    const op = OPS[job.op];
    if (!op) fail('UNKNOWN_OP', `unknown op "${job.op}"`, { ops: Object.keys(OPS) });
    if (READ_ONLY && MUTATING.has(job.op)) {
      fail('READ_ONLY', 'Flue Bridge is in read-only mode. Ask the user to untick "Read-only" in the plugin window.');
    }
    const out = await op(job);
    return { ok: true, ...out };
  } catch (e) {
    return errOut(e);
  }
}

/** Can this sandbox build functions from strings? */
function detectEval() {
  try {
    return typeof new AsyncFunction('return 1') === 'function';
  } catch (e) {
    return false;
  }
}

// ---------------------------------------------------------------- plugin wiring

async function main() {
  EVAL_OK = detectEval();
  READ_ONLY = !!(await F.clientStorage.getAsync('flue.ro'));
  const token = (await F.clientStorage.getAsync('flue.token')) || '';
  F.showUI(__html__, { width: 168, height: 38, title: 'Flue · keep open', themeColors: true });
  let chain = Promise.resolve();
  F.ui.onmessage = (/** @type {any} */ msg) => {
    if (msg.type === 'job') {
      // msg.jid is the transport's job id; msg.job is {op, ...args} (its own "id" is a node id).
      chain = chain.then(async () => {
        const res = await runJob(msg.job);
        F.ui.postMessage({ type: 'result', jid: msg.jid, res });
      });
    } else if (msg.type === 'resize') {
      F.ui.resize(Math.max(70, Math.min(400, Math.round(msg.w) || 168)), Math.max(30, Math.min(400, Math.round(msg.h) || 38)));
    } else if (msg.type === 'notify') {
      F.notify(String(msg.text || ''), { timeout: 8000, error: !!msg.error });
    } else if (msg.type === 'save') {
      return F.clientStorage.setAsync('flue.token', msg.token || '');
    } else if (msg.type === 'ro') {
      READ_ONLY = !!msg.value;
      return F.clientStorage.setAsync('flue.ro', READ_ONLY);
    }
  };
  // Tell the UI what the user has selected (cheap live context for the agent's status).
  const pushSel = () => {
    const sel = F.currentPage.selection;
    F.ui.postMessage({ type: 'sel', sel: sel.slice(0, 4).map((/** @type {any} */ n) => [n.id, String(n.name).slice(0, 24)]), n: sel.length, page: F.currentPage.name });
  };
  F.on('selectionchange', pushSel);
  F.on('currentpagechange', pushSel);
  F.ui.postMessage({ type: 'init', token, ro: READ_ONLY, eval: EVAL_OK, file: F.root.name, editor: F.editorType, v: VERSION });
}

if (typeof module !== 'undefined' && module.exports) {
  module.exports = {
    setFigma, runJob, detectEval, parseColor, toHex, solid, FlueError,
    _state: { get readOnly() { return READ_ONLY; }, set readOnly(v) { READ_ONLY = v; }, get evalOk() { return EVAL_OK; }, set evalOk(v) { EVAL_OK = v; }, S },
  };
}
if (typeof figma !== 'undefined' && typeof __html__ !== 'undefined') {
  main().catch((e) => {
    figma.notify('Flue Bridge failed to start: ' + (e && e.message ? e.message : e), { error: true });
  });
}
