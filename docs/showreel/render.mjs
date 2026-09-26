// Render the showreel to the files used in the README.
//
//   node docs/showreel/render.mjs             full quality: 1080p60, 8 sub-frames of motion blur per frame
//   node docs/showreel/render.mjs --sub 1     quick draft, no motion blur
//
// Needs Node 18+, Playwright (npm i -D playwright, or NODE_PATH pointing at a global
// install) and ffmpeg built with libx264 and libsvtav1.
//
// Headless Chromium draws the frames, a few pages in parallel. WebGL runs on
// SwiftShader, so the pixels don't depend on the graphics card. Raw frames come back
// over a WebSocket and go to ffmpeg in order as a lossless master; the MP4, the
// animated AVIF and the poster are cut from it. The sound track is synthesised by
// make_audio.py (Python with numpy) from the animation's cue times.

import { spawn, spawnSync } from 'node:child_process';
import crypto from 'node:crypto';
import fs from 'node:fs';
import http from 'node:http';
import { createRequire } from 'node:module';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
const docs = path.dirname(here);
const opts = {};
process.argv.slice(2).forEach((a, i, all) => {
  if (a.startsWith('--')) opts[a.slice(2)] = all[i + 1] && !all[i + 1].startsWith('--') ? all[i + 1] : true;
});
const W = 1920, H = 1080, DURATION = 15;
const FPS = Number(opts.fps || 60);
const SUB = Number(opts.sub || 8);
const JOBS = Number(opts.jobs || 3);
const FIRST = Math.round(Number(opts.from || 0) * FPS);           // --from/--to (seconds): render part of it
const LAST = Math.round(Number(opts.to || DURATION) * FPS);
const work = path.resolve(opts.work || path.join(here, 'build'));
const master = path.join(work, 'master.mkv');
fs.mkdirSync(work, { recursive: true });

function run(cmd, args) {
  const r = spawnSync(cmd, args, { stdio: 'inherit' });
  if (r.status !== 0) throw new Error(`${cmd} failed`);
}
const size = (file) => `${(fs.statSync(file).size / 1e6).toFixed(1)} MB`;

// Just enough of a WebSocket server to receive binary messages and send a one-byte ack.
function acceptWebSocket(req, socket, onMessage) {
  const key = crypto.createHash('sha1').update(`${req.headers['sec-websocket-key']}258EAFA5-E914-47DA-95CA-C5AB0DC85B11`);
  socket.write('HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n'
    + `Sec-WebSocket-Accept: ${key.digest('base64')}\r\n\r\n`);
  socket.setNoDelay(true);
  let buf = Buffer.alloc(0), parts = [];
  socket.on('data', (chunk) => {
    buf = buf.length ? Buffer.concat([buf, chunk]) : chunk;
    for (;;) {
      if (buf.length < 2) return;
      let len = buf[1] & 0x7f, off = 2;
      if (len === 126) { if (buf.length < 4) return; len = buf.readUInt16BE(2); off = 4; }
      if (len === 127) { if (buf.length < 10) return; len = Number(buf.readBigUInt64BE(2)); off = 10; }
      if (buf.length < off + 4 + len) return;
      const fin = buf[0] & 0x80, op = buf[0] & 0x0f;
      const mask = buf.readUInt32LE(off);
      const data = Buffer.from(buf.subarray(off + 4, off + 4 + len));
      const words = len >> 2;
      for (let i = 0; i < words; i++) data.writeUInt32LE((data.readUInt32LE(i * 4) ^ mask) >>> 0, i * 4);
      for (let i = words * 4; i < len; i++) data[i] ^= buf[off + (i & 3)];
      buf = buf.subarray(off + 4 + len);
      if (op === 8) { socket.end(); return; }
      parts.push(data);
      if (fin) {
        onMessage(Buffer.concat(parts), () => socket.write(Buffer.from([0x82, 1, 1])));
        parts = [];
      }
    }
  });
}

