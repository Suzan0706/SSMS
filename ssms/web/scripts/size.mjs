// Fails when the built JS + CSS exceed the gzip budget (master prompt: < 200 KB gzipped).
import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { gzipSync } from "node:zlib";

const BUDGET = 200 * 1024;
const dir = "dist/assets";
let total = 0;
for (const name of readdirSync(dir).filter((f) => /\.(js|css)$/.test(f))) {
  const size = gzipSync(readFileSync(join(dir, name))).length;
  total += size;
  console.log(`${name.padEnd(40)} ${(size / 1024).toFixed(1)} KB gz`);
}
console.log(`TOTAL ${(total / 1024).toFixed(1)} KB gz (budget ${BUDGET / 1024} KB)`);
if (total > BUDGET) process.exit(1);
