// Odoo Process X-Ray, the 15-second showreel.
//
// Every frame is a pure function of time: drawScene(ctx, t) paints the scene at
// t seconds, so the same t always gives the same picture. The story follows the
// tool itself, with the real demo data (data.js):
//
//   01 chatter      2,984 tracked changes from Odoo's chatter, one card each
//   02 x-ray        the scan turns every card into an event
//   03 event log    the events regroup into one timeline per order
//   04 process map  the timelines pour into the map: one dot per event
//   05 findings     where orders get stuck, where it concentrates, the fix
//   06 report       one command, one HTML report
//   07 title
(() => {
'use strict';

const W = 1920, H = 1080, DURATION = 15;
const D = window.XRAY_DATA;

// ------------------------------------------------------------------ math

const clamp = (x, a = 0, b = 1) => (x < a ? a : x > b ? b : x);
const lerp = (a, b, t) => a + (b - a) * t;
const prog = (t, a, b) => clamp((t - a) / (b - a));
const smooth = (x) => x * x * (3 - 2 * x);
const E = {
  lin: (x) => x,
  outQuad: (x) => 1 - (1 - x) * (1 - x),
  inCubic: (x) => x * x * x,
  outCubic: (x) => 1 - Math.pow(1 - x, 3),
  inOutCubic: (x) => (x < 0.5 ? 4 * x * x * x : 1 - Math.pow(-2 * x + 2, 3) / 2),
  inQuart: (x) => x ** 4,
  outExpo: (x) => (x >= 1 ? 1 : 1 - Math.pow(2, -10 * x)),
  inOutSine: (x) => -(Math.cos(Math.PI * x) - 1) / 2,
};
const P = (t, a, b, e = E.lin) => e(prog(t, a, b));
// Motion blur averages sub-frames around each frame. Numbers, typed text and
// scrambled glyphs change in steps, so they follow the frame's own time (TF)
// and stay crisp instead of showing two values at once.
let TF = 0;
// Damped spring from 0 to 1: s seconds after release, overshoots once and settles.
function spring(s, w = 16, z = 0.5) {
  if (s <= 0) return 0;
  const wd = w * Math.sqrt(1 - z * z);
  return 1 - Math.exp(-z * w * s) * (Math.cos(wd * s) + (z * w / wd) * Math.sin(wd * s));
}
function hash(i) {
  let x = Math.imul((i | 0) ^ 0x9e3779b9, 0x85ebca6b);
  x = Math.imul(x ^ (x >>> 13), 0xc2b2ae35);
  x ^= x >>> 16;
  return (x >>> 0) / 4294967296;
}
const noise = (x, seed = 0) => {
  const i = Math.floor(x);
  return lerp(hash(i + seed * 7919), hash(i + 1 + seed * 7919), smooth(x - i));
};
const fmt = (n) => Math.round(n).toLocaleString('en-US');

// ------------------------------------------------------------------ look

const COL = {
  ink: '#eef4ff', muted: '#91a2c4', dim: '#5a6b8f', faint: '#26324f',
  cyan: '#5ce1ff', ice: '#c9f6ff', blue: '#3d8bff', violet: '#8b7cff',
  hot: '#ff4d6d', hot2: '#ff9068', green: '#3ee6a8', panel: '#0c1426',
};
// Per activity, in the order of D.activities: the normal flow in cool blues,
// detours and corrections in warm colours.
const ACT_COL = ['#a6ecff', '#74dbff', '#4cc3ff', '#ff5c7a', '#ff9a4d', '#3aa6ff', '#6a8dff',
  '#ff9a4d', '#ff6fb1', '#9b85ff', '#8391ad'];
const PEOPLE_COL = ['#5b7cfa', '#e0679a', '#38b2ac', '#d69e2e', '#9f7aea', '#48bb78', '#ed8936', '#4299e1'];

const rgbCache = new Map();
function rgb(hex) {
  let v = rgbCache.get(hex);
  if (!v) {
    const n = parseInt(hex.slice(1), 16);
    v = [(n >> 16) & 255, (n >> 8) & 255, n & 255];
    rgbCache.set(hex, v);
  }
  return v;
}
const rgba = (hex, a) => { const [r, g, b] = rgb(hex); return `rgba(${r},${g},${b},${a})`; };
function mix(h1, h2, t, a = 1) {
  const x = rgb(h1), y = rgb(h2);
  return `rgba(${Math.round(lerp(x[0], y[0], t))},${Math.round(lerp(x[1], y[1], t))},${Math.round(lerp(x[2], y[2], t))},${a})`;
}

const SANS = '"Inter Tight"', SERIF = '"Instrument Serif"', MONO = '"JetBrains Mono"';
const font = (weight, size, family = SANS, italic = false) => `${italic ? 'italic ' : ''}${weight} ${size}px ${family}`;

function canvas(w, h) {
  const c = document.createElement('canvas');
  c.width = w;
  c.height = h;
  return c;
}
function glowSprite(hex, size = 64, core = 0.16) {
  const c = canvas(size, size), g = c.getContext('2d'), r = size / 2;
  const grad = g.createRadialGradient(r, r, 0, r, r, r);
  grad.addColorStop(0, 'rgba(255,255,255,1)');
  grad.addColorStop(core * 0.6, rgba(hex, 1));
  grad.addColorStop(core * 1.6, rgba(hex, 0.45));
  grad.addColorStop(0.55, rgba(hex, 0.08));
  grad.addColorStop(1, rgba(hex, 0));
  g.fillStyle = grad;
  g.fillRect(0, 0, size, size);
  return c;
}
const GLOW = ACT_COL.map((c) => glowSprite(c));
const GLOW_HOT = glowSprite(COL.hot);
const GLOW_ICE = glowSprite(COL.ice);
const GLOW_GREEN = glowSprite(COL.green);

// ------------------------------------------------------------------ timeline (seconds)

const T = {
  h1: [0.12, 1.9], focus: [0.9, 1.95], pull: [1.82, 2.95],
  scan: [2.7, 3.72], h2: [2.92, 3.58], reveal: [2.24, 2.92],
  chart: 3.76, chartLabels: [4.2, 4.98], h3: [4.16, 7.18],
  swarm: 4.96,
  dim: 7.3, h4: [7.5, 10.72], cards: [7.86, 8.88, 9.9, 10.94],
  report: 10.96, h5: [11.3, 12.86],
  title: 12.98, end: 15.0,
};
const SCENES = [[0, '01', 'CHATTER'], [2.7, '02', 'X-RAY'], [3.76, '03', 'EVENT LOG'], [4.96, '04', 'PROCESS MAP'],
  [7.3, '05', 'FINDINGS'], [10.96, '06', 'REPORT'], [12.98, '07', 'ODOO PROCESS X-RAY']];

// ------------------------------------------------------------------ data

const EVENTS = D.events.map(([order, act, rel, first, person, doc, when, extra], i) =>
  ({ i, order, act, rel, first, person, doc, when, extra }));
const ORDERS = D.stats.orders;
const DMAX = Math.max(...EVENTS.map((e) => e.rel));
const ACT = Object.fromEntries(D.activities.map((a, i) => [a, i]));

// 02: the chatter wall, one card per tracked change, in time order.
const COLS = 33, CW = 520, CH = 92, PX = 548, PY = 112;
const ROWS = Math.ceil(EVENTS.length / COLS);
const WALL_W = COLS * PX - (PX - CW), WALL_H = ROWS * PY - (PY - CH);
for (const e of EVENTS) {
  e.u = (e.i % COLS) * PX;
  e.v = Math.floor(e.i / COLS) * PY;
}
const FOCUS = (() => {
  const target = 40 * COLS + 19;
  let best = null;
  for (const e of EVENTS) {
    if (e.act === ACT['Order confirmed'] && e.person >= 0 && (!best || Math.abs(e.i - target) < Math.abs(best.i - target))) best = e;
  }
  return best;
})();

const TRACKING = [
  ['', 'Quotation created', ''], ['Status', 'Quotation', 'Quotation Sent'], ['Status', 'Quotation Sent', 'Sales Order'],
  ['Total', '', ''], ['Scheduled Date', '', ''], ['Status', 'Ready', 'Done'], ['Status', 'Draft', 'Posted'],
  ['Status', 'Posted', 'Draft'], ['Status', 'Draft', 'Posted'], ['Payment Status', 'Not Paid', 'Paid'],
  ['Status', 'Quotation', 'Cancelled'],
];
function tracking(e) {
  const [field, before, after] = TRACKING[e.act];
  if (e.extra) {
    const [a, b] = e.extra.split('|');
    return [field, a, b];
  }
  return [field, before, after];
}
const initials = (name) => name.split(' ').map((s) => s[0]).join('').slice(0, 2);
const TINT = ACT_COL.map((c) => mix('#131b31', c, 0.1, 0.95));

// 04: the process map, laid out like the report's.
const MAIN_X = 1100, SIDE_X = 1640;
const NODES = {
  'Quotation created': { x: MAIN_X, y: 150, w: 372 },
  'Quotation sent': { x: MAIN_X, y: 292, w: 372 },
  'Order confirmed': { x: MAIN_X, y: 434, w: 372 },
  'Goods shipped': { x: MAIN_X, y: 636, w: 372 },
  'Invoice posted': { x: MAIN_X, y: 778, w: 372 },
  'Payment received': { x: MAIN_X, y: 920, w: 372 },
  'Order cancelled': { x: SIDE_X, y: 234, w: 356 },
  'Order changed after confirmation': { x: SIDE_X, y: 420, w: 356, label: 'Changed after confirmation' },
  'Delivery rescheduled': { x: SIDE_X, y: 572, w: 356 },
  'Credit note posted': { x: SIDE_X, y: 848, w: 356 },
};
const NODE_H = 80;
for (const [name, n] of Object.entries(NODES)) {
  n.name = name;
  n.label = n.label || name;
  n.act = ACT[name];
  n.count = D.nodes[name] || 0;
  n.main = n.x === MAIN_X;
}
const MAP_PIVOT = { x: 1310, y: 537 };

// ------------------------------------------------------------------ helpers: text

function text(ctx, str, x, y, f, color, align = 'left', spacing = 0) {
  ctx.font = f;
  ctx.fillStyle = color;
  ctx.textAlign = align;
  ctx.letterSpacing = spacing ? `${spacing}px` : '0px';
  ctx.fillText(str, x, y);
  if (spacing) ctx.letterSpacing = '0px';
}
const widths = new Map();
function measure(ctx, str, f, spacing = 0) {
  const key = `${f}|${spacing}|${str}`;
  let w = widths.get(key);
  if (w === undefined) {
    ctx.font = f;
    ctx.letterSpacing = spacing ? `${spacing}px` : '0px';
    w = ctx.measureText(str).width;
    if (spacing) ctx.letterSpacing = '0px';
    widths.set(key, w);
  }
  return w;
}
const GLYPHS = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789#%&*+<>/=';
function scramble(str, p, seed) {
  let out = '';
  for (let i = 0; i < str.length; i++) {
    const r = (i / str.length) * 0.7;
    if (str[i] === ' ' || p >= r + 0.3) out += str[i];
    else if (p >= r) out += GLYPHS[Math.floor(hash(seed + i * 31 + Math.floor(p * 30)) * GLYPHS.length)];
    else out += ' ';
  }
  return out;
}

// Big headlines: words rise out of a mask, one after the other, and leave upwards.
// A word starting with * is set in the serif italic, in the accent colour.
const HEADLINES = [
  { lines: [['Every', 'Odoo', 'order'], ['leaves', 'a', '*trail.']], x: 112, y: 486, size: 118, t: T.h1, accent: COL.cyan },
  { lines: [['X-Ray', 'reads'], ['all', 'of', '*it.']], x: 112, y: 486, size: 118, t: T.h2, accent: COL.cyan },
  { lines: [['Rebuilds'], ['how', 'orders'], ['*really', 'flow.']], x: 112, y: 410, size: 104, t: T.h3, accent: COL.cyan },
  { lines: [['Finds', 'where'], ['they', 'get', 'stuck'], ['—', 'and', '*why.']], x: 112, y: 196, size: 74, t: T.h4, accent: COL.hot },
  { lines: [['One', 'command.'], ['One', '*report.']], x: 112, y: 420, size: 98, t: T.h5, accent: COL.cyan },
];

function drawHeadline(ctx, h, t) {
  const [tin, tout] = h.t;
  if (t < tin - 0.05 || t > tout + 0.8) return;
  const lh = h.size * 1.04;
  let k = 0;
  h.lines.forEach((words, li) => {
    const base = h.y + li * lh;
    ctx.save();
    ctx.beginPath();
    ctx.rect(h.x - 30, base - h.size * 1.12, W, h.size * 1.5);
    ctx.clip();
    let x = h.x;
    for (const raw of words) {
      const accent = raw.startsWith('*');
      const word = accent ? raw.slice(1) : raw;
      const size = accent ? h.size * 1.16 : h.size;
      const f = accent ? font(400, size, SERIF, true) : font(800, size);
      const w = measure(ctx, word, f);
      const a = tin + k * 0.055;
      const pin = E.outExpo(prog(t, a, a + 0.8));
      const b = tout + k * 0.03;
      const pout = E.inQuart(prog(t, b, b + 0.36));
      const y = base + (1 - pin) * h.size * 1.1 - pout * h.size * 1.6;
      ctx.globalAlpha = clamp(pin * 1.6) * (1 - pout);
      if (accent) {
        const g = ctx.createLinearGradient(x, y - size * 0.7, x + w, y);
        g.addColorStop(0, h.accent);
        g.addColorStop(1, mix(h.accent, '#ffffff', 0.55));
        ctx.shadowColor = rgba(h.accent, 0.55);
        ctx.shadowBlur = 36;
        text(ctx, word, x, y, f, g);
        ctx.shadowBlur = 0;
      } else {
        text(ctx, word, x, y, f, COL.ink);
      }
      x += w + h.size * (accent ? 0.2 : 0.24);
      k++;
    }
    ctx.restore();
  });
  ctx.globalAlpha = 1;
}

// ------------------------------------------------------------------ background

const BG = (() => {
  const c = canvas(W, H), g = c.getContext('2d');
  const grad = g.createRadialGradient(W * 0.62, H * 0.42, 40, W * 0.5, H * 0.5, W * 0.78);
  grad.addColorStop(0, '#0e172c');
  grad.addColorStop(0.5, '#080d1a');
  grad.addColorStop(1, '#03050b');
  g.fillStyle = grad;
  g.fillRect(0, 0, W, H);
  return c;
})();

function drawBackground(ctx, t, gridAlpha) {
  ctx.drawImage(BG, 0, 0);
  if (gridAlpha > 0) {
    ctx.lineWidth = 1;
    for (let pass = 0; pass < 2; pass++) {
      const step = pass ? 240 : 48;
      ctx.strokeStyle = rgba('#7ea6ff', (pass ? 0.075 : 0.035) * gridAlpha);
      ctx.beginPath();
      for (let x = 0; x < W; x += step) { ctx.moveTo(x + 0.5, 0); ctx.lineTo(x + 0.5, H); }
      for (let y = 12; y < H; y += step) { ctx.moveTo(0, y + 0.5); ctx.lineTo(W, y + 0.5); }
      ctx.stroke();
    }
  }
  // Dust drifting through the light.
  ctx.globalCompositeOperation = 'lighter';
  for (let i = 0; i < 70; i++) {
    const x = (hash(i) * W + t * (8 + hash(i + 5) * 22)) % W;
    const y = (hash(i + 9) * H - t * (4 + hash(i + 3) * 10) + H) % H;
    const tw = 0.35 + 0.65 * noise(t * 1.3 + i * 3.1, i);
    const s = 5 + hash(i + 11) * 9;
    ctx.globalAlpha = 0.16 * tw;
    ctx.drawImage(GLOW_ICE, x - s / 2, y - s / 2, s, s);
  }
  ctx.globalAlpha = 1;
  ctx.globalCompositeOperation = 'source-over';
}

// ------------------------------------------------------------------ 01-02: the chatter wall

const FOCAL = 1200;
const WALL_CX = WALL_W / 2, WALL_CY = WALL_H / 2;
const FAR = FOCAL / Math.min((W - 110) / WALL_W, (H - 110) / WALL_H);
const NEAR = 1060;

function wallCam(t) {
  const near = lerp(1300, NEAR, E.outCubic(prog(t, 0, 1.95)));
  const u = P(t, T.pull[0], T.pull[1], E.inOutCubic);
  let dist = Math.exp(lerp(Math.log(near), Math.log(FAR), u));
  if (t > T.pull[1]) dist *= 1 + 0.035 * (t - T.pull[1]);
  // Anchor the zoom on the focus card, then hand over to the wall's centre.
  const w = clamp((dist - near) / (FAR - near));
  const turn = P(t, T.pull[0] - 0.05, T.pull[1] - 0.18, E.inOutCubic);
  const drift = Math.min(t, T.pull[1]) * 34;
  return {
    tx: lerp(FOCUS.u + CW * 0.5 + drift * 0.35, WALL_CX, w),
    ty: lerp(FOCUS.v + CH * 0.5 - drift, WALL_CY, w),
    dist, pitch: lerp(0.8, 0, turn), yaw: lerp(0.3 - t * 0.025, 0, turn), roll: lerp(-0.1, 0, turn),
    ox: lerp(430, 0, w), oy: lerp(60, 0, w),
  };
}

function projector(c) {
  const cy = Math.cos(c.yaw), sy = Math.sin(c.yaw);
  const cp = Math.cos(-c.pitch), sp = Math.sin(-c.pitch);
  const cr = Math.cos(c.roll), sr = Math.sin(c.roll);
  return (u, v) => {
    const x = u - c.tx, y = v - c.ty;
    const x1 = x * cy, z1 = -x * sy;
    const y2 = y * cp - z1 * sp, z2 = y * sp + z1 * cp;
    const x3 = x1 * cr - y2 * sr, y3 = x1 * sr + y2 * cr;
    const z = c.dist + z2;
    const k = FOCAL / z;
    return [W / 2 + c.ox + x3 * k, H / 2 + c.oy + y3 * k, z];
  };
}

function beamX(t) {
  return lerp(-160, W + 160, P(t, T.scan[0], T.scan[1], E.inOutSine));
}
// 0 = still a card, 1 = fully turned into an event dot.
const scanState = (sx, t) => (t < T.scan[0] ? 0 : clamp((beamX(t) - sx) / 150));

function drawCard(ctx, e, lod, xr, focus) {
  const x = e.act;
  if (lod === 0) {
    ctx.fillStyle = mix('#1a2440', COL.cyan, xr * 0.5, 0.95);
    ctx.fillRect(0, 0, CW, CH);
    ctx.fillStyle = ACT_COL[x];
    ctx.fillRect(22, 22, 48, 48);
    return;
  }
  ctx.beginPath();
  ctx.roundRect(0, 0, CW, CH, 14);
  ctx.fillStyle = focus ? 'rgba(20,34,60,0.97)' : xr > 0 ? mix('#141d34', '#1b3a52', xr, 0.95) : TINT[x];
  ctx.fill();
  ctx.lineWidth = focus ? 3 : 1.5;
  ctx.strokeStyle = focus ? rgba(COL.cyan, 0.9) : mix('#8aa2e6', COL.cyan, xr, 0.16 + xr * 0.6);
  ctx.stroke();
  const person = e.person >= 0 ? D.people[e.person] : 'OdooBot';
  ctx.beginPath();
  ctx.arc(46, 46, 24, 0, Math.PI * 2);
  ctx.fillStyle = e.person >= 0 ? PEOPLE_COL[e.person % PEOPLE_COL.length] : '#7a86a3';
  ctx.fill();
  if (lod === 1) {
    ctx.fillStyle = 'rgba(210,225,255,0.45)';
    ctx.fillRect(86, 24, 150 + (e.i % 5) * 18, 16);
    ctx.fillStyle = 'rgba(150,170,210,0.3)';
    ctx.fillRect(86, 56, 110, 14);
    ctx.fillStyle = ACT_COL[x];
    ctx.fillRect(210, 54, 170 + (e.i % 3) * 30, 18);
    return;
  }
  text(ctx, initials(person), 46, 53, font(700, 18), '#ffffff', 'center');
  text(ctx, person, 86, 38, font(650, 21), COL.ink);
  const nw = measure(ctx, person, font(650, 21));
  text(ctx, e.when, 86 + nw + 12, 38, font(400, 17), COL.muted);
  text(ctx, e.doc, CW - 22, 38, font(500, 15, MONO), COL.dim, 'right');
  const [field, before, after] = tracking(e);
  const f = font(450, 19);
  if (!field) {
    text(ctx, before, 86, 70, font(500, 19), COL.muted);
    return;
  }
  let cx = 86;
  text(ctx, `${field}:`, cx, 70, f, COL.muted);
  cx += measure(ctx, `${field}:`, f) + 9;
  text(ctx, before, cx, 70, f, '#aab8d6');
  cx += measure(ctx, before, f) + 9;
  text(ctx, '→', cx, 70, font(600, 19), COL.cyan);
  cx += 28;
  text(ctx, after, cx, 70, font(700, 19), focus ? COL.ice : ACT_COL[x]);
}

const WALL_LAYER = canvas(W, H);
const WALL_SMALL = canvas(W / 4, H / 4);

function drawWall(ctx, t) {
  if (t > T.scan[1] + 0.2) return;
  const cam = wallCam(t);
  const proj = projector(cam);
  const g = WALL_LAYER.getContext('2d');
  g.setTransform(1, 0, 0, 1, 0, 0);
  g.clearRect(0, 0, W, H);
  const focusGlow = P(t, T.focus[0], T.focus[0] + 0.35, E.outCubic) * (1 - P(t, T.focus[1] - 0.25, T.focus[1] + 0.25));
  for (const e of EVENTS) {
    const p00 = proj(e.u, e.v);
    if (p00[2] < 260) continue;
    if (p00[0] < -700 || p00[0] > W + 200 || p00[1] < -300 || p00[1] > H + 300) continue;
    const p10 = proj(e.u + CW, e.v), p01 = proj(e.u, e.v + CH);
    if (p10[2] < 260 || p01[2] < 260) continue;
    const wpx = Math.hypot(p10[0] - p00[0], p10[1] - p00[1]);
    const cx = (p10[0] + p01[0]) / 2, cy = (p10[1] + p01[1]) / 2;
    const xr = scanState(cx, t);
    if (xr >= 1) continue;
    const depth = p00[2] / cam.dist;
    const fog = clamp(1.35 - (depth - 1) * 0.42) * clamp((depth - 0.42) * 4);
    if (fog <= 0.01) continue;
    const focus = e === FOCUS && focusGlow > 0;
    // The x-ray burns the card away: bright outline first, then it collapses into its dot.
    const burn = clamp((xr - 0.25) / 0.75);
    g.globalAlpha = fog * (1 - burn);
    g.setTransform((p10[0] - p00[0]) / CW, (p10[1] - p00[1]) / CW, (p01[0] - p00[0]) / CH, (p01[1] - p00[1]) / CH, p00[0], p00[1]);
    if (focus) {
      const s = 1 + 0.05 * focusGlow;
      g.translate(CW / 2, CH / 2);
      g.scale(s, s);
      g.translate(-CW / 2, -CH / 2);
      g.shadowColor = rgba(COL.cyan, 0.7 * focusGlow);
      g.shadowBlur = 40 * focusGlow;
    }
    drawCard(g, e, wpx > 150 ? 2 : wpx > 34 ? 1 : 0, clamp(xr / 0.25), focus && focusGlow > 0.02);
    g.shadowBlur = 0;
  }
  g.setTransform(1, 0, 0, 1, 0, 0);
  g.globalAlpha = 1;

  // Rack focus at the start, and a soft haze where the wall recedes.
  const blur = 14 * (1 - P(t, 0, 0.6, E.outCubic));
  const appear = P(t, 0, 0.45, E.outQuad);
  ctx.globalAlpha = appear;
  if (blur > 0.3) {
    ctx.filter = `blur(${blur.toFixed(2)}px)`;
    ctx.drawImage(WALL_LAYER, 0, 0);
    ctx.filter = 'none';
  } else {
    ctx.drawImage(WALL_LAYER, 0, 0);
  }
  const haze = 1 - P(t, T.pull[0], T.pull[0] + 0.5);
  if (haze > 0) {
    const s = WALL_SMALL.getContext('2d');
    s.clearRect(0, 0, W / 4, H / 4);
    s.drawImage(WALL_LAYER, 0, 0, W / 4, H / 4);
    ctx.save();
    ctx.globalAlpha = appear * haze * 0.9;
    const grad = ctx.createLinearGradient(0, 0, 0, H * 0.55);
    grad.addColorStop(0, 'rgba(0,0,0,1)');
    grad.addColorStop(1, 'rgba(0,0,0,0)');
    ctx.beginPath();
    ctx.rect(0, 0, W, H * 0.55);
    ctx.clip();
    ctx.filter = 'blur(3px)';
    ctx.drawImage(WALL_SMALL, 0, 0, W, H);
    ctx.filter = 'none';
    ctx.globalCompositeOperation = 'source-over';
    ctx.globalAlpha = appear * haze * 0.55;
    ctx.fillStyle = grad;
    ctx.fillRect(0, 0, W, H * 0.55);
    ctx.restore();
  }
  ctx.globalAlpha = 1;

  // The focus card's tracking value, called out.
  if (focusGlow > 0.01) {
    const p = proj(FOCUS.u + CW * 0.62, FOCUS.v);
    const a = focusGlow;
    const x0 = p[0], y0 = p[1] - 10;
    const len = 76 * P(t, T.focus[0] + 0.1, T.focus[0] + 0.45, E.outCubic);
    ctx.strokeStyle = rgba(COL.cyan, 0.8 * a);
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.moveTo(x0, y0);
    ctx.lineTo(x0, y0 - len);
    ctx.lineTo(x0 + len * 0.4, y0 - len);
    ctx.stroke();
    ctx.beginPath();
    ctx.arc(x0, y0, 4, 0, Math.PI * 2);
    ctx.fillStyle = rgba(COL.cyan, a);
    ctx.fill();
    ctx.globalAlpha = a * P(t, T.focus[0] + 0.3, T.focus[0] + 0.5);
    text(ctx, scramble('mail.tracking.value', P(TF, T.focus[0] + 0.3, T.focus[0] + 0.7), 7), x0 + len * 0.4 + 12, y0 - len + 8,
      font(500, 22, MONO), COL.cyan);
    ctx.globalAlpha = 1;
  }
}

// The pull-back's payoff: all of that is one year of tracked changes.
function drawReveal(ctx, t) {
  const [a, b] = T.reveal;
  if (t < a || t > b + 0.15) return;
  const pin = E.outExpo(prog(t, a, a + 0.5));
  const pout = E.inCubic(prog(t, b - 0.2, b + 0.1));
  const alpha = clamp(pin * 1.4) * (1 - pout);
  if (alpha <= 0) return;
  ctx.save();
  ctx.globalAlpha = alpha * 0.9;
  const g = ctx.createRadialGradient(W / 2, H / 2 + 30, 0, W / 2, H / 2 + 30, 640);
  g.addColorStop(0, 'rgba(3,6,12,0.92)');
  g.addColorStop(1, 'rgba(3,6,12,0)');
  ctx.fillStyle = g;
  ctx.fillRect(0, 0, W, H);
  ctx.globalAlpha = alpha;
  const k = 1 + 0.08 * pout;
  ctx.translate(W / 2, H / 2 + 20);
  ctx.scale(k, k);
  ctx.shadowColor = rgba(COL.cyan, 0.45);
  ctx.shadowBlur = 44;
  text(ctx, fmt(EVENTS.length * E.outCubic(prog(TF, a, a + 0.6))), 0, 50 + (1 - pin) * 36, font(800, 230), COL.ink, 'center');
  ctx.shadowBlur = 0;
  text(ctx, `tracked changes · ${fmt(ORDERS)} orders · one year`, 0, 128 + (1 - pin) * 24, font(500, 30, MONO), COL.muted, 'center', 1);
  ctx.restore();
}

function drawBeam(ctx, t) {
  if (t < T.scan[0] || t > T.scan[1]) return;
  const x = beamX(t);
  const life = Math.sin(Math.PI * prog(t, T.scan[0], T.scan[1]));
  ctx.save();
  ctx.globalCompositeOperation = 'lighter';
  let g = ctx.createLinearGradient(x - 420, 0, x + 60, 0);
  g.addColorStop(0, rgba(COL.cyan, 0));
  g.addColorStop(0.82, rgba(COL.cyan, 0.1 * life));
  g.addColorStop(0.97, rgba(COL.cyan, 0.32 * life));
  g.addColorStop(1, rgba(COL.cyan, 0));
  ctx.fillStyle = g;
  ctx.fillRect(x - 420, 0, 480, H);
  g = ctx.createLinearGradient(x - 26, 0, x + 26, 0);
  g.addColorStop(0, rgba(COL.cyan, 0));
  g.addColorStop(0.5, rgba('#ffffff', 0.95 * life));
  g.addColorStop(1, rgba(COL.cyan, 0));
  ctx.fillStyle = g;
  ctx.fillRect(x - 26, 0, 52, H);
  // Scan lines riding the beam.
  for (let i = 0; i < 26; i++) {
    const y = (hash(i * 3 + Math.floor(t * 30)) * H) | 0;
    ctx.fillStyle = rgba(COL.ice, 0.25 * life * hash(i + 77));
    ctx.fillRect(x - 160 * hash(i + 5), y, 160 * hash(i + 5) + 20, 1.5);
  }
  ctx.restore();
  // The beam's tag and its counter.
  const converted = EVENTS.length * P(TF, T.scan[0] + 0.05, T.scan[1] - 0.05, E.inOutSine);
  ctx.globalAlpha = clamp(life * 3);
  ctx.fillStyle = 'rgba(4,10,20,0.75)';
  ctx.beginPath();
  ctx.roundRect(x + 18, 118, 208, 74, 10);
  ctx.fill();
  ctx.strokeStyle = rgba(COL.cyan, 0.5);
  ctx.lineWidth = 1.5;
  ctx.stroke();
  text(ctx, 'X-RAY', x + 34, 146, font(700, 18, MONO), COL.cyan, 'left', 4);
  text(ctx, `${fmt(converted)} events`, x + 34, 176, font(500, 21, MONO), COL.ink);
  ctx.globalAlpha = 1;
}

// ------------------------------------------------------------------ 03-04: every event as a particle

const CHART = { x0: 800, x1: 1830, y0: 150, y1: 950 };
const chartX = (days) => CHART.x0 + (Math.log1p(days) / Math.log1p(DMAX)) * (CHART.x1 - CHART.x0);
const chartY = (order) => CHART.y0 + (order / (ORDERS - 1)) * (CHART.y1 - CHART.y0);
// When each activity's events leave for the map: in process order, so the map fills from the top.
const SWARM_DELAY = { 0: 0, 1: 0.1, 2: 0.2, 10: 0.26, 3: 0.32, 4: 0.36, 5: 0.34, 6: 0.46, 8: 0.54, 9: 0.6, 7: 0.5 };
for (const e of EVENTS) {
  e.cx = chartX(e.rel);
  e.cy = chartY(e.order);
  e.tc = T.chart + (e.order / ORDERS) * 0.26 + hash(e.i * 7) * 0.1;
  e.dc = 0.5 + hash(e.i * 3) * 0.12;
  const node = Object.values(NODES).find((n) => n.act === e.act);
  e.node = node;
  e.jx = (hash(e.i * 11) - 0.5) * (node ? node.w * 0.7 : 0);
  e.jy = (hash(e.i * 13) - 0.5) * 34;
  e.tm = T.swarm + (SWARM_DELAY[e.act] || 0) + hash(e.i * 17) * 0.34;
  e.dm = 0.62 + hash(e.i * 19) * 0.22;
  e.arrive = e.tm + e.dm;
}
// Arrival times of each order's first event per activity, sorted: that is the node's counter.
for (const n of Object.values(NODES)) {
  n.arrivals = EVENTS.filter((e) => e.node === n && e.first).map((e) => e.arrive).sort((a, b) => a - b);
  n.t0 = Math.min(...EVENTS.filter((e) => e.node === n).map((e) => e.arrive)) - 0.14;
}
function arrived(list, t) {
  let lo = 0, hi = list.length;
  while (lo < hi) { const mid = (lo + hi) >> 1; if (list[mid] <= t) lo = mid + 1; else hi = mid; }
  return lo;
}

function wallPoint(e, t) {
  // After the pull-back the wall is flat and only zooms, so this is exact.
  const c = wallCam(Math.max(t, T.pull[1]));
  const k = FOCAL / c.dist;
  return [W / 2 + (e.u + 46 - WALL_CX) * k, H / 2 + (e.v + 46 - WALL_CY) * k];
}

function drawDots(ctx, t, cam) {
  if (t < T.scan[0] || t > T.swarm + 1.8) return;
  const flatProj = projector(wallCam(t));
  ctx.save();
  ctx.globalCompositeOperation = 'lighter';
  for (const e of EVENTS) {
    let x, y, size = 10, a = 1, sprite = GLOW[e.act];
    if (t < e.tc) {
      const p00 = flatProj(e.u, e.v), p10 = flatProj(e.u + CW, e.v), p01 = flatProj(e.u, e.v + CH);
      const xr = scanState((p10[0] + p01[0]) / 2, t);
      if (xr <= 0.25) continue;
      const k = clamp((xr - 0.25) / 0.75);
      const p = flatProj(e.u + 46, e.v + 46);
      x = p[0];
      y = p[1];
      size = lerp(30, 13, k);
      a = lerp(0.25, 1, k);
      sprite = k < 0.6 ? GLOW_ICE : sprite;
    } else if (t < e.tm) {
      const u = E.inOutCubic(prog(t, e.tc, e.tc + e.dc));
      const [sx, sy] = wallPoint(e, e.tc);
      const k = 0.12 + 0.12 * hash(e.i * 31);
      const mx = (sx + e.cx) / 2 + (e.cy - sy) * k, my = (sy + e.cy) / 2 - (e.cx - sx) * k;
      x = (1 - u) * (1 - u) * sx + 2 * u * (1 - u) * mx + u * u * e.cx;
      y = (1 - u) * (1 - u) * sy + 2 * u * (1 - u) * my + u * u * e.cy;
      size = lerp(13, 11, u);
    } else {
      if (!e.node || t >= e.arrive) continue;
      const u = E.inOutCubic(prog(t, e.tm, e.arrive));
      const [nx, ny] = apply(cam, e.node.x + e.jx, e.node.y + e.jy);
      const k = 0.3 + 0.22 * hash(e.i * 29);
      const mx = (e.cx + nx) / 2 - (ny - e.cy) * k, my = (e.cy + ny) / 2 + (nx - e.cx) * k;
      x = (1 - u) * (1 - u) * e.cx + 2 * u * (1 - u) * mx + u * u * nx;
      y = (1 - u) * (1 - u) * e.cy + 2 * u * (1 - u) * my + u * u * ny;
      size = lerp(11, 17, Math.sin(Math.PI * u));
      a = 1 - 0.4 * P(u, 0.85, 1);
    }
    ctx.globalAlpha = a;
    ctx.drawImage(sprite, x - size / 2, y - size / 2, size, size);
  }
  ctx.restore();
}

function drawChartLabels(ctx, t) {
  const a = P(t, T.chartLabels[0], T.chartLabels[0] + 0.3) * (1 - P(t, T.chartLabels[1] - 0.15, T.chartLabels[1] + 0.15));
  if (a <= 0) return;
  ctx.globalAlpha = a;
  const y = CHART.y1 + 34;
  ctx.strokeStyle = rgba(COL.muted, 0.4);
  ctx.lineWidth = 1.5;
  ctx.beginPath();
  ctx.moveTo(CHART.x0, y);
  ctx.lineTo(CHART.x0 + (CHART.x1 - CHART.x0) * P(t, T.chartLabels[0], T.chartLabels[0] + 0.4, E.outCubic), y);
  ctx.stroke();
  for (const [days, label] of [[0, 'created'], [1, '1 day'], [7, '1 week'], [30, '1 month'], [90, '3 months']]) {
    if (days > DMAX) continue;
    const x = chartX(days);
    ctx.beginPath();
    ctx.moveTo(x, y - 6);
    ctx.lineTo(x, y + 6);
    ctx.stroke();
    text(ctx, label, x, y + 32, font(500, 18, MONO), COL.muted, 'center');
  }
  text(ctx, scramble('EVENT LOG · ONE ROW PER ORDER', P(TF, T.chartLabels[0], T.chartLabels[0] + 0.5), 3),
    CHART.x0, CHART.y0 - 34, font(600, 19, MONO), COL.cyan, 'left', 3);
  text(ctx, `${fmt(ORDERS)} orders · ${fmt(EVENTS.length)} events`, CHART.x1, CHART.y0 - 34, font(500, 19, MONO), COL.muted, 'right');
  ctx.globalAlpha = 1;
}

// ------------------------------------------------------------------ 04: the process map

// Map camera: a uniform scale and a translation, {s, x, y}: screen = p * s + (x, y).
const apply = (c, x, y) => [x * c.s + c.x, y * c.s + c.y];
const compose = (a, b) => ({ s: a.s * b.s, x: b.x * a.s + a.x, y: b.y * a.s + a.y });
const around = (s, px, py) => ({ s, x: px - px * s, y: py - py * s });

// The report window (06), and where the map lands inside it.
const RW = { x: 862, y: 176, w: 960, h: 724 };
const MINI = { s: 0.37, cx: RW.x + 34 + 196, cy: RW.y + 352 + 168 };

function windowExit(t) {
  const x = P(t, 12.9, 13.28, E.inCubic);
  const push = 1 + 0.03 * E.inOutSine(prog(t, 11.3, 12.95));
  return { k: push * (1 - 0.12 * x), a: 1 - x };
}

function mapCam(t) {
  let c = around(1 + 0.03 * E.inOutSine(prog(t, 4.9, 7.3)), MAP_PIVOT.x, MAP_PIVOT.y);
  const side = P(t, T.dim - 0.1, T.dim + 0.5, E.inOutCubic);
  if (side > 0) c = compose(around(lerp(1, 0.94, side), 1862, 548), c);
  const m = P(t, T.report, T.report + 0.62, E.inOutCubic);
  if (m > 0) {
    const target = { s: MINI.s, x: MINI.cx - MAP_PIVOT.x * MINI.s, y: MINI.cy - MAP_PIVOT.y * MINI.s };
    c = { s: lerp(c.s, target.s, m), x: lerp(c.x, target.x, m), y: lerp(c.y, target.y, m) };
  }
  const ex = windowExit(t);
  if (ex.k < 1) c = compose(around(ex.k, RW.x + RW.w / 2, RW.y + RW.h / 2), c);
  return c;
}

function port(n, side, dy = 0) {
  return side === 'top' ? [n.x, n.y - NODE_H / 2] : side === 'bottom' ? [n.x, n.y + NODE_H / 2]
    : side === 'left' ? [n.x - n.w / 2, n.y + dy] : [n.x + n.w / 2, n.y + dy];
}
function bezierPoints(p0, p1, p2, p3, steps = 48) {
  const pts = [];
  for (let i = 0; i <= steps; i++) {
    const u = i / steps, v = 1 - u;
    pts.push([v * v * v * p0[0] + 3 * v * v * u * p1[0] + 3 * v * u * u * p2[0] + u * u * u * p3[0],
      v * v * v * p0[1] + 3 * v * v * u * p1[1] + 3 * v * u * u * p2[1] + u * u * u * p3[1]]);
  }
  return pts;
}
const MAIN_ORDER = ['Quotation created', 'Quotation sent', 'Order confirmed', 'Goods shipped', 'Invoice posted', 'Payment received'];
const LEFT_BULGE = { 'Quotation created>Order confirmed': 96, 'Order confirmed>Invoice posted': 150,
  'Invoice posted>Goods shipped': 62, 'Goods shipped>Payment received': 205 };

const EDGES = D.edges.filter(([a, b, n]) => n >= 10 && NODES[a] && NODES[b]).map(([from, to, count, days]) => {
  const a = NODES[from], b = NODES[to];
  let pts;
  if (a === b) {
    const [x, y] = port(a, 'right');
    pts = bezierPoints([x, y - 14], [x + 90, y - 70], [x + 90, y + 70], [x, y + 14], 32);
  } else if (a.main && b.main) {
    const ia = MAIN_ORDER.indexOf(from), ib = MAIN_ORDER.indexOf(to);
    if (ib === ia + 1) {
      pts = bezierPoints(port(a, 'bottom'), port(a, 'bottom'), port(b, 'top'), port(b, 'top'), 8);
    } else {
      const bulge = LEFT_BULGE[`${from}>${to}`] || 120;
      const p0 = port(a, 'left', ib > ia ? 12 : -12), p3 = port(b, 'left', ib > ia ? -12 : 12);
      pts = bezierPoints(p0, [p0[0] - bulge, p0[1]], [p3[0] - bulge, p3[1]], p3);
    }
  } else if (a.main) {
    const p0 = port(a, 'right', -12), p3 = port(b, 'left', -12);
    const dx = (p3[0] - p0[0]) * 0.5;
    pts = bezierPoints(p0, [p0[0] + dx, p0[1]], [p3[0] - dx, p3[1]], p3);
  } else {
    const p0 = port(a, 'left', 12), p3 = port(b, 'right', 14);
    const dx = (p0[0] - p3[0]) * 0.5;
    pts = bezierPoints(p0, [p0[0] - dx, p0[1]], [p3[0] + dx, p3[1]], p3);
  }
  const lens = [0];
  for (let i = 1; i < pts.length; i++) lens.push(lens[i - 1] + Math.hypot(pts[i][0] - pts[i - 1][0], pts[i][1] - pts[i - 1][1]));
  const wait = clamp(Math.log1p(days) / Math.log1p(28));
  return {
    key: `${from}>${to}`, from: a, to: b, count, days, pts, lens, len: lens[lens.length - 1],
    width: 1.8 + 11 * Math.sqrt(count / ORDERS), color: mix('#9cf1ff', '#7266ff', wait), hex: wait,
    t0: Math.max(a.t0, b.t0) + 0.2 + hash(count) * 0.1,
    travel: 0.55 + 0.85 * Math.log1p(days),
  };
});
const EDGE = Object.fromEntries(EDGES.map((e) => [e.key, e]));

function pointAt(e, s) {
  const d = clamp(s) * e.len;
  let lo = 0, hi = e.lens.length - 1;
  while (lo < hi - 1) { const mid = (lo + hi) >> 1; if (e.lens[mid] <= d) lo = mid; else hi = mid; }
  const f = (d - e.lens[lo]) / Math.max(1e-6, e.lens[hi] - e.lens[lo]);
  const p = e.pts[lo], q = e.pts[hi];
  return [lerp(p[0], q[0], f), lerp(p[1], q[1], f), Math.atan2(q[1] - p[1], q[0] - p[0])];
}
const duration = (d) => (d < 1 ? `${Math.max(1, Math.round(d * 24))} h` : `${d.toFixed(1)} d`);

// Which part of the map a finding is about (05).
const FINDINGS = [
  { edge: 'Order confirmed>Order changed after confirmation', node: 'Order changed after confirmation',
    tag: `${D.findings.changed.hits} orders`, at: [SIDE_X, NODES['Order changed after confirmation'].y - NODE_H / 2 - 34], align: 'center' },
  { edge: 'Order confirmed>Invoice posted', node: 'Invoice posted',
    tag: `${D.findings.invoicedEarly.hits} invoiced first`, at: [MAIN_X - 186 - 24, NODES['Invoice posted'].y - 12], align: 'right' },
  { edge: 'Invoice posted>Payment received', node: 'Payment received',
    tag: `${duration(EDGE['Invoice posted>Payment received'].days)} to pay`, at: [MAIN_X + 24, 849], align: 'left' },
];
function focusOf(t) {
  // How much each finding is in focus right now (0..1), and how much the rest of the map steps back.
  const weights = FINDINGS.map((f, k) => {
    const a = T.cards[k], b = T.cards[k + 1];
    return P(t, a - 0.05, a + 0.25, E.outCubic) * (1 - P(t, b - 0.12, b + 0.12));
  });
  const dim = P(t, T.dim, T.dim + 0.4, E.outCubic) * (1 - P(t, T.report, T.report + 0.3));
  return { weights, dim };
}

function drawMap(ctx, t) {
  if (t < T.swarm + 0.2) return;
  const cam = mapCam(t);
  const ex = windowExit(t);
  if (ex.a <= 0) return;
  const { weights, dim } = focusOf(t);
  const hotEdge = (e) => Math.max(0, ...FINDINGS.map((f, k) => (f.edge === e.key ? weights[k] : 0)));
  const hotNode = (n) => Math.max(0, ...FINDINGS.map((f, k) => (f.node === n.name ? weights[k] : 0)));
  ctx.save();
  ctx.setTransform(cam.s, 0, 0, cam.s, cam.x, cam.y);
  ctx.globalAlpha = ex.a;
  ctx.lineCap = 'round';
  ctx.lineJoin = 'round';

  // Edges draw themselves on, arrow last.
  for (const e of EDGES) {
    const f = P(t, e.t0, e.t0 + 0.55, E.inOutCubic);
    if (f <= 0) continue;
    const hot = hotEdge(e);
    const alpha = lerp(0.85, 0.2, dim) + hot * 0.8;
    ctx.strokeStyle = hot > 0.01 ? mix('#9cf1ff', COL.hot, clamp(hot * 1.3), clamp(alpha)) : e.color.replace(/,1\)$/, `,${alpha})`);
    ctx.lineWidth = e.width + hot * 3;
    ctx.beginPath();
    const end = f * e.len;
    ctx.moveTo(e.pts[0][0], e.pts[0][1]);
    for (let i = 1; i < e.pts.length && e.lens[i - 1] < end; i++) {
      const q = e.lens[i] <= end ? e.pts[i] : pointAt(e, end / e.len);
      ctx.lineTo(q[0], q[1]);
    }
    ctx.stroke();
    if (f > 0.96) {
      const [x, y, ang] = pointAt(e, 1);
      const s = 7 + e.width * 0.55;
      ctx.fillStyle = ctx.strokeStyle;
      ctx.beginPath();
      ctx.moveTo(x + Math.cos(ang) * 2, y + Math.sin(ang) * 2);
      ctx.lineTo(x - Math.cos(ang - 0.5) * s * 1.5, y - Math.sin(ang - 0.5) * s * 1.5);
      ctx.lineTo(x - Math.cos(ang + 0.5) * s * 1.5, y - Math.sin(ang + 0.5) * s * 1.5);
      ctx.fill();
    }
  }

  // Orders flowing: slow edges crawl, and that is where the waiting is.
  ctx.globalCompositeOperation = 'lighter';
  for (const e of EDGES) {
    const on = P(t, e.t0 + 0.45, e.t0 + 0.9);
    if (on <= 0) continue;
    const hot = hotEdge(e);
    const n = Math.round(clamp(e.count / 14, 2, 30));
    const alpha = on * (lerp(1, 0.35, dim) + hot) * ex.a;
    const sprite = hot > 0.3 ? GLOW_HOT : GLOW[e.to.act];
    for (let j = 0; j < n; j++) {
      const s = ((t - e.t0) / e.travel + hash(j * 97 + e.count)) % 1;
      const fade = clamp(s * 8) * clamp((1 - s) * 8);
      for (let k = 0; k < 4; k++) {
        const [x, y] = pointAt(e, s - k * 0.012);
        const size = (16 - k * 3) * (1 + hot * 0.4);
        ctx.globalAlpha = alpha * fade * (1 - k * 0.22);
        ctx.drawImage(sprite, x - size / 2, y - size / 2, size, size);
      }
    }
  }
  ctx.globalCompositeOperation = 'source-over';

  // Nodes: they pop in as the first events land, and count every order that arrives.
  for (const n of Object.values(NODES)) {
    const s = t - n.t0;
    if (s <= 0) continue;
    const pop = spring(s, 15, 0.55);
    const hot = hotNode(n);
    const count = t > 9 ? n.count : arrived(n.arrivals, TF);
    const recent = count - arrived(n.arrivals, TF - 0.12);
    const absorb = clamp(recent / 25);
    ctx.save();
    ctx.globalAlpha = clamp(pop * 1.5) * lerp(1, 0.55, dim * (1 - hot)) * ex.a;
    ctx.translate(n.x, n.y);
    ctx.scale(lerp(0.7, 1, pop), lerp(0.7, 1, pop));
    const accent = hot > 0.01 ? mix(ACT_COL[n.act], COL.hot, hot) : ACT_COL[n.act];
    ctx.shadowColor = hot > 0.01 ? rgba(COL.hot, 0.6 * hot) : rgba(ACT_COL[n.act], 0.25 + 0.5 * absorb);
    ctx.shadowBlur = 22 + 30 * Math.max(absorb, hot);
    ctx.beginPath();
    ctx.roundRect(-n.w / 2, -NODE_H / 2, n.w, NODE_H, 16);
    ctx.fillStyle = n.main ? 'rgba(13,22,42,0.94)' : 'rgba(22,20,38,0.94)';
    ctx.fill();
    ctx.shadowBlur = 0;
    ctx.lineWidth = 1.5 + hot * 1.5;
    ctx.strokeStyle = typeof accent === 'string' && accent.startsWith('#') ? rgba(accent, 0.7) : accent;
    ctx.stroke();
    text(ctx, n.label, 0, -4, font(620, 26), COL.ink, 'center');
    text(ctx, `${fmt(count)} orders`, 0, 25, font(500, 18, MONO), hot > 0.3 ? COL.hot2 : COL.muted, 'center');
    ctx.restore();
  }

  // Edge labels: how many orders, and the median wait.
  for (const e of EDGES) {
    if (e.count < 19 || e.from === e.to) continue;
    const a = P(t, e.t0 + 0.4, e.t0 + 0.8) * lerp(1, 0.25, dim) * (1 - hotEdge(e)) * ex.a;
    if (a <= 0) continue;
    const vertical = e.from.main && e.to.main && Math.abs(e.pts[0][0] - e.pts[e.pts.length - 1][0]) < 1;
    let [x, y] = pointAt(e, 0.5);
    if (vertical) x += 16;
    const label = `${e.count} · ${duration(e.days)}`;
    const f = font(500, 17, MONO);
    const w = measure(ctx, label, f);
    ctx.globalAlpha = a;
    ctx.fillStyle = 'rgba(5,9,19,0.82)';
    ctx.beginPath();
    ctx.roundRect(vertical ? x - 6 : x - w / 2 - 8, y - 14, w + 16, 26, 7);
    ctx.fill();
    text(ctx, label, vertical ? x + 2 : x, y + 5, f, COL.muted, vertical ? 'left' : 'center');
  }

  // Tags on the part of the map each finding is about.
  FINDINGS.forEach((fd, k) => {
    const w = weights[k];
    if (w <= 0.01) return;
    const [x, y] = pointAt(EDGE[fd.edge], 0.5);
    const pulse = (t - T.cards[k]) % 0.9;
    ctx.globalAlpha = w * (1 - pulse / 0.9) * ex.a;
    ctx.strokeStyle = COL.hot;
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.arc(x, y, 14 + pulse * 70, 0, Math.PI * 2);
    ctx.stroke();
    ctx.globalAlpha = w * ex.a;
    const f = font(650, 20, MONO);
    const tw = measure(ctx, fd.tag, f);
    const bw = tw + 30;
    const bx = fd.align === 'center' ? fd.at[0] - bw / 2 : fd.align === 'right' ? fd.at[0] - bw : fd.at[0];
    const by = fd.at[1] - 20 + (1 - E.outCubic(clamp(w * 1.4))) * 12;
    ctx.fillStyle = 'rgba(40,8,18,0.92)';
    ctx.beginPath();
    ctx.roundRect(bx, by, bw, 40, 20);
    ctx.fill();
    ctx.strokeStyle = rgba(COL.hot, 0.9);
    ctx.lineWidth = 1.5;
    ctx.stroke();
    text(ctx, fd.tag, bx + 15, by + 27, f, '#ffd3db');
  });
  ctx.restore();
}

// ------------------------------------------------------------------ 05: findings

const CARDS = [
  { label: 'CHANGED AFTER CONFIRMATION', big: D.findings.changed.share, side: ['of them come from', 'one salesperson'],
    bars: [['Their orders', D.findings.changed.groupRate], ['Average', D.findings.changed.rate]], fix: 'Lock Confirmed Sales' },
  { label: 'INVOICED BEFORE SHIPPING', big: D.findings.invoicedEarly.share, side: ['of them ship from', 'one warehouse'],
    bars: [[D.findings.invoicedEarly.values[0], D.findings.invoicedEarly.groupRate], ['Brussels DC', 0]],
    fix: 'Invoicing Policy: Delivered qty' },
  { label: 'PAID 2+ WEEKS LATE', big: D.findings.paidLate.share, side: ['of them come from', `${D.findings.paidLate.values.length === 5 ? 'five' : D.findings.paidLate.values.length} customers`],
    bars: [['Those customers', D.findings.paidLate.groupRate], ['Average', D.findings.paidLate.rate]], fix: 'Sales Credit Limit' },
];

function toggle(ctx, x, y, on) {
  ctx.beginPath();
  ctx.roundRect(x, y, 64, 36, 18);
  ctx.fillStyle = mix('#2a3552', COL.green, on);
  ctx.fill();
  const kx = x + lerp(18, 46, on);
  ctx.beginPath();
  ctx.arc(kx, y + 18, 14, 0, Math.PI * 2);
  ctx.fillStyle = '#ffffff';
  ctx.fill();
}

function drawCards(ctx, t) {
  CARDS.forEach((c, k) => {
    const s = T.cards[k], e = T.cards[k + 1];
    if (t < s - 0.05 || t > e + 0.25) return;
    const pin = E.outExpo(prog(t, s, s + 0.55));
    const pout = E.inCubic(prog(t, e - 0.22, e + 0.02));
    const x = 112, y0 = 450 + (1 - pin) * 60 - pout * 70;
    const a = clamp(pin * 1.5) * (1 - pout);
    if (a <= 0) return;
    ctx.save();
    ctx.globalAlpha = a;
    // Index and label.
    text(ctx, `0${k + 1}`, x, y0, font(700, 21, MONO), COL.hot, 'left', 2);
    text(ctx, scramble(c.label, P(TF, s + 0.02, s + 0.4), k * 50), x + 48, y0, font(600, 21, MONO), '#ffc2cc', 'left', 3);
    // The share, counting up.
    const pct = Math.round(c.big * 100 * E.outExpo(prog(TF, s + 0.06, s + 0.62)));
    const bigF = font(800, 140);
    const bigStr = `${pct}%`;
    const bw = measure(ctx, `${Math.round(c.big * 100)}%`, bigF);
    const g = ctx.createLinearGradient(x, y0 + 30, x, y0 + 170);
    g.addColorStop(0, '#ff8aa0');
    g.addColorStop(1, COL.hot);
    ctx.shadowColor = rgba(COL.hot, 0.55);
    ctx.shadowBlur = 44;
    text(ctx, bigStr, x - 6, y0 + 154, bigF, g);
    ctx.shadowBlur = 0;
    const sa = P(t, s + 0.18, s + 0.45);
    ctx.globalAlpha = a * sa;
    text(ctx, c.side[0], x + bw + 18, y0 + 102 + (1 - sa) * 10, font(500, 30), COL.muted);
    text(ctx, c.side[1], x + bw + 18, y0 + 142 + (1 - sa) * 10, font(750, 34), COL.ink);
    // Evidence: rate inside the group against the average.
    c.bars.forEach(([label, v], j) => {
      const by = y0 + 214 + j * 44;
      const grow = E.outCubic(prog(t, s + 0.24 + j * 0.06, s + 0.7 + j * 0.06));
      ctx.globalAlpha = a * P(t, s + 0.2 + j * 0.06, s + 0.4 + j * 0.06);
      text(ctx, label, x, by + 7, font(500, 21), COL.muted);
      ctx.fillStyle = 'rgba(120,140,190,0.16)';
      ctx.fillRect(x + 190, by - 6, 330, 14);
      ctx.fillStyle = j === 0 ? COL.hot : '#8a9ab8';
      ctx.fillRect(x + 190, by - 6, 330 * v * grow, 14);
      const shown = Math.round(v * 100 * E.outCubic(prog(TF, s + 0.24 + j * 0.06, s + 0.7 + j * 0.06)));
      text(ctx, `${shown}%`, x + 190 + Math.max(330 * v * grow, 0) + 12, by + 8, font(650, 20, MONO), j === 0 ? '#ffc2cc' : COL.muted);
    });
    // The Odoo setting that fixes it, switched on.
    const ca = P(t, s + 0.32, s + 0.52, E.outCubic);
    ctx.globalAlpha = a * ca;
    const cy = y0 + 318 + (1 - ca) * 16;
    text(ctx, 'FIX IN ODOO', x, cy, font(600, 17, MONO), COL.green, 'left', 3);
    const on = E.inOutCubic(prog(t, s + 0.55, s + 0.72));
    const chipW = 104 + measure(ctx, c.fix, font(650, 26));
    ctx.beginPath();
    ctx.roundRect(x, cy + 16, chipW, 62, 14);
    ctx.fillStyle = mix('#101a2e', '#0d2a26', on, 0.95);
    ctx.fill();
    ctx.strokeStyle = mix('#3a4a6e', COL.green, on, 0.9);
    ctx.lineWidth = 1.5;
    ctx.stroke();
    toggle(ctx, x + 14, cy + 29, on);
    text(ctx, c.fix, x + 92, cy + 56, font(650, 26), mix(COL.muted, COL.ink, on));
    if (on > 0 && on < 1) {
      ctx.globalCompositeOperation = 'lighter';
      ctx.globalAlpha = a * Math.sin(Math.PI * on) * 0.8;
      ctx.drawImage(GLOW_GREEN, x + 14 + 46 - 60, cy + 47 - 60, 120, 120);
    }
    ctx.restore();
  });
}

// ------------------------------------------------------------------ 06: the report

function typed(str, p) { return str.slice(0, Math.round(str.length * clamp(p))); }

function drawReport(ctx, t) {
  if (t < T.report) return;
  const ex = windowExit(t);
  if (ex.a <= 0) return;
  const ap = E.outExpo(prog(t, T.report + 0.05, T.report + 0.7));
  ctx.save();
  const cx = RW.x + RW.w / 2, cy = RW.y + RW.h / 2;
  ctx.translate(cx, cy);
  ctx.scale(ex.k * lerp(0.94, 1, ap), ex.k * lerp(0.94, 1, ap));
  ctx.translate(-cx, -cy + (1 - ap) * 40);
  ctx.globalAlpha = clamp(ap * 1.4) * ex.a;
  // Window.
  ctx.shadowColor = 'rgba(0,0,0,0.6)';
  ctx.shadowBlur = 60;
  ctx.beginPath();
  ctx.roundRect(RW.x, RW.y, RW.w, RW.h, 20);
  ctx.fillStyle = 'rgba(11,17,32,0.96)';
  ctx.fill();
  ctx.shadowBlur = 0;
  ctx.strokeStyle = 'rgba(140,170,255,0.2)';
  ctx.lineWidth = 1.5;
  ctx.stroke();
  ctx.beginPath();
  ctx.moveTo(RW.x, RW.y + 48);
  ctx.lineTo(RW.x + RW.w, RW.y + 48);
  ctx.stroke();
  ['#ff5f57', '#febc2e', '#28c840'].forEach((c, i) => {
    ctx.beginPath();
    ctx.arc(RW.x + 26 + i * 22, RW.y + 24, 6.5, 0, Math.PI * 2);
    ctx.fillStyle = rgba(c, 0.85);
    ctx.fill();
  });
  ctx.beginPath();
  ctx.roundRect(RW.x + RW.w / 2 - 110, RW.y + 11, 220, 26, 13);
  ctx.fillStyle = 'rgba(255,255,255,0.05)';
  ctx.fill();
  text(ctx, 'report.html', RW.x + RW.w / 2, RW.y + 29, font(500, 15, MONO), COL.muted, 'center');
  // Header.
  const px = RW.x + 36;
  const r = (d) => P(t, T.report + 0.42 + d, T.report + 0.72 + d, E.outCubic);
  ctx.globalAlpha = ex.a * r(0);
  text(ctx, 'ODOO PROCESS X-RAY · ORDER-TO-CASH', px, RW.y + 92, font(500, 14, MONO), COL.muted, 'left', 2);
  text(ctx, `${D.company} (fictional)`, px, RW.y + 136, font(750, 36), COL.ink);
  // Headline numbers, counting up.
  const st = D.stats;
  const tiles = [
    ['Sales orders analysed', (p) => fmt(st.orders * p), '1 Sep 2025 – 31 Aug 2026'],
    ['Quotations confirmed', (p) => `${Math.round(st.conversion * 100 * p)}%`, `${st.confirmed} of ${st.orders}`],
    ['Order to cash (median)', (p) => `${(st.orderToCashDays * p).toFixed(1)} days`, 'confirmation to payment'],
    ['Orders with a problem', (p) => `${Math.round(st.problemShare * 100 * p)}%`, `${st.problemOrders} orders, ${st.problemKinds} kinds`],
  ];
  const tw = (RW.w - 72 - 48) / 4;
  tiles.forEach(([label, value, sub], i) => {
    const a = r(0.08 + i * 0.06);
    const p = E.outExpo(prog(TF, T.report + 0.5 + i * 0.06, T.report + 1.35 + i * 0.06));
    const x = px + i * (tw + 16), y = RW.y + 166 + (1 - a) * 20;
    ctx.globalAlpha = ex.a * a;
    ctx.beginPath();
    ctx.roundRect(x, y, tw, 140, 14);
    ctx.fillStyle = 'rgba(255,255,255,0.035)';
    ctx.fill();
    ctx.strokeStyle = i === 3 ? rgba(COL.hot, 0.35) : 'rgba(140,170,255,0.16)';
    ctx.stroke();
    text(ctx, label, x + 18, y + 32, font(500, 16), COL.muted);
    text(ctx, value(p), x + 18, y + 86, font(750, 42), i === 3 ? '#ff8aa0' : COL.ink);
    text(ctx, sub, x + 18, y + 120, font(450, 14), COL.dim);
  });
  // Key findings next to the map (the map itself is drawn by drawMap and lands here).
  const fx = RW.x + 480, fy = RW.y + 356;
  ctx.globalAlpha = ex.a * r(0.3);
  text(ctx, 'Key findings', fx, fy, font(700, 24), COL.ink);
  const lines = [
    ['Changed after confirmation', `${Math.round(D.findings.changed.share * 100)}% one salesperson`],
    ['Invoiced before shipping', `${Math.round(D.findings.invoicedEarly.share * 100)}% one warehouse`],
    ['Paid 2+ weeks late', `${Math.round(D.findings.paidLate.share * 100)}% five customers`],
    ['Warsaw ships Thu/Fri orders', `${D.findings.bottleneck.slow[1][1]} d vs ${D.findings.bottleneck.typical} d`],
  ];
  lines.forEach(([a, b], i) => {
    ctx.globalAlpha = ex.a * r(0.36 + i * 0.07);
    const y = fy + 46 + i * 58;
    ctx.beginPath();
    ctx.arc(fx + 8, y - 6, 5, 0, Math.PI * 2);
    ctx.fillStyle = COL.hot;
    ctx.fill();
    text(ctx, a, fx + 26, y, font(600, 19), COL.ink);
    text(ctx, b, fx + 26, y + 24, font(500, 16, MONO), '#ff9fb1');
  });
  // The AI summary badge: numbers checked against the analysis.
  const ba = r(0.7);
  ctx.globalAlpha = ex.a * ba;
  const by = RW.y + RW.h - 74;
  ctx.beginPath();
  ctx.roundRect(fx, by, 446, 44, 22);
  ctx.fillStyle = 'rgba(62,230,168,0.08)';
  ctx.fill();
  ctx.strokeStyle = rgba(COL.green, 0.5);
  ctx.stroke();
  text(ctx, 'AI summary · every number checked', fx + 22, by + 29, font(500, 17, MONO), '#aef5da');
  const ck = P(t, T.report + 1.3, T.report + 1.55, E.outCubic);
  ctx.strokeStyle = COL.green;
  ctx.lineWidth = 3;
  ctx.beginPath();
  const kx = fx + 410, ky = by + 22;
  ctx.moveTo(kx - 10, ky);
  if (ck > 0) ctx.lineTo(kx - 10 + 7 * clamp(ck * 2), ky + 7 * clamp(ck * 2));
  if (ck > 0.5) ctx.lineTo(kx - 3 + 14 * clamp(ck * 2 - 1), ky + 7 - 15 * clamp(ck * 2 - 1));
  ctx.stroke();
  ctx.restore();

  // The command, typed.
  const ca = P(t, T.h5[0] + 0.3, T.h5[0] + 0.6, E.outCubic) * ex.a;
  if (ca > 0) {
    const y = 646;
    ctx.globalAlpha = ca;
    ctx.beginPath();
    ctx.roundRect(112, y, 560, 70, 14);
    ctx.fillStyle = 'rgba(8,14,28,0.9)';
    ctx.fill();
    ctx.strokeStyle = rgba(COL.cyan, 0.35);
    ctx.lineWidth = 1.5;
    ctx.stroke();
    const cmd = 'python -m xray run';
    const shown = typed(cmd, prog(TF, T.h5[0] + 0.45, T.h5[0] + 0.95));
    text(ctx, '$', 136, y + 45, font(600, 27, MONO), COL.cyan);
    text(ctx, shown, 168, y + 45, font(500, 27, MONO), COL.ink);
    const cw = measure(ctx, shown, font(500, 27, MONO));
    if (Math.floor(TF * 3.2) % 2 === 0 || shown.length < cmd.length) {
      ctx.fillStyle = rgba(COL.cyan, 0.9);
      ctx.fillRect(170 + cw + 3, y + 22, 14, 30);
    }
    const da = P(t, T.h5[0] + 1.05, T.h5[0] + 1.3, E.outCubic);
    ctx.globalAlpha = ca * da;
    text(ctx, '✓  report.html  ·  one file, no server', 136, y + 116, font(500, 21, MONO), '#aef5da');
    ctx.globalAlpha = 1;
  }
}

// ------------------------------------------------------------------ 07: title

function drawTitle(ctx, t) {
  if (t < T.title) return;
  const s = t - T.title;
  // Two beams cross into an X, and the name comes out of the flash.
  const cross = P(s, 0.0, 0.34, E.inOutCubic);
  if (s < 0.6) {
    ctx.save();
    ctx.globalCompositeOperation = 'lighter';
    const fade = 1 - P(s, 0.3, 0.6);
    for (const dir of [1, -1]) {
      ctx.save();
      ctx.translate(W / 2, H / 2);
      ctx.rotate(dir * 0.52);
      const x = lerp(-W * 0.9 * dir, 0, cross) * (1 - P(s, 0.34, 0.6)) + 0;
      const len = W * 1.4;
      const g = ctx.createLinearGradient(0, -30, 0, 30);
      g.addColorStop(0, rgba(COL.cyan, 0));
      g.addColorStop(0.5, rgba('#ffffff', 0.9 * fade));
      g.addColorStop(1, rgba(COL.cyan, 0));
      ctx.fillStyle = g;
      ctx.fillRect(x - len / 2, -30, len, 60);
      ctx.restore();
    }
    const flash = Math.exp(-Math.max(0, s - 0.3) * 7) * P(s, 0.25, 0.32);
    ctx.globalAlpha = flash;
    ctx.drawImage(GLOW_ICE, W / 2 - 700, H / 2 - 700, 1400, 1400);
    ctx.restore();
  }
  // Soft light behind the name.
  const la = P(s, 0.28, 0.9, E.outCubic);
  ctx.globalAlpha = la * 0.5;
  ctx.globalCompositeOperation = 'lighter';
  ctx.drawImage(GLOW[2], W / 2 - 900, H / 2 - 520, 1800, 900);
  ctx.globalCompositeOperation = 'source-over';
  ctx.globalAlpha = 1;

  const parts = [['Odoo', COL.ink], ['Process', COL.ink], ['X-Ray', null]];
  const f = font(800, 152);
  const space = 36;
  const widths = parts.map(([w]) => measure(ctx, w, f));
  let x = W / 2 - (widths.reduce((a, b) => a + b, 0) + space * 2) / 2;
  const y = 548;
  let k = 0;
  ctx.save();
  ctx.beginPath();
  ctx.rect(0, y - 170, W, 215);
  ctx.clip();
  parts.forEach(([word, color], i) => {
    let lx = x;
    for (const ch of word) {
      const a = T.title + 0.3 + k * 0.024;
      const p = E.outExpo(prog(t, a, a + 0.7));
      const cw = measure(ctx, ch, f);
      ctx.globalAlpha = clamp(p * 1.4);
      const yy = y + (1 - p) * 180;
      if (color) {
        text(ctx, ch, lx, yy, f, color);
      } else {
        const g = ctx.createLinearGradient(0, y - 120, 0, y);
        g.addColorStop(0, COL.ice);
        g.addColorStop(1, COL.cyan);
        ctx.shadowColor = rgba(COL.cyan, 0.8);
        ctx.shadowBlur = 50;
        text(ctx, ch, lx, yy, f, g);
        ctx.shadowBlur = 0;
      }
      lx += cw;
      k++;
    }
    x += widths[i] + space;
  });
  ctx.restore();

  // An x-ray line runs down the name and shows its outline.
  const sl = P(s, 0.95, 1.55, E.inOutSine);
  if (sl > 0 && sl < 1) {
    const ly = lerp(y - 150, y + 40, sl);
    ctx.save();
    ctx.globalCompositeOperation = 'lighter';
    const g = ctx.createLinearGradient(0, ly - 30, 0, ly + 30);
    g.addColorStop(0, rgba(COL.cyan, 0));
    g.addColorStop(0.5, rgba(COL.cyan, 0.5 * Math.sin(Math.PI * sl)));
    g.addColorStop(1, rgba(COL.cyan, 0));
    ctx.fillStyle = g;
    ctx.fillRect(W * 0.1, ly - 30, W * 0.8, 60);
    ctx.restore();
  }

  const sa = P(s, 0.62, 1.0, E.outCubic);
  ctx.globalAlpha = sa;
  text(ctx, 'Process mining for Odoo 17 · 18 · 19', W / 2, 640 + (1 - sa) * 16, font(500, 34, MONO), COL.muted, 'center', 1);
  const ua = P(s, 0.85, 1.25, E.outCubic);
  const chips = ['reads the chatter', 'finds the pattern', 'names the fix'];
  const cf = font(600, 22);
  const cws = chips.map((c) => measure(ctx, c, cf) + 44);
  let chx = W / 2 - (cws.reduce((a, b) => a + b, 0) + 16 * (chips.length - 1)) / 2;
  chips.forEach((c, i) => {
    const a = P(s, 0.9 + i * 0.08, 1.2 + i * 0.08, E.outCubic);
    ctx.globalAlpha = a;
    const cy = 700 + (1 - a) * 14;
    ctx.beginPath();
    ctx.roundRect(chx, cy, cws[i], 46, 23);
    ctx.fillStyle = 'rgba(92,225,255,0.07)';
    ctx.fill();
    ctx.strokeStyle = rgba(COL.cyan, 0.4);
    ctx.lineWidth = 1.5;
    ctx.stroke();
    text(ctx, c, chx + cws[i] / 2, cy + 30, cf, COL.ice, 'center');
    chx += cws[i] + 16;
  });
  ctx.globalAlpha = ua * 0.9;
  text(ctx, 'github.com/mateuszkrw-coder/odoo-process-xray', W / 2, 826, font(500, 22, MONO), COL.dim, 'center', 1);
  ctx.globalAlpha = 1;
}

// ------------------------------------------------------------------ HUD

function drawHUD(ctx, t) {
  const a = P(t, 0.15, 0.6) * (1 - P(t, 14.6, 14.9));
  if (a <= 0) return;
  ctx.save();
  ctx.globalAlpha = a;
  ctx.strokeStyle = 'rgba(170,195,255,0.4)';
  ctx.lineWidth = 2;
  const m = 44, s = 26 * P(t, 0.15, 0.7, E.outCubic);
  for (const [x, y, dx, dy] of [[m, m, 1, 1], [W - m, m, -1, 1], [m, H - m, 1, -1], [W - m, H - m, -1, -1]]) {
    ctx.beginPath();
    ctx.moveTo(x, y + dy * s);
    ctx.lineTo(x, y);
    ctx.lineTo(x + dx * s, y);
    ctx.stroke();
  }
  ctx.globalAlpha = a * 0.55;
  text(ctx, 'ODOO PROCESS X-RAY', m + 36, m + 22, font(600, 15, MONO), COL.muted, 'left', 3);
  let scene = SCENES[0];
  for (const sc of SCENES) if (TF >= sc[0]) scene = sc;
  const sp = P(TF, scene[0], scene[0] + 0.45);
  if (scene[1] !== '07') text(ctx, `${scene[1]} — ${scramble(scene[2], sp, scene[0] * 10)}`, W - m - 36, m + 22, font(600, 15, MONO), COL.muted, 'right', 3);
  const f = Math.round(TF * 60);
  const tc = `00:00:${String(Math.floor(f / 60)).padStart(2, '0')}:${String(f % 60).padStart(2, '0')}`;
  text(ctx, tc, m + 36, H - m - 10, font(500, 15, MONO), COL.muted, 'left', 2);
  text(ctx, 'DEMO DATA · BEANLINE TRADING (FICTIONAL)', W - m - 36, H - m - 10, font(500, 15, MONO), COL.muted, 'right', 2);
  ctx.restore();
}

// ------------------------------------------------------------------ frame

function drawScene(ctx, t, frameTime = t) {
  TF = frameTime;
  ctx.setTransform(1, 0, 0, 1, 0, 0);
  ctx.globalAlpha = 1;
  ctx.globalCompositeOperation = 'source-over';
  const grid = P(t, T.pull[1] - 0.4, T.pull[1] + 0.4) * (1 - 0.6 * P(t, T.title, T.title + 0.5));
  drawBackground(ctx, t, grid);
  drawWall(ctx, t);
  drawBeam(ctx, t);

  // Keep the headline readable over the wall.
  const shade = P(t, 0.05, 0.5) * (1 - P(t, T.h2[1], T.h2[1] + 0.4));
  if (shade > 0) {
    const g = ctx.createLinearGradient(0, 0, 1250, 0);
    g.addColorStop(0, `rgba(3,5,11,${0.9 * shade})`);
    g.addColorStop(0.55, `rgba(3,5,11,${0.6 * shade})`);
    g.addColorStop(1, 'rgba(3,5,11,0)');
    ctx.fillStyle = g;
    ctx.fillRect(0, 0, 1250, H);
  }

  drawReveal(ctx, t);
  const cam = mapCam(t);
  drawChartLabels(ctx, t);
  if (t < T.report) drawMap(ctx, t);
  drawDots(ctx, t, cam);
  drawCards(ctx, t);
  drawReport(ctx, t);
  if (t >= T.report) drawMap(ctx, t);
  drawTitle(ctx, t);
  for (const h of HEADLINES) drawHeadline(ctx, h, t);
  drawHUD(ctx, t);

  // In from black, out to black: the loop point.
  const black = 1 - P(t, 0, 0.3) + P(t, 14.7, 15.0);
  if (black > 0) {
    ctx.fillStyle = `rgba(0,0,0,${clamp(black)})`;
    ctx.fillRect(0, 0, W, H);
  }
}

// Lens and grain settings for the post-processing pass, over time.
function effects(t) {
  const scan = Math.sin(Math.PI * prog(t, T.scan[0], T.scan[1] + 0.1));
  const flash = t >= T.title + 0.28 ? Math.exp(-(t - T.title - 0.28) * 11) : 0;
  const pull = Math.sin(Math.PI * prog(t, T.pull[0], T.pull[1]));
  return {
    bloom: 0.36 + 0.35 * flash, threshold: 0.66, knee: 0.4, radius: 1.0,
    aberration: 2.5 + 7 * scan + 4 * pull + 14 * flash,
    // No grain, and the same dither pattern on every frame: nothing changes where
    // nothing moves, so the video and the animated WebP stay small.
    vignette: 0.62, grain: 0, exposure: 1.0, flash: 0.035 * flash, seed: 1,
  };
}

// When things happen, for the sound track (make_audio.py).
function cues() {
  const words = HEADLINES.flatMap((h) => h.lines.flat().map((_, k) => h.t[0] + k * 0.055));
  const cmd = 'python -m xray run';
  return {
    T, words,
    nodes: Object.values(NODES).map((n) => ({ t: n.t0, main: n.main, act: n.act })).sort((a, b) => a.t - b.t),
    edges: EDGES.map((e) => e.t0).sort((a, b) => a - b),
    typing: [...cmd].map((_, i) => T.h5[0] + 0.45 + (0.5 * (i + 0.5)) / cmd.length),
    tiles: [0, 1, 2, 3].map((i) => T.report + 0.5 + i * 0.06),
    check: T.report + 1.3,
    letters: [...'OdooProcessX-Ray'].map((_, k) => T.title + 0.3 + k * 0.024),
  };
}

window.Showreel = { W, H, DURATION, drawScene, effects, cues };
})();