async function render() {
  const { chromium } = createRequire(import.meta.url)('playwright');
  const ffmpeg = spawn('ffmpeg', ['-y', '-loglevel', 'error', '-f', 'rawvideo', '-pix_fmt', 'rgba', '-s', `${W}x${H}`,
    '-framerate', String(FPS), '-i', '-', '-vf', 'vflip', '-c:v', 'ffv1', '-level', '3', '-slices', '16',
    '-pix_fmt', 'gbrp', master], { stdio: ['pipe', 'inherit', 'inherit'] });
  const done = new Promise((resolve, reject) => ffmpeg.on('close', (c) => (c === 0 ? resolve() : reject(new Error('ffmpeg failed')))));

  // Frames arrive from several pages out of order; write them to ffmpeg in order.
  const waiting = new Map();
  let next = FIRST;
  const start = Date.now();
  function flush() {
    while (waiting.has(next)) {
      const { pixels, ack } = waiting.get(next);
      waiting.delete(next);
      if (ffmpeg.stdin.write(pixels)) ack();
      else ffmpeg.stdin.once('drain', ack);
      next++;
      const done = next - FIRST, total = LAST - FIRST;
      if (done % 30 === 0 || done === total) {
        const s = (Date.now() - start) / 1000;
        process.stdout.write(`\rframe ${done}/${total}  ${s.toFixed(0)} s, about ${((s / done) * (total - done)).toFixed(0)} s to go   `);
      }
    }
  }

  const types = { '.html': 'text/html', '.js': 'text/javascript', '.css': 'text/css', '.woff2': 'font/woff2' };
  const server = http.createServer((req, res) => {
    const file = path.join(here, decodeURIComponent(new URL(req.url, 'http://localhost').pathname));
    fs.readFile(file, (err, data) => {
      if (err || !file.startsWith(here)) { res.writeHead(404); res.end(); return; }
      res.writeHead(200, { 'content-type': types[path.extname(file)] || 'application/octet-stream' });
      res.end(data);
    });
  });
  server.on('upgrade', (req, socket) => acceptWebSocket(req, socket, (msg, ack) => {
    waiting.set(msg.readUInt32LE(0), { pixels: msg.subarray(4), ack });
    flush();
  }));
  await new Promise((r) => server.listen(0, '127.0.0.1', r));
  const port = server.address().port;

  // Software 2D canvas: Skia's CPU rasteriser is far faster than Skia on SwiftShader.
  const browser = await chromium.launch({
    args: ['--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist', '--disable-accelerated-2d-canvas'],
  });
  await Promise.all(Array.from({ length: JOBS }, async (_, job) => {
    const page = await browser.newPage({ viewport: { width: W, height: H } });
    page.on('pageerror', (e) => { console.error(e); process.exit(1); });
    await page.goto(`http://127.0.0.1:${port}/index.html?render&fps=${FPS}&sub=${SUB}`);
    await page.waitForFunction(() => window.ready === true, null, { timeout: 60000 });
    if (job === 0) fs.writeFileSync(path.join(work, 'cues.json'), JSON.stringify(await page.evaluate(() => window.Showreel.cues())));
    await page.evaluate((port) => new Promise((resolve) => {
      const ws = new WebSocket(`ws://127.0.0.1:${port}/`);
      ws.binaryType = 'arraybuffer';
      const acks = [];
      ws.onmessage = () => acks.shift()();
      window.sendFrame = (n) => {
        const gl = document.getElementById('out').getContext('webgl2');
        const msg = window.frameBuffer || (window.frameBuffer = new Uint8Array(4 + gl.drawingBufferWidth * gl.drawingBufferHeight * 4));
        new DataView(msg.buffer).setUint32(0, n, true);
        gl.readPixels(0, 0, gl.drawingBufferWidth, gl.drawingBufferHeight, gl.RGBA, gl.UNSIGNED_BYTE, msg.subarray(4));
        return new Promise((ok) => { acks.push(ok); ws.send(msg); });
      };
      ws.onopen = resolve;
    }), port);
    for (let n = FIRST + job; n < LAST; n += JOBS) {
      await page.evaluate(async (n) => { window.renderFrame(n); await window.sendFrame(n); }, n);
    }
  }));
  console.log();
  await browser.close();
  server.close();
  ffmpeg.stdin.end();
  await done;
}

function encode() {
  const mp4 = path.join(docs, 'showreel.mp4');
  const avif = path.join(docs, 'showreel.avif');
  const poster = path.join(docs, 'showreel.png');
  const cues = path.join(work, 'cues.json');
  const audio = path.join(work, 'audio.wav');
  let sound = false;
  if (!opts['no-audio'] && fs.existsSync(cues)) {
    sound = spawnSync(opts.python || 'python3', [path.join(here, 'make_audio.py'), cues, audio], { stdio: 'inherit' }).status === 0;
    if (!sound) console.log('No sound track (make_audio.py needs Python with numpy); the MP4 will be silent.');
  }
  // H.264 for sharing: plays everywhere, BT.709 tagged so the colours match the page.
  run('ffmpeg', ['-y', '-loglevel', 'error', '-i', master, ...(sound ? ['-i', audio] : []),
    '-vf', 'scale=out_color_matrix=bt709:out_range=tv:flags=lanczos+accurate_rnd+full_chroma_int,format=yuv420p',
    '-c:v', 'libx264', '-preset', 'veryslow', '-crf', String(opts.crf || 18), '-profile:v', 'high', '-level', '4.2',
    '-colorspace', 'bt709', '-color_primaries', 'bt709', '-color_trc', 'bt709', '-color_range', 'tv',
    ...(sound ? ['-c:a', 'aac', '-b:a', '192k'] : []), '-movflags', '+faststart', mp4]);
  // Animated AVIF for the README: it autoplays and loops like a GIF, where a video would
  // not, and AV1 keeps the whole piece to a few megabytes.
  run('ffmpeg', ['-y', '-loglevel', 'error', '-i', master,
    '-vf', `fps=${opts['avif-fps'] || 30},scale=${opts['avif-width'] || 1280}:-2:flags=lanczos:out_color_matrix=bt709:out_range=tv,format=yuv420p`,
    '-c:v', 'libsvtav1', '-preset', '4', '-crf', String(opts['avif-crf'] || 32), '-g', '450', '-svtav1-params', 'tune=0',
    '-colorspace', 'bt709', '-color_primaries', 'bt709', '-color_trc', 'bt709', '-color_range', 'tv', avif]);
  // Still frame: the title card.
  run('ffmpeg', ['-y', '-loglevel', 'error', '-ss', '14.4', '-i', master, '-frames:v', '1',
    '-vf', 'scale=1280:-1:flags=lanczos', poster]);
  for (const f of [mp4, avif, poster]) console.log(`${path.relative(process.cwd(), f)}  ${size(f)}`);
}

if (!opts['encode-only']) await render();
if (!opts['render-only']) encode();
