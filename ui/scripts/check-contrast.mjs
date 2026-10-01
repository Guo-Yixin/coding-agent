#!/usr/bin/env node
// 对比度检查：把 tokens.css 里真实用到的「前景 × 背景」组合量一遍 WCAG 对比度。
//
//   node scripts/check-contrast.mjs           人类可读表格；有不合格项则 exit 1
//   node scripts/check-contrast.mjs --json    机器可读
//
// 为什么需要它：对比度是「看着够不够灰」这种主观判断最容易搞错的地方。
// token 文件里躺着几个 3.2:1 的浅灰文字，肉眼完全看不出来 —— 只有算一遍才知道。
import fs from 'node:fs';
import path from 'node:path';

const TOKENS = process.argv.includes('--json') ? null : path.resolve('src/styles/tokens.css');
const FILE = TOKENS || path.resolve('src/styles/tokens.css');
const MIN_TEXT = 4.5;   // WCAG AA 正文
const MIN_LARGE = 3.0;  // WCAG AA 大字 / 非文本（边框、图标）

function parseTokens(file) {
  const src = fs.readFileSync(file, 'utf8');
  const out = new Map();
  // 只看未被注释掉的声明：先把注释整段挖掉
  const bare = src.replace(/\/\*[\s\S]*?\*\//g, '');
  for (const m of bare.matchAll(/(--[a-z0-9-]+)\s*:\s*([^;]+);/gi)) {
    const v = m[2].trim();
    if (/^#[0-9a-f]{3,8}$/i.test(v)) out.set(m[1], v);
  }
  return out;
}

function lum(hex) {
  let h = hex.replace('#', '');
  if (h.length === 3) h = h.split('').map((c) => c + c).join('');
  const ch = [0, 2, 4].map((i) => parseInt(h.slice(i, i + 2), 16) / 255);
  const lin = ch.map((c) => (c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4));
  return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2];
}

function ratio(fg, bg) {
  const a = lum(fg), b = lum(bg);
  const [hi, lo] = a > b ? [a, b] : [b, a];
  return (hi + 0.05) / (lo + 0.05);
}

// 真实存在的组合：前景 token → 它会落在哪些背景 token 上
const PAIRS = [
  ['--c-text', ['--c-bg', '--c-bg-subtle', '--c-surface', '--c-surface-hover', '--c-accent-subtle', '--c-success-subtle', '--c-warning-subtle', '--c-danger-subtle']],
  ['--c-text-secondary', ['--c-bg', '--c-bg-subtle', '--c-surface', '--c-surface-hover', '--c-accent-subtle', '--c-success-subtle', '--c-warning-subtle', '--c-danger-subtle']],
  ['--c-text-muted', ['--c-bg', '--c-bg-subtle', '--c-surface', '--c-surface-hover']],
  ['--c-text-inverse', ['--c-accent', '--c-accent-hover', '--c-accent-active', '--c-success', '--c-warning', '--c-danger', '--c-text']],
  ['--c-accent', ['--c-bg', '--c-bg-subtle', '--c-surface', '--c-accent-subtle']],
  ['--c-success', ['--c-bg', '--c-surface', '--c-success-subtle']],
  ['--c-warning', ['--c-bg', '--c-surface', '--c-warning-subtle']],
  ['--c-danger', ['--c-bg', '--c-surface', '--c-danger-subtle']],
];

const T = parseTokens(FILE);
const rows = [];
const fails = [];
const missing = new Set();

for (const [fgName, bgs] of PAIRS) {
  const fg = T.get(fgName);
  if (!fg) { missing.add(fgName); continue; }
  for (const bgName of bgs) {
    const bg = T.get(bgName);
    if (!bg) { missing.add(bgName); continue; }
    const r = ratio(fg, bg);
    const ok = r >= MIN_TEXT;
    rows.push({ fg: fgName, bg: bgName, ratio: Math.round(r * 100) / 100, ok });
    if (!ok) fails.push(`${fgName} (${fg}) on ${bgName} (${bg}) = ${r.toFixed(2)}:1  < ${MIN_TEXT}`);
  }
}

if (missing.size) {
  console.error('❌ tokens.css 缺少以下 token（检查清单已过期）：' + [...missing].join(', '));
  process.exit(1);
}

if (process.argv.includes('--json')) {
  console.log(JSON.stringify({ min: MIN_TEXT, rows, fails }, null, 2));
} else {
  const w = Math.max(...rows.map((r) => r.fg.length));
  let lastFg = '';
  for (const r of rows) {
    if (r.fg !== lastFg) { console.log(`\n${r.fg}`); lastFg = r.fg; }
    console.log(`  ${r.ok ? '✅' : '❌'} ${r.ratio.toFixed(2).padStart(5)}:1  on ${r.bg}`);
  }
  console.log(`\n共 ${rows.length} 组，${fails.length} 组不达标（门槛 ${MIN_TEXT}:1）`);
  for (const f of fails) console.log('  ❌ ' + f);
}

process.exit(fails.length ? 1 : 0);
