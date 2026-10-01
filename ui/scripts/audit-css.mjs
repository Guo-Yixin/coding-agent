#!/usr/bin/env node
/**
 * audit-css.mjs —— CSS「设计系统漂移」审计记分卡（零依赖 · Node 18+ · 跨平台）
 *
 * 用途
 *   扫一个前端项目（或单个 CSS 文件），统计颜色 / 圆角 / 字号 / 变量 / 选择器 /
 *   !important 的散乱程度，输出一张 ✅ / ❌ 记分卡，判断设计系统是否已经漂移。
 *
 * 用法
 *   node audit-css.mjs <css文件或目录> [--json] [--quiet] [--help]
 *
 * 选项
 *   --json     输出机器可读 JSON（含全部原始数据 + pass/fail），无装饰字符
 *   --quiet    只输出最后一行总结
 *   -h, --help 显示本帮助
 *
 * 输入
 *   - 目录：递归收集所有 .css，以及所有 .vue（只取 <style ...>…</style> 块参与分析）
 *   - 文件：直接分析（.vue 同样只取 style 块）
 *   - 跳过目录：node_modules / dist / build / .git / coverage / vendor
 *
 * 指标
 *   1. :root 块数量；CSS 变量重复声明（最后一个生效，其余标为死代码）
 *   2. 十六进制颜色 distinct + 频次 Top15 + 近重复聚类（RGB 欧氏距离 < 12）
 *   3. rgb()/rgba() distinct + 基色（忽略 alpha）distinct + 基色近重复聚类
 *   4. border-radius 取值列表 + distinct
 *   5. font-size 取值列表 + distinct + 频次分布（clamp() 整体视作一个值）
 *   6. 同一选择器分散在多块（> 1 次）数量 + Top15（提示项，不参与判定）
 *   7. token 覆盖率 = var(--x) 次数 /（var 次数 + 硬编码颜色数 + 硬编码间距/字号/圆角 px 数）
 *   8. !important 数量
 *   9. 规则块总数 / distinct 选择器数
 *
 * 评分（任一 FAIL → 进程退出码 1）
 *   彩色 distinct ≤ 5 · border-radius distinct ≤ 4 · font-size distinct ≤ 7
 *   近白背景 distinct ≤ 3 · :root 块 = 1 · token 覆盖率 ≥ 90%
 *   rgb/rgba 基色 distinct ≤ 3 · 冗余声明（同属性重复声明）= 0 · !important = 0
 *
 * 提示项（不参与判定，不影响退出码）
 *   同一选择器分散在多块 —— 归零必须合并块，而合并会把声明搬到文件更靠后处，
 *   改变它与其它同特异性选择器的先后关系，有渲染风险，因此只提示不判定
 *
 * 退出码
 *   0 全部通过 · 1 有未通过项 / 参数或输入错误
 */

import fs from 'node:fs';
import path from 'node:path';

// ───────────────────────────── 常量与阈值 ─────────────────────────────

const SKIP_DIRS = new Set(['node_modules', 'dist', 'build', '.git', 'coverage', 'vendor']);
const NEAR_DUP_DISTANCE = 12; // RGB 欧氏距离阈值：小于它视为「近重复颜色」
const NEAR_WHITE_MIN = 245; // 三通道全部 > 245 视为「近白」
const NEUTRAL_SAT = 0.12; // HSL 饱和度 < 12% 视为中性色
const NEUTRAL_CHROMA = 6; // 彩度（max-min）≤ 6 视为「彩度接近 0」→ 中性色
const VALUE_PREVIEW = 12; // 记分卡值列表最多展示几个
const DETAIL_PREVIEW = 24; // 详情行最多展示几个
const TOP_N = 15; // Top 列表长度
const MAX_LISTED_PX = 24; // JSON 里 px 明细最多列几个

// 评分阈值（改这里即可调整严格度）
// 注意 duplicateSelectors 与 redundantDeclarations 是两件事：
//   redundantDeclarations —— 同一 (上下文, 选择器) 下同一个属性被声明了不止一次。
//     后一条必然覆盖前一条，删掉前一条不改变任何渲染。这是真正的漂移症状，硬门 = 0。
//   duplicateSelectors（提示，不参与判定）—— 同一选择器分散在多个规则块里，但各块声明的属性互不重叠。
//     它不是冗余：要归零就得把多个块合并，而合并会把声明搬到文件更靠后的位置，
//     从而改变它与其它同特异性选择器之间的先后关系 —— 那是有渲染风险的，不能当作硬门。
const LIMITS = {
  coloredDistinct: 5,
  radiusDistinct: 4,
  fontSizeDistinct: 7,
  nearWhiteDistinct: 3,
  rootBlocks: 1,
  tokenCoverage: 90,
  rgbBaseDistinct: 3,
  redundantDeclarations: 0,
  duplicateSelectors: 0,
  importantCount: 0,
};

// ───────────────────────────── 基础文本工具 ─────────────────────────────

/** 跳过一段字符串字面量，返回结束引号之后的偏移 */
function skipString(src, i) {
  const n = src.length;
  const quote = src[i];
  i++;
  while (i < n) {
    const c = src[i];
    if (c === '\\') {
      i += 2;
      continue;
    }
    if (c === quote) return i + 1;
    i++;
  }
  return i;
}

/** 跳过一对配对的括号，返回右括号之后的偏移 */
function skipBalanced(src, i, open, close) {
  const n = src.length;
  let depth = 0;
  while (i < n) {
    const c = src[i];
    if (c === '"' || c === "'") {
      i = skipString(src, i);
      continue;
    }
    if (c === open) depth++;
    else if (c === close) {
      depth--;
      if (depth === 0) return i + 1;
    }
    i++;
  }
  return i;
}

/**
 * 剥离 /* … *\/ 注释，但保持字符串长度不变（注释字符换成空格、换行保留），
 * 这样后续所有偏移量都能一对一映射回原文件，行号才不会错位。
 * 注意：只剥离注释、不动声明，所以 :root 里的变量声明不会丢。
 */
function stripComments(src) {
  const out = src.split('');
  const n = src.length;
  let i = 0;
  while (i < n) {
    const c = src[i];
    if (c === '"' || c === "'") {
      i = skipString(src, i);
      continue;
    }
    if (c === '/' && src[i + 1] === '*') {
      const end = src.indexOf('*/', i + 2);
      const stop = end === -1 ? n : end + 2;
      for (let k = i; k < stop; k++) {
        if (out[k] !== '\n' && out[k] !== '\r') out[k] = ' ';
      }
      i = stop;
      continue;
    }
    i++;
  }
  return out.join('');
}

/**
 * .vue：把 <style> 之外的字符全部涂成空格（保留换行），
 * 于是 .vue 也能用同一套解析器，且行号与 .vue 文件一致。
 */
