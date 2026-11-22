// After `vite build`: a `.br` and a `.gz` next to each text file of dist/, which the gateway serves
// to a browser that accepts them (a third of the bytes over a phone's network). Written only when
// smaller; none for images already compressed.
import { brotliCompressSync, constants, gzipSync } from "node:zlib";
import { readdirSync, readFileSync, statSync, writeFileSync } from "node:fs";
import { join } from "node:path";

const TEXT = /\.(js|css|html|svg|webmanifest|json)$/;

function* files(dir: string): Generator<string> {
  for (const name of readdirSync(dir)) {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) yield* files(path);
    else if (TEXT.test(name)) yield path;
  }
}

const dist = new URL("../dist", import.meta.url).pathname;
let before = 0;
let after = 0;
for (const path of files(dist)) {
  const raw = readFileSync(path);
  const br = brotliCompressSync(raw, { params: { [constants.BROTLI_PARAM_QUALITY]: 11 } });
  const gz = gzipSync(raw, { level: 9 });
  if (br.length < raw.length) writeFileSync(`${path}.br`, br);
  if (gz.length < raw.length) writeFileSync(`${path}.gz`, gz);
  before += raw.length;
  after += Math.min(raw.length, br.length);
}
console.log(`precompressed dist/: ${Math.round(before / 1024)} KiB → ${Math.round(after / 1024)} KiB (brotli)`);
