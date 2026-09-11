// Generates simple app icons (PWA + favicon) with zero external image tools —
// hand-built PNG encoder using only Node's built-in zlib, since this sandbox has
// no ImageMagick/Sharp/Cairo available. Draws a flat pint-glass glyph on a
// rounded, deep-green field.
import { deflateSync } from 'node:zlib';
import { writeFileSync, mkdirSync } from 'node:fs';
import path from 'node:path';

const BG = [15, 81, 50]; // #0f5132 deep pub green
const FG = [250, 247, 242]; // #faf7f2 cream foam/glass colour
const AMBER = [217, 119, 6]; // accent for the "beer" fill

function crc32(buf) {
  let c;
  const table = crc32.table || (crc32.table = (() => {
    const t = new Uint32Array(256);
    for (let n = 0; n < 256; n++) {
      c = n;
      for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
      t[n] = c >>> 0;
    }
    return t;
  })());
  let crc = 0xffffffff;
  for (let i = 0; i < buf.length; i++) crc = table[(crc ^ buf[i]) & 0xff] ^ (crc >>> 8);
  return (crc ^ 0xffffffff) >>> 0;
}

function chunk(type, data) {
  const len = Buffer.alloc(4);
  len.writeUInt32BE(data.length, 0);
  const typeBuf = Buffer.from(type, 'ascii');
  const crcBuf = Buffer.alloc(4);
  crcBuf.writeUInt32BE(crc32(Buffer.concat([typeBuf, data])), 0);
  return Buffer.concat([len, typeBuf, data, crcBuf]);
}

function makePng(size, pixelFn) {
  const width = size, height = size;
  const raw = Buffer.alloc((width * 4 + 1) * height);
  let offset = 0;
  for (let y = 0; y < height; y++) {
    raw[offset++] = 0; // filter type: none
    for (let x = 0; x < width; x++) {
      const [r, g, b, a] = pixelFn(x, y, width, height);
      raw[offset++] = r;
      raw[offset++] = g;
      raw[offset++] = b;
      raw[offset++] = a;
    }
  }
  const sig = Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]);
  const ihdr = Buffer.alloc(13);
  ihdr.writeUInt32BE(width, 0);
  ihdr.writeUInt32BE(height, 4);
  ihdr[8] = 8; // bit depth
  ihdr[9] = 6; // color type RGBA
  ihdr[10] = 0;
  ihdr[11] = 0;
  ihdr[12] = 0;
  const idat = deflateSync(raw, { level: 9 });
  return Buffer.concat([sig, chunk('IHDR', ihdr), chunk('IDAT', idat), chunk('IEND', Buffer.alloc(0))]);
}

function roundedMask(x, y, w, h, radius) {
  const nearCornerX = x < radius ? radius : x > w - radius ? w - radius : x;
  const nearCornerY = y < radius ? radius : y > h - radius ? h - radius : y;
  if ((x < radius || x > w - radius) && (y < radius || y > h - radius)) {
    const dx = x - nearCornerX, dy = y - nearCornerY;
    return dx * dx + dy * dy <= radius * radius;
  }
  return true;
}

function pintGlassGlyph(x, y, w, h) {
  // Normalised coords 0..1
  const nx = x / w, ny = y / h;
  // Glass body: a trapezoid narrower at bottom, wider at top, centred.
  const top = 0.28, bottom = 0.78;
  if (ny < top || ny > bottom) return false;
  const t = (ny - top) / (bottom - top); // 0 at top .. 1 at bottom
  const halfWidthTop = 0.19, halfWidthBottom = 0.15;
  const halfWidth = halfWidthBottom + (halfWidthTop - halfWidthBottom) * (1 - t);
  const cx = 0.5;
  return nx > cx - halfWidth && nx < cx + halfWidth;
}

function foamGlyph(x, y, w, h) {
  const nx = x / w, ny = y / h;
  const top = 0.22, bottom = 0.30;
  if (ny < top || ny > bottom) return false;
  const halfWidth = 0.205;
  return nx > 0.5 - halfWidth && nx < 0.5 + halfWidth;
}

function makeIcon(size) {
  return makePng(size, (x, y, w, h) => {
    const radius = Math.round(size * 0.22);
    if (!roundedMask(x, y, w, h, radius)) return [0, 0, 0, 0];
    if (foamGlyph(x, y, w, h)) return [...FG, 255];
    if (pintGlassGlyph(x, y, w, h)) return [...AMBER, 235];
    return [...BG, 255];
  });
}

const outDirs = [
  path.join(process.cwd(), 'public', 'icons'),
];
for (const d of outDirs) mkdirSync(d, { recursive: true });

writeFileSync(path.join(process.cwd(), 'public', 'icons', 'icon-192.png'), makeIcon(192));
writeFileSync(path.join(process.cwd(), 'public', 'icons', 'icon-512.png'), makeIcon(512));
writeFileSync(path.join(process.cwd(), 'public', 'apple-touch-icon.png'), makeIcon(180));

const favSvg = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">
  <rect width="100" height="100" rx="22" fill="rgb(${BG.join(',')})"/>
  <rect x="30.5" y="22" width="39" height="8" rx="4" fill="rgb(${FG.join(',')})"/>
  <path d="M34 30 L66 30 L61 76 Q50 82 39 76 Z" fill="rgb(${AMBER.join(',')})"/>
</svg>`;
writeFileSync(path.join(process.cwd(), 'public', 'favicon.svg'), favSvg);

console.log('Icons generated.');