function maskVue(raw) {
  const out = raw.split('');
  const keep = new Array(raw.length).fill(false);
  const notes = [];
  const re = /<style\b([^>]*)>([\s\S]*?)<\/style\s*>/gi;
  let m;
  while ((m = re.exec(raw))) {
    const attrs = m[1] || '';
    const lower = m[0].toLowerCase();
    const openEnd = lower.indexOf('>');
    const closeStart = lower.lastIndexOf('</style');
    if (openEnd < 0 || closeStart < 0) continue;
    const contentStart = m.index + openEnd + 1;
    const contentEnd = m.index + closeStart;
    for (let k = contentStart; k < contentEnd; k++) keep[k] = true;
    const lang = (attrs.match(/\blang\s*=\s*["']?([\w-]+)/i) || [])[1];
    if (lang && /^(scss|sass|less|styl|stylus)$/i.test(lang)) notes.push(lang.toLowerCase());
  }
  for (let i = 0; i < raw.length; i++) {
    if (keep[i]) continue;
    const c = raw[i];
    out[i] = c === '\n' || c === '\r' ? c : ' ';
  }
  return { src: out.join(''), notes };
}

/** 把块内嵌套的 { … } 子规则涂成空格（保留长度与换行），只留顶层声明 */
function maskNestedBlocks(body) {
  const out = body.split('');
  const n = body.length;
  let i = 0;
  while (i < n) {
    const c = body[i];
    if (c === '"' || c === "'") {
      i = skipString(body, i);
      continue;
    }
    if (c === '(') {
      i = skipBalanced(body, i, '(', ')');
      continue;
    }
    if (c === '{') {
      const end = skipBalanced(body, i, '{', '}');
      for (let k = i; k < end; k++) {
        if (out[k] !== '\n' && out[k] !== '\r') out[k] = ' ';
      }
      i = end;
      continue;
    }
    i++;
  }
  return out.join('');
}

/** 把 var( … ) 整体涂成空格（保留长度）：token 覆盖率里不把回退值当硬编码 */
function maskVarCalls(value) {
  const out = value.split('');
  const re = /\bvar\s*\(/g;
  let m;
  while ((m = re.exec(value))) {
    const open = m.index + m[0].length - 1;
    const end = skipBalanced(value, open, '(', ')');
    for (let k = m.index; k < end; k++) out[k] = ' ';
    re.lastIndex = end;
  }
  return out.join('');
}

// ───────────────────────────── CSS 解析 ─────────────────────────────

// 会「包住其它规则」的条件型 at-rule：递归进去继续找规则
const CONDITIONAL_AT = /^@(media|supports|layer|container|scope|starting-style|document|-moz-document)\b/i;
// 带声明体、但不是选择器的 at-rule（声明照收，但不计入选择器统计）
const DECL_AT = /^@(font-face|page|property|counter-style|viewport|font-feature-values)\b/i;

/**
 * 极简但健壮的 CSS 规则扫描器。
 * 返回 [{ selector, bodyStart, bodyEnd, atRule }]，bodyStart/bodyEnd 为声明体在源码中的偏移。
 * 支持：压缩写法、多空格、注释（已剥离）、@media 嵌套、@keyframes 内层步骤、CSS 嵌套。
 */
function parseRules(src) {
  const rules = [];
  const n = src.length;

  function readBody(openIdx) {
    const after = skipBalanced(src, openIdx, '{', '}'); // '}' 之后
    const closed = src[after - 1] === '}';
    return { bodyStart: openIdx + 1, bodyEnd: closed ? after - 1 : after, end: after };
  }

  function walk(start, expectBrace, mode, context = '') {
    let buf = '';
    let i = start;
    while (i < n) {
      const c = src[i];
      if (c === '"' || c === "'") {
        const j = skipString(src, i);
        buf += src.slice(i, j);
        i = j;
        continue;
      }
      if (c === '(') {
        const j = skipBalanced(src, i, '(', ')');
        buf += src.slice(i, j);
        i = j;
        continue;
      }
      if (c === ';') {
        i++;
        buf = '';
        continue;
      }
      if (c === '}') {
        i++;
        if (expectBrace) return i;
        continue;
      }
      if (c === '{') {
        const prelude = buf.trim();
        const body = readBody(i);
        if (prelude.startsWith('@')) {
          if (/^@keyframes\b/i.test(prelude)) {
            // 关键帧：内层 0%/from/to 的声明照收，但不作为「选择器」计数
            walk(body.bodyStart, true, 'keyframes', context);
          } else if (CONDITIONAL_AT.test(prelude)) {
            // 条件 at-rule：把 prelude 压进上下文，供「重复选择器」按媒体条件分组
            walk(body.bodyStart, true, mode, context ? `${context} && ${prelude}` : prelude);
          } else {
            // @font-face / @page 等：带声明体，收声明但不算选择器
            rules.push({ selector: prelude, ...body, atRule: true, context });
          }
          i = body.end;
        } else if (mode === 'keyframes') {
          rules.push({ selector: prelude, ...body, atRule: true, context });
          i = body.end;
        } else {
          rules.push({ selector: prelude, ...body, atRule: false, context });
          i = body.end;
        }
        buf = '';
        continue;
      }
      buf += c;
      i++;
    }
    return i;
  }

  walk(0, false, 'normal');
  return rules;
}

/** 把声明体切成 [{ start, text }]（识别字符串与括号，忽略其中的分号） */
function splitDeclParts(text) {
  const parts = [];
  const n = text.length;
  let i = 0;
  let bufStart = 0;
  while (i < n) {
    const c = text[i];
    if (c === '"' || c === "'") {
      i = skipString(text, i);
      continue;
    }
    if (c === '(') {
      i = skipBalanced(text, i, '(', ')');
      continue;
    }
    if (c === ';') {
      parts.push({ start: bufStart, text: text.slice(bufStart, i) });
      i++;
      bufStart = i;
      continue;
    }
    i++;
  }
  if (bufStart < n) parts.push({ start: bufStart, text: text.slice(bufStart, n) });
  return parts.filter((p) => p.text.trim().length > 0);
}

const PROP_RE = /^(--[\w-]+|-?[a-zA-Z][\w-]*)$/;

/** 逗号分割选择器组（跳过 :is()/:not() 的括号、属性选择器里的逗号与字符串） */
function splitSelectorList(selector) {
  const out = [];
  const n = selector.length;
  let i = 0;
  let buf = '';
  while (i < n) {
    const c = selector[i];
    if (c === '"' || c === "'") {
      const j = skipString(selector, i);
      buf += selector.slice(i, j);
      i = j;
      continue;
    }
    if (c === '(' || c === '[') {
      const close = c === '(' ? ')' : ']';
      const j = skipBalanced(selector, i, c, close);
      buf += selector.slice(i, j);
      i = j;
      continue;
    }
    if (c === ',') {
      out.push(buf);
      buf = '';
      i++;
      continue;
    }
    buf += c;
    i++;
  }
  out.push(buf);
  return out.map((s) => s.replace(/\s+/g, ' ').trim()).filter(Boolean);
}

// ───────────────────────────── 颜色工具 ─────────────────────────────

function rgbToHsl(r, g, b) {
  const R = r / 255;
  const G = g / 255;
  const B = b / 255;
  const max = Math.max(R, G, B);
  const min = Math.min(R, G, B);
  const d = max - min;
  const l = (max + min) / 2;
  let h = 0;
  let s = 0;
  if (d !== 0) {
    s = l > 0.5 ? d / (2 - max - min) : d / (max + min);
    if (max === R) h = (G - B) / d + (G < B ? 6 : 0);
    else if (max === G) h = (B - R) / d + 2;
    else h = (R - G) / d + 4;
    h *= 60;
  }
  return { h, s, l };
}

function isNearWhite(r, g, b) {
  return r > NEAR_WHITE_MIN && g > NEAR_WHITE_MIN && b > NEAR_WHITE_MIN;
}

/** 中性色判定：HSL 饱和度 < 12% 或彩度（max-min）接近 0 */
function isNeutral(r, g, b) {
  const { s } = rgbToHsl(r, g, b);
  const chroma = Math.max(r, g, b) - Math.min(r, g, b);
  return s < NEUTRAL_SAT || chroma <= NEUTRAL_CHROMA;
}

function rgbDistance(a, b) {
  return Math.sqrt((a.r - b.r) ** 2 + (a.g - b.g) ** 2 + (a.b - b.b) ** 2);
}

/** 给近重复聚类起个中文色名，例如「7 个几乎一样的绿色」 */
function hueName(r, g, b) {
  const { h, s, l } = rgbToHsl(r, g, b);
  if (l <= 0.12) return '近黑';
  if (l >= 0.94) return '近白';
  if (s < NEUTRAL_SAT) return '灰';
  if (h < 15 || h >= 345) return '红';
  if (h < 45) return '橙';
  if (h < 70) return '黄';
  if (h < 165) return '绿';
  if (h < 195) return '青';
  if (h < 255) return '蓝';
  if (h < 290) return '紫';
  return '品红';
}

const HEX_RE = /#([0-9a-fA-F]{8}|[0-9a-fA-F]{6}|[0-9a-fA-F]{4}|[0-9a-fA-F]{3})(?![0-9a-fA-F])/g;
const RGB_FN_RE = /\brgba?\s*\(([^()]*)\)/gi;

/** 先抹掉 url(...)（SVG 片段 id 常常形如 #abc，会被误认成颜色） */
function maskUrls(value) {
  return value.replace(/\burl\s*\((?:[^()]|\([^()]*\))*\)/gi, (m) => ' '.repeat(m.length));
}

function canonHex(r, g, b, a) {
  const base = [r, g, b].map((x) => x.toString(16).padStart(2, '0')).join('');
  return '#' + base + (a < 255 ? a.toString(16).padStart(2, '0') : '');
}

/** 扫描一段值里的十六进制颜色 */
function scanHex(value) {
  const out = [];
  HEX_RE.lastIndex = 0;
  let m;
  while ((m = HEX_RE.exec(value))) {
    const h = m[1].toLowerCase();
    let r, g, b, a;
    if (h.length === 3 || h.length === 4) {
      r = parseInt(h[0] + h[0], 16);
      g = parseInt(h[1] + h[1], 16);
      b = parseInt(h[2] + h[2], 16);
      a = h.length === 4 ? parseInt(h[3] + h[3], 16) : 255;
    } else {
      r = parseInt(h.slice(0, 2), 16);
      g = parseInt(h.slice(2, 4), 16);
      b = parseInt(h.slice(4, 6), 16);
      a = h.length === 8 ? parseInt(h.slice(6, 8), 16) : 255;
    }
    out.push({ raw: '#' + h, canon: canonHex(r, g, b, a), r, g, b, a });
  }
  return out;
}

function parseRgbChannel(token) {
  const t = String(token).trim();
  if (!t) return null;
  if (t.endsWith('%')) {
    const v = Number.parseFloat(t);
    return Number.isFinite(v) ? Math.max(0, Math.min(255, Math.round((v * 255) / 100))) : null;
  }
  const v = Number.parseFloat(t);
  if (!Number.isFinite(v)) return null;
  return Math.max(0, Math.min(255, Math.round(v)));
}

function parseAlpha(token) {
  if (token == null || token === '') return 1;
  const t = String(token).trim();
  if (t.endsWith('%')) {
    const v = Number.parseFloat(t);
    return Number.isFinite(v) ? Math.max(0, Math.min(1, v / 100)) : 1;
  }
  const v = Number.parseFloat(t);
  return Number.isFinite(v) ? Math.max(0, Math.min(1, v)) : 1;
}

/**
 * 解析 rgb()/rgba() 参数，同时支持现代与逗号写法：
 *   rgba(1,2,3,0.5) / rgb(1 2 3 / 50%) / rgb(100% 0% 0%) / rgb(1, 2, 3)
 */
function parseRgbArgs(argsStr) {
  let body = String(argsStr).trim();
  let slashAlpha = null;
  const slash = body.indexOf('/');
  if (slash >= 0) {
    slashAlpha = body.slice(slash + 1).trim();
    body = body.slice(0, slash);
  }
  let parts = body.includes(',') ? body.split(',') : body.trim().split(/\s+/);
  parts = parts.map((s) => s.trim()).filter(Boolean);
  if (parts.length < 3) return null;
  const rgb = [parseRgbChannel(parts[0]), parseRgbChannel(parts[1]), parseRgbChannel(parts[2])];
  if (rgb.some((v) => v === null)) return null; // 相对颜色语法等 → 跳过
  const alphaToken = slashAlpha != null ? slashAlpha : parts.length >= 4 ? parts[3] : null;
  return { r: rgb[0], g: rgb[1], b: rgb[2], a: parseAlpha(alphaToken) };
}

/** 扫描一段值里的 rgb()/rgba() */
function scanRgb(value) {
  const out = [];
  RGB_FN_RE.lastIndex = 0;
  let m;
  while ((m = RGB_FN_RE.exec(value))) {
    const parsed = parseRgbArgs(m[1]);
    if (!parsed) continue;
    const a = Math.round(parsed.a * 1000) / 1000;
    out.push({
      raw: m[0].replace(/\s+/g, ' '),
      canon: `rgba(${parsed.r},${parsed.g},${parsed.b},${a})`,
      r: parsed.r,
      g: parsed.g,
      b: parsed.b,
      a,
    });
  }
  return out;
}

// ───────────────────────────── 文件收集 ─────────────────────────────

/** 递归收集 .css / .vue；跳过 SKIP_DIRS */
function collectFiles(target) {
  const found = [];
  const stack = [target];
  while (stack.length) {
    const cur = stack.pop();
    let st;
    try {
      st = fs.statSync(cur);
    } catch {
      continue;
    }
    if (st.isDirectory()) {
      let entries = [];
      try {
        entries = fs.readdirSync(cur, { withFileTypes: true });
      } catch {
        continue;
      }
      for (const e of entries) {
        const full = path.join(cur, e.name);
        if (e.isDirectory()) {
          if (SKIP_DIRS.has(e.name)) continue;
          stack.push(full);
        } else if (e.isFile()) {
          const ext = path.extname(e.name).toLowerCase();
          if (ext === '.css' || ext === '.vue') found.push(full);
        }
      }
    } else if (st.isFile()) {
      const ext = path.extname(cur).toLowerCase();
      if (ext === '.css' || ext === '.vue') found.push(cur);
    }
  }
  found.sort();
  return found;
}

/** 按路径片段过滤（--ignore）。用于排除 tokens 定义文件这类"字面量本来就合法"的文件。 */
function filterIgnored(files, patterns) {
  if (!patterns || patterns.length === 0) return files;
  const norm = (s) => String(s).split(path.sep).join('/');
  const pats = patterns.map(norm);
  return files.filter((f) => {
    const n = norm(f);
    return !pats.some((p) => n.includes(p));
  });
}

// ───────────────────────────── 单文件分析 ─────────────────────────────

function lineIndex(text) {
  const starts = [0];
  for (let i = 0; i < text.length; i++) {
    if (text[i] === '\n') starts.push(i + 1);
  }
  return (offset) => {
    let lo = 0;
    let hi = starts.length - 1;
    while (lo < hi) {
      const mid = (lo + hi + 1) >> 1;
      if (starts[mid] <= offset) lo = mid;
      else hi = mid - 1;
    }
    return lo + 1;
  };
}

/**
 * 分析单个文件，返回 { file, lines, rules, decls, selectors, notes }
 * decls: { prop, value, important, line }
 */
function analyzeFile(file) {
  const raw = fs.readFileSync(file, 'utf8');
  const isVue = path.extname(file).toLowerCase() === '.vue';
  const notes = [];
  let src = raw;
  if (isVue) {
    const masked = maskVue(raw);
    src = masked.src;
    for (const n of masked.notes) notes.push(`<style lang="${n}">：嵌套语法可能抬高「重复选择器」计数`);
  }
  const clean = stripComments(src);
  const rules = parseRules(clean);
  const lineOf = lineIndex(raw);

  const decls = [];
  const selectors = [];

  for (const rule of rules) {
    const body = clean.slice(rule.bodyStart, rule.bodyEnd);
    const masked = maskNestedBlocks(body);
    for (const part of splitDeclParts(masked)) {
      const text = part.text;
      const colon = text.indexOf(':');
      if (colon < 0) continue;
      const prop = text.slice(0, colon).trim().toLowerCase();
      if (!PROP_RE.test(prop)) continue;
      let value = text.slice(colon + 1).trim();
      if (!value) continue;
      const importantCount = (value.match(/!\s*important/gi) || []).length;
      if (importantCount > 0) value = value.replace(/!\s*important/gi, '').trim();
      const absOffset = rule.bodyStart + part.start + colon + 1;
      decls.push({
        prop,
        value,
        important: importantCount,
        line: lineOf(absOffset),
        file,
        selector: rule.selector || '',
        context: rule.context || '',
        // atRule 的声明体（@keyframes 的 0%/from/to 步骤、@font-face、@page）不是层叠里的选择器：
        // 两个 @keyframes 各有一个 to { transform } 是完全正常的，互相不覆盖。
        // 冗余声明检查必须跳过它们，否则「再加一个动画」就会被误报。
        atRule: !!rule.atRule,
      });
    }
    if (!rule.atRule && rule.selector) {
      // 带上 at-rule 上下文：同一个选择器在 base 与 @media 里各写一次是合法的响应式覆盖，
      // 只有「同一上下文内被声明多次」才算重复。
      for (const sel of splitSelectorList(rule.selector)) {
        selectors.push({ sel, context: rule.context || '' });
      }
    }
  }

  return {
    file,
    // 行数按编辑器口径统计（忽略文件末尾换行带来的空行）
    lines: raw.replace(/\r\n?/g, '\n').replace(/\n$/, '').split('\n').length,
    rules,
    decls,
    selectors,
    notes,
  };
}

// ───────────────────────────── 指标聚合 ─────────────────────────────

function bump(map, key, init) {
  const cur = map.get(key);
  if (cur) cur.count++;
  else map.set(key, { ...init, count: 1 });
  return map.get(key);
}

function topByCount(map, n) {
  return [...map.entries()]
    .map(([value, v]) => ({ value, count: v.count }))
    .sort((a, b) => b.count - a.count || String(a.value).localeCompare(String(b.value)))
    .slice(0, n);
}

function cmpCssValue(a, b) {
  const na = Number.parseFloat(a);
  const nb = Number.parseFloat(b);
  const fa = Number.isFinite(na);
  const fb = Number.isFinite(nb);
  if (fa && fb) {
    if (na !== nb) return na - nb;
    return a.localeCompare(b);
  }
  if (fa !== fb) return fa ? -1 : 1;
  return a.localeCompare(b);
}

/** 把距离 < 阈值 的颜色聚成组（并查式 BFS），返回成员数 > 1 的组 */
function clusterColors(items) {
  const used = new Array(items.length).fill(false);
  const clusters = [];
  for (let i = 0; i < items.length; i++) {
    if (used[i]) continue;
    used[i] = true;
    const group = [i];
    const queue = [i];
    while (queue.length) {
      const a = queue.shift();
      for (let j = 0; j < items.length; j++) {
        if (used[j]) continue;
        if (rgbDistance(items[a], items[j]) < NEAR_DUP_DISTANCE) {
          used[j] = true;
          group.push(j);
          queue.push(j);
        }
      }
    }
    if (group.length > 1) clusters.push(group.map((k) => items[k]));
  }
  return clusters.sort((a, b) => b.length - a.length);
}

const SPACING_PROP_RE = /^(padding|margin|gap|grid-gap)(-.+)?$/;
const RADIUS_LONGHAND_RE = /^border-.+-radius$/;

function stripVendor(prop) {
  return prop.replace(/^-[a-z]+-/, '');
}

/** 间距 / 字号 / 圆角这类「本该 token 化」的属性 */
function isTokenizableLengthProp(prop) {
  const p = stripVendor(prop);
  if (p === 'font-size' || p === 'border-radius') return true;
  if (SPACING_PROP_RE.test(p)) return true;
  if (RADIUS_LONGHAND_RE.test(p)) return true;
  return false;
}

const PX_RE = /-?\d*\.?\d+px\b/gi;

function computeMetrics(docs, files) {
  const hexMap = new Map(); // canon → {count, rgb}
  const rgbMap = new Map(); // rgba(...) → {count, rgb}
  const rgbBaseMap = new Map(); // r,g,b → {count, rgb}
  const radiusMap = new Map();
  const fontSizeMap = new Map();
  const selectorMap = new Map();
  const rootFiles = new Set();
  const varDecls = []; // {name, value, file, line}
  const hardPx = [];

  let ruleBlocks = 0;
  let rootBlockCount = 0;
  let importantCount = 0;
  let hardColorCount = 0;
  let varUseCount = 0;

  for (const doc of docs) {
    for (const rule of doc.rules) {
      if (!rule.atRule && rule.selector) {
        ruleBlocks++;
        if (splitSelectorList(rule.selector).some((s) => s === ':root' || s.endsWith(':root'))) {
          rootBlockCount++; // 按块计数（同一文件里两个 :root 就是 2）
          rootFiles.add(doc.file);
        }
      }
    }

    for (const { sel, context } of doc.selectors) {
      const key = context ? `${context}\u0000${sel}` : sel;
      bump(selectorMap, key, { value: sel, context: context || '(base)' });
    }

    for (const d of doc.decls) {
      importantCount += d.important;

      // :root 变量（任意作用域的 --x 声明都收，用于找重复声明）
      if (d.prop.startsWith('--')) {
        varDecls.push({ name: d.prop, value: d.value, file: d.file, line: d.line });
      }

      // 颜色（含 var() 回退值，反映「文件里出现了多少种颜色」）
      const colorZone = maskUrls(d.value);
      for (const c of scanHex(colorZone)) {
        const cur = bump(hexMap, c.canon, { rgb: { r: c.r, g: c.g, b: c.b } });
        if (!cur.rgb) cur.rgb = { r: c.r, g: c.g, b: c.b };
      }
      for (const c of scanRgb(colorZone)) {
        bump(rgbMap, c.canon, { rgb: { r: c.r, g: c.g, b: c.b } });
        bump(rgbBaseMap, `${c.r},${c.g},${c.b}`, { rgb: { r: c.r, g: c.g, b: c.b } });
      }

      // border-radius / font-size 取值
      if (stripVendor(d.prop) === 'border-radius') {
        bump(radiusMap, d.value.replace(/\s+/g, ' '), {});
      }
      if (stripVendor(d.prop) === 'font-size') {
        bump(fontSizeMap, d.value.replace(/\s+/g, ' '), {});
      }

      // token 覆盖率：var() 用量 + 硬编码颜色 + 硬编码长度 px
      const varZone = maskUrls(d.value);
      varUseCount += (varZone.match(/\bvar\s*\(/g) || []).length;
      const hardZone = maskVarCalls(varZone); // 去掉 var(...) 回退值后的「真·硬编码」区
      hardColorCount += scanHex(hardZone).length + scanRgb(hardZone).length;
      if (isTokenizableLengthProp(d.prop)) {
        const pxs = hardZone.match(PX_RE) || [];
        for (const px of pxs) {
          hardPx.push({ prop: d.prop, value: px, file: d.file, line: d.line });
        }
      }
    }
  }

  // 变量重复声明：同名按文档顺序，最后一个生效，其余为死代码
  const varByName = new Map();
  for (const v of varDecls) {
    if (!varByName.has(v.name)) varByName.set(v.name, []);
    varByName.get(v.name).push(v);
  }
  const duplicateVars = [];
  for (const [name, list] of varByName) {
    if (list.length > 1) {
      duplicateVars.push({
        name,
        declarations: list,
        winner: list[list.length - 1],
        dead: list.slice(0, -1),
      });
    }
  }
  duplicateVars.sort((a, b) => b.declarations.length - a.declarations.length || a.name.localeCompare(b.name));

  // 近白 / 彩色（hex 与 rgb 基色合并去重）
  const baseColors = new Map();
  for (const [canon, v] of hexMap) {
    const key = `${v.rgb.r},${v.rgb.g},${v.rgb.b}`;
    if (!baseColors.has(key)) baseColors.set(key, { ...v.rgb, displays: new Set(), count: 0 });
    const b = baseColors.get(key);
    b.displays.add(canon);
    b.count += v.count;
  }
  for (const [key, v] of rgbBaseMap) {
    if (!baseColors.has(key)) baseColors.set(key, { ...v.rgb, displays: new Set(), count: 0 });
    const b = baseColors.get(key);
    b.count += v.count;
  }
  const colorList = [...baseColors.values()].map((c) => ({
    ...c,
    label: [...c.displays][0] || `rgb(${c.r},${c.g},${c.b})`,
  }));
  const nearWhite = colorList.filter((c) => isNearWhite(c.r, c.g, c.b));
  const colored = colorList.filter((c) => !isNearWhite(c.r, c.g, c.b) && !isNeutral(c.r, c.g, c.b));
  const nearWhiteSet = new Set(nearWhite.map((c) => `${c.r},${c.g},${c.b}`));

  const hexClusters = clusterColors(
    [...hexMap.entries()].map(([canon, v]) => ({ label: canon, ...v.rgb })),
  );
  const rgbBaseClusters = clusterColors(
    [...rgbBaseMap.entries()].map(([key, v]) => ({
      label: `rgb(${key.split(',').join(', ')})`,
      ...v.rgb,
    })),
  );

  // 重复声明的选择器
  const duplicateList = [...selectorMap.values()]
    .filter((v) => v.count > 1)
    .map((v) => ({ value: v.value, count: v.count, context: v.context }))
    .sort((a, b) => b.count - a.count || a.value.localeCompare(b.value));

  // 被同 (上下文, 选择器) 更靠后的声明覆盖掉的属性声明 —— 真正的冗余。
  // 一条声明只有在「同一上下文、同一选择器下，后面还声明了同一个属性」时才必然无效：
  // 同选择器 ⇒ 同特异性，后出现者胜。
  // 注意选择器列表：`.a, .b { color:red }` 后面接 `.a { color:blue }` 时，
  // color:red 对 .a 已失效、对 .b 仍然有效 —— 删掉它会改变 .b 的颜色。
  // 所以只统计「列表中每个选择器都被覆盖」的声明，那才是可以安全删除的集合。
  const declById = new Map(); // id → {prop, context, selectors}
  const lastFor = new Map(); // `${context}\0${sel}\0${prop}` → 最后一次声明它的 id
  let seqId = 0;
  for (const doc of docs) {
    for (const d of doc.decls) {
      if (!d.selector || d.atRule) continue;
      const sels = splitSelectorList(d.selector);
      if (!sels.length) continue;
      const id = seqId++;
      declById.set(id, { prop: d.prop, context: d.context, selectors: sels });
      for (const sel of sels) lastFor.set(`${d.context}\u0000${sel}\u0000${d.prop}`, id);
    }
  }
  let redundantDeclarations = 0;
  for (const [id, info] of declById) {
    const covered = info.selectors.every(
      (sel) => lastFor.get(`${info.context}\u0000${sel}\u0000${info.prop}`) !== id,
    );
    if (covered) redundantDeclarations++;
  }

  const denom = varUseCount + hardColorCount + hardPx.length;
  const tokenCoverage = denom === 0 ? 100 : (varUseCount / denom) * 100;

  const radiusValues = [...radiusMap.entries()].map(([value, v]) => ({ value, count: v.count }));
  const fontSizeValues = [...fontSizeMap.entries()].map(([value, v]) => ({ value, count: v.count }));

  return {
    fileCount: files.length,
    lines: docs.reduce((s, d) => s + d.lines, 0),
    ruleBlocks,
    distinctSelectors: selectorMap.size,
    totalSelectorUses: docs.reduce((s, d) => s + d.selectors.length, 0),
    redundantDeclarations,
    rootBlocks: rootBlockCount,
    rootFiles: [...rootFiles],
    variables: {
      total: varByName.size,
      declarations: varDecls.length,
      duplicates: duplicateVars,
    },
    hexColors: {
      distinct: hexMap.size,
      occurrences: [...hexMap.values()].reduce((s, v) => s + v.count, 0),
      top: topByCount(hexMap, TOP_N),
      nearDuplicates: hexClusters,
    },
    rgbColors: {
      distinct: rgbMap.size,
      occurrences: [...rgbMap.values()].reduce((s, v) => s + v.count, 0),
      baseDistinct: rgbBaseMap.size,
      top: topByCount(rgbMap, TOP_N),
      baseNearDuplicates: rgbBaseClusters,
    },
    coloredDistinct: colored.length,
    colored: colored.map((c) => c.label).sort(),
    nearWhiteDistinct: nearWhite.length,
    nearWhite: nearWhite.map((c) => c.label).sort(),
    nearWhiteSet,
    borderRadius: { distinct: radiusValues.length, values: radiusValues },
    fontSize: { distinct: fontSizeValues.length, values: fontSizeValues },
    selectors: {
      duplicateCount: duplicateList.length,
      duplicateUses: duplicateList.reduce((s, d) => s + d.count, 0),
      list: duplicateList,
      top: duplicateList.slice(0, TOP_N),
    },
    tokenCoverage: {
      percent: Math.round(tokenCoverage * 10) / 10,
      varUses: varUseCount,
      hardcodedColors: hardColorCount,
      hardcodedPx: hardPx.length,
      pxSamples: hardPx.slice(0, MAX_LISTED_PX),
    },
    importantCount,
    notes: [...new Set(docs.flatMap((d) => d.notes))],
  };
}

// ───────────────────────────── 评分 ─────────────────────────────

function buildChecks(m) {
  const previewList = (arr, n = VALUE_PREVIEW) => {
    if (arr.length <= n) return arr.join(',');
    return arr.slice(0, n).join(',') + `…(+${arr.length - n})`;
  };
  const radiusSorted = [...m.borderRadius.values].map((v) => v.value).sort(cmpCssValue);
  const fontSizeSorted = [...m.fontSize.values].map((v) => v.value).sort(cmpCssValue);
  const dupPreview = m.selectors.top.map((d) => `${d.value}×${d.count}`);

  return [
    {
      id: 'coloredDistinct',
      label: '彩色 distinct',
      value: m.coloredDistinct,
      valueText: `distinct=${m.coloredDistinct}`,
      need: `≤${LIMITS.coloredDistinct}`,
      needText: `(需 ≤${LIMITS.coloredDistinct})`,
      pass: m.coloredDistinct <= LIMITS.coloredDistinct,
      extra: previewList(m.colored),
    },
    {
      id: 'radiusDistinct',
      label: 'border-radius',
      value: m.borderRadius.distinct,
      valueText: `distinct=${m.borderRadius.distinct}`,
      need: `≤${LIMITS.radiusDistinct}`,
      needText: `(需 ≤${LIMITS.radiusDistinct})`,
      pass: m.borderRadius.distinct <= LIMITS.radiusDistinct,
      extra: previewList(radiusSorted),
    },
    {
      id: 'fontSizeDistinct',
      label: 'font-size',
      value: m.fontSize.distinct,
      valueText: `distinct=${m.fontSize.distinct}`,
      need: `≤${LIMITS.fontSizeDistinct}`,
      needText: `(需 ≤${LIMITS.fontSizeDistinct})`,
      pass: m.fontSize.distinct <= LIMITS.fontSizeDistinct,
      extra: previewList(fontSizeSorted),
    },
    {
      id: 'nearWhiteDistinct',
      label: '近白背景 distinct',
      value: m.nearWhiteDistinct,
      valueText: `distinct=${m.nearWhiteDistinct}`,
      need: `≤${LIMITS.nearWhiteDistinct}`,
      needText: `(需 ≤${LIMITS.nearWhiteDistinct})`,
      pass: m.nearWhiteDistinct <= LIMITS.nearWhiteDistinct,
      extra: previewList(m.nearWhite),
    },
    {
      id: 'rootBlocks',
      label: ':root 块',
      value: m.rootBlocks,
      valueText: `count=${m.rootBlocks}`,
      need: `=${LIMITS.rootBlocks}`,
      needText: `(需 =${LIMITS.rootBlocks})`,
      pass: m.rootBlocks === LIMITS.rootBlocks,
      extra: m.rootFiles.join(','),
    },
    {
      id: 'tokenCoverage',
      label: 'token 覆盖率',
      value: m.tokenCoverage.percent,
      valueText: `${m.tokenCoverage.percent.toFixed(1)}%`,
      need: `≥${LIMITS.tokenCoverage}%`,
      needText: `(需 ≥${LIMITS.tokenCoverage}%)`,
      pass: m.tokenCoverage.percent >= LIMITS.tokenCoverage,
      extra: `var()=${m.tokenCoverage.varUses} 硬编码色=${m.tokenCoverage.hardcodedColors} 硬编码px=${m.tokenCoverage.hardcodedPx}`,
    },
    {
      id: 'rgbBaseDistinct',
      label: 'rgb/rgba 基色 distinct',
      value: m.rgbColors.baseDistinct,
      valueText: `distinct=${m.rgbColors.baseDistinct}`,
      need: `≤${LIMITS.rgbBaseDistinct}`,
      needText: `(需 ≤${LIMITS.rgbBaseDistinct})`,
      pass: m.rgbColors.baseDistinct <= LIMITS.rgbBaseDistinct,
      extra: previewList(m.rgbColors.top.map((t) => t.value)),
    },
    {
      id: 'redundantDeclarations',
      label: '冗余声明（同属性重复声明）',
      value: m.redundantDeclarations,
      valueText: `count=${m.redundantDeclarations}`,
      need: `=${LIMITS.redundantDeclarations}`,
      needText: `(需 =${LIMITS.redundantDeclarations})`,
      pass: m.redundantDeclarations === LIMITS.redundantDeclarations,
      extra: '',
    },
    {
      id: 'duplicateSelectors',
      label: '同一选择器分散在多块',
      value: m.selectors.duplicateCount,
      valueText: `count=${m.selectors.duplicateCount}`,
      need: '提示',
      needText: '（提示，不参与判定）',
      pass: m.selectors.duplicateCount === LIMITS.duplicateSelectors,
      advisory: true,
      extra: previewList(dupPreview),
    },
    {
      id: 'importantCount',
      label: '!important',
      value: m.importantCount,
      valueText: `count=${m.importantCount}`,
      need: `=${LIMITS.importantCount}`,
      needText: `(需 =${LIMITS.importantCount})`,
      pass: m.importantCount === LIMITS.importantCount,
      extra: '',
    },
  ];
}

// ───────────────────────────── 输出 ─────────────────────────────

/** 中文按 2 列宽计算，保证终端对齐 */
function displayWidth(s) {
  let w = 0;
  for (const ch of s) {
    w += /[\u1100-\u115F\u2E80-\uA4CF\uAC00-\uD7A3\uF900-\uFAFF\uFE30-\uFE4F\uFF00-\uFF60\uFFE0-\uFFE6]/.test(ch)
      ? 2
      : 1;
  }
  return w;
}

function padDisplay(s, width) {
  return s + ' '.repeat(Math.max(0, width - displayWidth(s)));
}

function summaryLine(checks) {
  const failed = checks.filter((c) => !c.pass && !c.advisory);
  if (failed.length === 0) return '全部通过 — 设计系统一致';
  return `合计 ${failed.length} 项未通过 — 设计系统已漂移`;
}

function renderScorecard(target, m, checks) {
  const labelW = Math.max(...checks.map((c) => displayWidth(c.label)));
  const valueW = Math.max(...checks.map((c) => displayWidth(c.valueText)));
  const out = [];

  out.push('CSS 设计系统漂移审计');
  out.push(`目标  ${target}`);
  out.push(
    `范围  ${m.fileCount} 个文件 · ${m.lines} 行 · 规则块 ${m.ruleBlocks} · distinct 选择器 ${m.distinctSelectors}`,
  );
  out.push('─'.repeat(64));
  out.push('[评分]');
  for (const c of checks) {
    const mark = c.advisory ? 'ℹ️' : c.pass ? '✅' : '❌';
    const base = `${mark} ${padDisplay(c.label, labelW)}  ${padDisplay(c.valueText, valueW)}  ${c.needText}`;
    out.push(c.extra ? `${base}   ${c.extra}` : base);
  }

  out.push('[详情]');

  // :root / 变量
  const dupVars = m.variables.duplicates;
  if (dupVars.length === 0) {
    out.push(
      `:root 块 ×${m.rootBlocks} · CSS 变量 ${m.variables.total} 个 / 声明 ${m.variables.declarations} 次（无重复声明）`,
    );
  } else {
    out.push(
      `:root 块 ×${m.rootBlocks} · CSS 变量 ${m.variables.total} 个 / 声明 ${m.variables.declarations} 次 · 重复声明 ${dupVars.length} 个`,
    );
    for (const v of dupVars.slice(0, 8)) {
      const winner = `${v.winner.value} (${path.basename(v.winner.file)}:${v.winner.line})`;
      const dead = v.dead.map((d) => `${d.value} (${path.basename(d.file)}:${d.line})`).join(' | ');
      out.push(`  ❌ ${v.name}  声明 ${v.declarations.length} 次 → 生效 ${winner} · 死代码 ${dead}`);
    }
    if (dupVars.length > 8) out.push(`  …(+${dupVars.length - 8} 个重复变量)`);
    out.push('  （同名字段按文档顺序取最后一个生效；跨作用域覆盖不适用此规则）');
  }

  // hex
  if (m.hexColors.distinct > 0) {
    const top = m.hexColors.top.map((t) => `${t.count}×${t.value}`).join(' · ');
    out.push(
      `hex 颜色 distinct=${m.hexColors.distinct} / ${m.hexColors.occurrences} 次 — Top${Math.min(TOP_N, m.hexColors.top.length)}: ${top}`,
    );
  } else {
    out.push('hex 颜色 distinct=0');
  }

  // 近重复聚类
  const clusters = [...m.hexColors.nearDuplicates, ...m.rgbColors.baseNearDuplicates];
  if (clusters.length === 0) {
    out.push(`近重复颜色聚类（RGB 距离 < ${NEAR_DUP_DISTANCE}）: 无`);
  } else {
    out.push(`近重复颜色聚类（RGB 距离 < ${NEAR_DUP_DISTANCE}）${clusters.length} 组:`);
    for (const g of clusters.slice(0, 8)) {
      const name = hueName(g[0].r, g[0].g, g[0].b);
      const list = g.map((c) => c.label).join(' · ');
      out.push(`  [${name}] ${list}  (${g.length} 个)`);
    }
    if (clusters.length > 8) out.push(`  …(+${clusters.length - 8} 组)`);
  }

  // rgb
  if (m.rgbColors.distinct > 0) {
    const top = m.rgbColors.top.map((t) => `${t.count}×${t.value}`).join(' · ');
    out.push(
      `rgb/rgba distinct=${m.rgbColors.distinct} / ${m.rgbColors.occurrences} 次 · 基色 distinct=${m.rgbColors.baseDistinct} — Top${Math.min(TOP_N, m.rgbColors.top.length)}: ${top}`,
    );
  } else {
    out.push('rgb/rgba distinct=0 · 基色 distinct=0');
  }

  // radius
  const radiusList = [...m.borderRadius.values]
    .sort((a, b) => cmpCssValue(a.value, b.value))
    .map((v) => `${v.value}×${v.count}`);
  out.push(`border-radius distinct=${m.borderRadius.distinct} — ${preview(radiusList, DETAIL_PREVIEW)}`);

  // font-size
  const fontList = [...m.fontSize.values]
    .sort((a, b) => cmpCssValue(a.value, b.value))
    .map((v) => `${v.value}×${v.count}`);
  out.push(`font-size distinct=${m.fontSize.distinct} — ${preview(fontList, DETAIL_PREVIEW)}`);

  // 选择器
  out.push(`规则块 ${m.ruleBlocks} · distinct 选择器 ${m.distinctSelectors}`);
  if (m.selectors.duplicateCount === 0) {
    out.push('同一选择器分散在多块 0 个（提示项）');
  } else {
    const list = m.selectors.top.map((d) => `${d.value}×${d.count}`).join(' · ');
    out.push(
      `同一选择器分散在多块 ${m.selectors.duplicateCount} 个 / 共 ${m.selectors.duplicateUses} 次（提示项，不参与判定）— Top${m.selectors.top.length}: ${list}`,
    );
  }

  out.push(`!important ${m.importantCount}`);
  out.push(
    `token 覆盖率 ${m.tokenCoverage.percent.toFixed(1)}% — var() ${m.tokenCoverage.varUses} 次 · 硬编码颜色 ${m.tokenCoverage.hardcodedColors} 个 · 硬编码间距/字号/圆角 px ${m.tokenCoverage.hardcodedPx} 个`,
  );
  for (const note of m.notes) out.push(`注意  ${note}`);

  out.push('─'.repeat(64));
  out.push(summaryLine(checks));
  return out.join('\n');
}

function preview(arr, n) {
  if (arr.length === 0) return '(无)';
  if (arr.length <= n) return arr.join(' · ');
  return arr.slice(0, n).join(' · ') + ` · …(+${arr.length - n})`;
}

function buildJson(target, files, m, checks) {
  return {
    tool: 'audit-css',
    version: 1,
    target,
    files,
    thresholds: {
      nearDuplicateDistance: NEAR_DUP_DISTANCE,
      nearWhiteMin: NEAR_WHITE_MIN,
      neutralSaturation: NEUTRAL_SAT,
      neutralChroma: NEUTRAL_CHROMA,
      limits: LIMITS,
    },
    totals: {
      files: m.fileCount,
      lines: m.lines,
      ruleBlocks: m.ruleBlocks,
      distinctSelectors: m.distinctSelectors,
      selectorUses: m.totalSelectorUses,
    },
    root: {
      blockCount: m.rootBlocks,
      files: m.rootFiles,
      variables: m.variables.total,
      variableDeclarations: m.variables.declarations,
      duplicates: m.variables.duplicates,
    },
    hexColors: m.hexColors,
    rgbColors: m.rgbColors,
    colored: { distinct: m.coloredDistinct, values: m.colored },
    nearWhite: { distinct: m.nearWhiteDistinct, values: m.nearWhite },
    borderRadius: m.borderRadius,
    fontSize: m.fontSize,
    selectors: m.selectors,
    tokenCoverage: m.tokenCoverage,
    importantCount: m.importantCount,
    notes: m.notes,
    checks: checks.map((c) => ({
      id: c.id,
      label: c.label,
      value: c.value,
      need: c.need,
      pass: c.pass,
      advisory: !!c.advisory,
    })),
    failed: checks.filter((c) => !c.pass && !c.advisory).map((c) => c.id),
    failedCount: checks.filter((c) => !c.pass && !c.advisory).length,
    passed: checks.every((c) => c.pass || c.advisory),
  };
}

function printHelp() {
  process.stdout.write(
    [
      'audit-css.mjs —— CSS「设计系统漂移」审计记分卡（零依赖 · Node 18+）',
      '',
      '用法:',
      '  node audit-css.mjs <css文件或目录> [--ignore <片段>]... [--json] [--quiet] [--help]',
      '',
      '参数:',
      '  <css文件或目录>  目录会递归收集所有 .css 与 .vue（.vue 只取 <style> 块）；',
      '                   跳过 node_modules / dist / build / .git / coverage / vendor',
      '',
      '选项:',
      '  --ignore <路径片段>  跳过路径中含该片段的文件（可重复）。也接受 --exclude / --ignore=<片段>',
      '                       用途：排除 tokens.css 这类「字面量本来就合法」的定义文件',
      '  --json     输出机器可读 JSON（全部原始数据 + pass/fail），无装饰字符',
      '  --quiet    只输出总结行',
      '  -h, --help 显示本帮助',
      '',
      '评分项（任一 FAIL → 退出码 1）:',
      '  彩色 distinct ≤ 5        border-radius distinct ≤ 4      font-size distinct ≤ 7',
      '  近白背景 distinct ≤ 3    :root 块 = 1                   token 覆盖率 ≥ 90%',
      '  rgb/rgba 基色 distinct ≤ 3   冗余声明（同属性重复声明）= 0   !important = 0',
      '',
      '提示项（不参与判定，不影响退出码）:',
      '  同一选择器分散在多块 —— 归零需合并块，会改变同特异性选择器之间的先后关系，有渲染风险',
      '',
      '示例:',
      '  node audit-css.mjs .\\ui\\src\\styles\\main.css',
      '  node audit-css.mjs .\\ui\\src\\styles --ignore tokens.css --json > report.json',
      '  node audit-css.mjs .\\src\\components --quiet',
      '',
      '退出码: 0 全部通过；1 有未通过项 / 参数或输入错误。',
      '',
    ].join('\n'),
  );
}

// ───────────────────────────── 主流程 ─────────────────────────────

function main() {
  const argv = process.argv.slice(2);
  let json = false;
  let quiet = false;
  let target = null;
  const ignores = [];

  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a === '--help' || a === '-h') {
      printHelp();
      process.exit(0);
    }
    if (a === '--json') {
      json = true;
      continue;
    }
    if (a === '--quiet' || a === '-q') {
      quiet = true;
      continue;
    }
    if (a === '--ignore' || a === '--exclude') {
      const v = argv[++i];
      if (!v) {
        process.stderr.write(`❌ ${a} 需要一个路径片段参数\n`);
        process.exit(1);
      }
      ignores.push(v);
      continue;
    }
    if (a.startsWith('--ignore=') || a.startsWith('--exclude=')) {
      const v = a.slice(a.indexOf('=') + 1);
      if (!v) {
        process.stderr.write(`❌ ${a} 缺少值\n`);
        process.exit(1);
      }
      ignores.push(v);
      continue;
    }
    if (a.startsWith('-')) {
      process.stderr.write(`❌ 未知选项 ${a}（用 --help 查看用法）\n`);
      process.exit(1);
    }
    if (target === null) target = a;
    else {
      process.stderr.write(`❌ 只接受一个目标路径，多给了: ${a}\n`);
      process.exit(1);
    }
  }

  if (!target) {
    process.stderr.write('❌ 缺少目标：需要 <css文件或目录>（用 --help 查看用法）\n');
    process.exit(1);
  }

  const abs = path.resolve(target);
  if (!fs.existsSync(abs)) {
    process.stderr.write(`❌ 路径不存在: ${abs}\n`);
    process.exit(1);
  }
  const st = fs.statSync(abs);
  if (!st.isDirectory() && !st.isFile()) {
    process.stderr.write(`❌ 不是文件也不是目录: ${abs}\n`);
    process.exit(1);
  }
  if (st.isFile()) {
    const ext = path.extname(abs).toLowerCase();
    if (ext !== '.css' && ext !== '.vue') {
      process.stderr.write(`❌ 只支持 .css / .vue 文件，收到: ${path.basename(abs)}\n`);
      process.exit(1);
    }
  }

  const allFiles = collectFiles(abs);
  const files = filterIgnored(allFiles, ignores);
  if (files.length === 0) {
    process.stderr.write(
      ignores.length
        ? `❌ 忽略规则过滤后没有剩余文件: ${abs}（忽略: ${ignores.join(', ')}）\n`
        : `❌ 未找到任何 .css / .vue 文件: ${abs}\n`,
    );
    process.exit(1);
  }

  const docs = [];
  for (const f of files) {
    try {
      docs.push(analyzeFile(f));
    } catch (err) {
      process.stderr.write(`❌ 读取失败 ${f}: ${err && err.message ? err.message : err}\n`);
      process.exit(1);
    }
  }

  const metrics = computeMetrics(docs, files);
  const checks = buildChecks(metrics);
  const failed = checks.filter((c) => !c.pass && !c.advisory);

  if (json) {
    process.stdout.write(JSON.stringify(buildJson(abs, files, metrics, checks), null, 2) + '\n');
  } else if (quiet) {
    process.stdout.write(summaryLine(checks) + '\n');
  } else {
    process.stdout.write(renderScorecard(abs, metrics, checks) + '\n');
  }

  process.exit(failed.length === 0 ? 0 : 1);
}

main();
