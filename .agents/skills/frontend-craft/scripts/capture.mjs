#!/usr/bin/env node
/**
 * capture.mjs —— 无头浏览器多宽度截图（零依赖 · Node 18+ · 跨平台）
 *
 * 用途
 *   把一个 URL（或本地 HTML 文件）在多个视口宽度下各截一张 PNG，
 *   供 AI 或人做响应式视觉验收。
 *
 * 用法
 *   node capture.mjs <url> <outDir> [选项]
 *
 * 选项
 *   --widths 375,768,1440   逗号分隔的视口宽度列表（默认 375,768,1440）
 *   --height 900            视口高度，px（默认 900）
 *   --budget 1500           --virtual-time-budget，毫秒（默认 1500）
 *   --scale 1               --force-device-scale-factor（默认 1）
 *   --name shot             输出文件名前缀 → shot-<width>.png（默认 shot）
 *   --chrome <path>         指定浏览器可执行文件（优先级最高）
 *   --help                  显示本帮助
 *
 * 示例
 *   node capture.mjs "file:///A:/proj/index.html" A:\proj\shots --widths 375,1440
 *   node capture.mjs https://example.com .\shots --height 1200 --scale 2 --name home
 *   node capture.mjs .\local\page.html .\shots            REM 本地路径自动转 file:///
 *   $env:CHROME_PATH = "D:\Chrome\chrome.exe"; node capture.mjs https://example.com .\shots
 *
 * 浏览器探测顺序
 *   1) --chrome <path>   2) 环境变量 CHROME_PATH   3) 自动探测：
 *   Windows : %ProgramFiles%\Google\Chrome\Application\chrome.exe
 *             %ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe
 *             %LOCALAPPDATA%\Google\Chrome\Application\chrome.exe
 *             %ProgramFiles%\Microsoft\Edge\Application\msedge.exe
 *             %ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe
 *   macOS   : /Applications/Google Chrome.app/Contents/MacOS/Google Chrome
 *   Linux   : PATH 中的 google-chrome / chromium / chromium-browser
 *
 * 设计与约束（重要）
 *   - 子进程一律用 spawnSync 且 stdio: 'ignore'：绝不管道 stdout/stderr。
 *     某些受限沙箱下管道会抛 EPERM，因此脚本完全不读取浏览器输出。
 *   - 成功与否只看输出 PNG 是否存在且字节数 > 0（先删除旧文件再截图，避免误判）。
 *   - 额外加了 --user-data-dir=<临时目录>：避免与本机已运行的 Chrome/Edge 争用
 *     默认用户配置导致 headless 进程直接退出、截不出图。
 *
 * 退出码
 *   0 全部成功 · 1 参数错误 / 找不到浏览器 / 截图失败
 */

import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { spawnSync } from 'node:child_process';

const DEFAULT_WIDTHS = [375, 768, 1440];
const CHROME_TIMEOUT_MS = 120000; // 单张截图最长等待

// ───────────────────────────── 小工具 ─────────────────────────────

/** 打印错误并退出 1 */
function die(msg) {
  process.stderr.write(`\n❌ ${msg}\n`);
  process.exit(1);
}

/** 数字参数校验 */
function toPositiveInt(raw, flag) {
  const n = Number.parseInt(String(raw).trim(), 10);
  if (!Number.isFinite(n) || n <= 0) {
    die(`${flag} 需要一个正整数，收到: ${JSON.stringify(raw)}`);
  }
  return n;
}

/** 数字参数校验（允许小数，如 --scale 1.5） */
function toPositiveNumber(raw, flag) {
  const n = Number.parseFloat(String(raw).trim());
  if (!Number.isFinite(n) || n <= 0) {
    die(`${flag} 需要一个正数，收到: ${JSON.stringify(raw)}`);
  }
  return n;
}

/**
 * 本地绝对路径 → file:/// URL。
 * Windows: A:\x\y.html → file:///A:/x/y.html（保留盘符冒号，空格转 %20）
 */
function toFileUrl(absPath) {
  let p = absPath.replace(/\\/g, '/');
  if (!p.startsWith('/')) p = '/' + p; // A:/x → /A:/x，于是 file:// + /A:/x = file:///A:/x
  // 只编码真正需要编码的字符；保留 : / 等 URL 合法字符，保证 file:///A:/x 形态
  const safe = /[A-Za-z0-9\-._~!$&'()*+,;=:@/]/;
  p = Array.from(p)
    .map((ch) => (safe.test(ch) ? ch : encodeURIComponent(ch)))
    .join('');
  return 'file://' + p;
}

/**
 * 解析位置参数里的 URL：
 *   - 已有 scheme（http/https/file/...）→ 原样使用
 *   - 本地路径（绝对 / 相对 / UNC / 盘符）→ 转 file:/// 并校验文件存在
 */
function normalizeTarget(input) {
  const raw = String(input).trim();
  if (!raw) die('缺少 <url> 参数');
  if (/^[a-zA-Z][a-zA-Z0-9+.-]*:\/\//.test(raw)) {
    return { url: raw, local: /^file:\/\//i.test(raw) };
  }
  const abs = path.resolve(raw);
  if (!fs.existsSync(abs)) {
    die(`本地文件不存在: ${abs}`);
  }
  return { url: toFileUrl(abs), local: true, localPath: abs };
}

// ───────────────────────── 浏览器可执行文件探测 ─────────────────────────

/** Windows 候选路径（严格按约定顺序） */
function windowsCandidates() {
  const list = [];
  const pf = process.env['ProgramFiles'];
  const pf86 = process.env['ProgramFiles(x86)'];
  const localApp = process.env['LOCALAPPDATA'];
  if (pf) list.push(path.join(pf, 'Google', 'Chrome', 'Application', 'chrome.exe'));
  if (pf86) list.push(path.join(pf86, 'Google', 'Chrome', 'Application', 'chrome.exe'));
  if (localApp) list.push(path.join(localApp, 'Google', 'Chrome', 'Application', 'chrome.exe'));
  if (pf) list.push(path.join(pf, 'Microsoft', 'Edge', 'Application', 'msedge.exe'));
  if (pf86) list.push(path.join(pf86, 'Microsoft', 'Edge', 'Application', 'msedge.exe'));
  return list;
}

/** macOS 候选路径 */
function macCandidates() {
  return [
    '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
    '/Applications/Chromium.app/Contents/MacOS/Chromium',
    '/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge',
  ];
}

/** Linux：在 PATH 里查找命令名 */
function linuxCandidates() {
  const names = ['google-chrome', 'chromium', 'chromium-browser', 'google-chrome-stable'];
  const dirs = (process.env.PATH || '').split(path.delimiter).filter(Boolean);
  const out = [];
  for (const name of names) {
    for (const dir of dirs) out.push(path.join(dir, name));
  }
  return out;
}

/** 按平台列出候选；返回 {candidates, findInPath:boolean} */
function candidatesForPlatform() {
  if (process.platform === 'win32') return { candidates: windowsCandidates(), pathSearch: false };
  if (process.platform === 'darwin') return { candidates: macCandidates(), pathSearch: false };
  return { candidates: linuxCandidates(), pathSearch: true };
}

/** 候选是否为「可执行的普通文件」 */
function isUsable(candidate, pathSearch) {
  try {
    const st = fs.statSync(candidate);
    if (!st.isFile()) return false;
  } catch {
    return false;
  }
  if (pathSearch) {
    try {
      fs.accessSync(candidate, fs.constants.X_OK);
    } catch {
      return false;
    }
  }
  return true;
}

/** 解析出浏览器路径；失败时报错并列出所有尝试过的路径 */
function resolveChrome(explicit) {
  // 1) --chrome 优先级最高，指定了就必须可用
  if (explicit) {
    const abs = path.resolve(explicit);
    if (!isUsable(abs, process.platform !== 'win32' && process.platform !== 'darwin')) {
      die(`--chrome 指定的浏览器不可用: ${abs}\n   请检查路径是否正确、是否为文件。`);
    }
    return abs;
  }

  // 2) 环境变量 CHROME_PATH：无效时给出警告并继续自动探测
  const tried = [];
  const fromEnv = process.env.CHROME_PATH;
  if (fromEnv) {
    const abs = path.resolve(fromEnv);
    if (isUsable(abs, false)) return abs;
    tried.push(`CHROME_PATH=${fromEnv}（不可用，已忽略）`);
    process.stderr.write(`⚠️  环境变量 CHROME_PATH 指向的文件不可用，继续自动探测: ${abs}\n`);
  }

  // 3) 自动探测
  const { candidates, pathSearch } = candidatesForPlatform();
  for (const c of candidates) {
    tried.push(c);
    if (isUsable(c, pathSearch)) return c;
  }

  die(
    [
      '未找到可用的浏览器（Chrome / Edge / Chromium）。',
      '已尝试以下位置：',
      ...tried.map((t) => `  - ${t}`),
      '',
      '解决办法（任选其一）：',
      '  - 用 --chrome "<浏览器路径>" 显式指定',
      '  - 设置环境变量 CHROME_PATH=<浏览器路径>',
      '  - 安装 Google Chrome 或 Microsoft Edge',
    ].join('\n'),
  );
}

// ───────────────────────────── 截图 ─────────────────────────────

/**
 * 用 spawnSync 跑一次 headless 截图。
 * 注意：stdio 一律 'ignore'，不捕获任何子进程输出（受限沙箱下管道会 EPERM）。
 */
function captureOne({ chrome, url, outFile, width, height, budget, scale, profileDir }) {
  // 先删掉旧文件：否则「文件存在」无法证明这次真的截成功了
  try {
    if (fs.existsSync(outFile)) fs.rmSync(outFile);
  } catch {
    /* 删不掉就让后面的校验兜底 */
  }

  const args = [
    '--headless=new',
    '--disable-gpu',
    '--hide-scrollbars',
    '--no-sandbox',
    `--force-device-scale-factor=${scale}`,
    `--virtual-time-budget=${budget}`,
    `--window-size=${width},${height}`,
    `--user-data-dir=${profileDir}`,
    `--screenshot=${outFile}`,
    url,
  ];

  const res = spawnSync(chrome, args, {
    stdio: 'ignore', // 关键：绝不管道化子进程 stdio
    timeout: CHROME_TIMEOUT_MS,
    windowsHide: true,
  });

  // 只看输出文件：存在且字节数 > 0 即成功
  let bytes = 0;
  try {
    const st = fs.statSync(outFile);
    if (st.isFile()) bytes = st.size;
  } catch {
    bytes = 0;
  }

  if (bytes > 0) return { ok: true, bytes };

  const why = [];
  if (res.error) why.push(`spawn error: ${res.error.message}`);
  if (res.signal) why.push(`被信号终止: ${res.signal}`);
  if (typeof res.status === 'number') why.push(`退出码: ${res.status}`);
  return {
    ok: false,
    bytes: 0,
    reason: why.join(' / ') || '未知原因',
  };
}

// ───────────────────────────── 帮助 ─────────────────────────────

function printHelp() {
  process.stdout.write(
    [
      'capture.mjs —— 无头浏览器多宽度截图（零依赖 · Node 18+）',
      '',
      '用法:',
      '  node capture.mjs <url> <outDir> [--widths 375,768,1440] [--height 900]',
      '                    [--budget 1500] [--scale 1] [--name shot] [--chrome <path>] [--help]',
      '',
      '参数:',
      '  <url>                   http:// | https:// | file:// 开头的 URL，或本地 HTML 文件路径',
      '                          （本地相对/绝对路径会自动转成 file:/// 形式）',
      '  <outDir>                输出目录，不存在则递归创建',
      '',
      '选项:',
      '  --widths <列表>         逗号分隔的宽度，每个宽度截一张（默认 375,768,1440）',
      '  --height <px>           视口高度（默认 900）',
      '  --budget <ms>           --virtual-time-budget，等待页面渲染的虚拟时间（默认 1500）',
      '  --scale <n>             --force-device-scale-factor（默认 1；2 = 高清二倍图）',
      '  --name <前缀>           文件名前缀，输出 <前缀>-<width>.png（默认 shot）',
      '  --chrome <path>         浏览器可执行文件，优先于 CHROME_PATH 与自动探测',
      '  -h, --help              显示本帮助',
      '',
      '示例:',
      '  node capture.mjs "file:///A:/proj/index.html" A:\\proj\\shots --widths 375,1440',
      '  node capture.mjs https://example.com .\\shots --height 1200 --scale 2 --name home',
      '  node capture.mjs .\\page.html .\\shots --chrome "D:\\Chrome\\chrome.exe"',
      '  $env:CHROME_PATH = "D:\\Chrome\\chrome.exe"; node capture.mjs https://example.com .\\shots',
      '',
      '说明:',
      '  浏览器探测顺序: --chrome > 环境变量 CHROME_PATH > 自动探测（Chrome / Edge / Chromium）。',
      '  子进程以 stdio: "ignore" 启动，完全不读取浏览器 stdout/stderr（受限沙箱下管道会 EPERM）；',
      '  成功与否只看输出 PNG 是否存在且字节数 > 0。',
      '  退出码: 0 全部成功；1 参数错误 / 未找到浏览器 / 任一张截图失败。',
      '',
    ].join('\n'),
  );
}

// ───────────────────────────── 主流程 ─────────────────────────────

function parseArgs(argv) {
  const opts = {
    widths: DEFAULT_WIDTHS,
    height: 900,
    budget: 1500,
    scale: 1,
    name: 'shot',
    chrome: null,
    help: false,
  };
  const positional = [];

  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a === '--help' || a === '-h') {
      opts.help = true;
      continue;
    }
    if (a.startsWith('--')) {
      let key;
      let val;
      const eq = a.indexOf('=');
      if (eq > 2) {
        key = a.slice(2, eq);
        val = a.slice(eq + 1);
      } else {
        key = a.slice(2);
        val = argv[i + 1];
        if (val === undefined || (val.startsWith('--') && val !== '--')) {
          die(`选项 --${key} 缺少取值`);
        }
        i++;
      }
      switch (key) {
        case 'widths':
          opts.widths = String(val)
            .split(',')
            .map((s) => s.trim())
            .filter(Boolean)
            .map((s) => toPositiveInt(s, '--widths'));
          if (opts.widths.length === 0) die('--widths 至少需要一个宽度');
          break;
        case 'height':
          opts.height = toPositiveInt(val, '--height');
          break;
        case 'budget':
          opts.budget = toPositiveInt(val, '--budget');
          break;
        case 'scale':
          opts.scale = toPositiveNumber(val, '--scale');
          break;
        case 'name':
          opts.name = String(val).trim();
          if (!opts.name) die('--name 不能为空');
          break;
        case 'chrome':
          opts.chrome = String(val).trim();
          if (!opts.chrome) die('--chrome 不能为空');
          break;
        default:
          die(`未知选项 --${key}（用 --help 查看用法）`);
      }
      continue;
    }
    positional.push(a);
  }

  if (!opts.help && positional.length < 2) {
    die('参数不足：需要 <url> 和 <outDir>（用 --help 查看用法）');
  }
  opts.positional = positional;
  return opts;
}

function main() {
  const opts = parseArgs(process.argv.slice(2));
  if (opts.help) {
    printHelp();
    process.exit(0);
  }

  const [rawUrl, rawOutDir] = opts.positional;
  const target = normalizeTarget(rawUrl);

  const outDir = path.resolve(rawOutDir);
  fs.mkdirSync(outDir, { recursive: true }); // 递归创建输出目录

  const chrome = resolveChrome(opts.chrome);
  const safeName = opts.name.replace(/[\\/:*?"<>|]+/g, '_'); // 防文件名里混入路径分隔符
  const profileDir = path.join(os.tmpdir(), `dsh-capture-${process.pid}`);

  process.stdout.write(
    [
      `浏览器  ${chrome}`,
      `目标    ${target.url}`,
      `输出    ${outDir}`,
      `参数    widths=${opts.widths.join(',')} height=${opts.height} budget=${opts.budget} scale=${opts.scale}`,
      '',
    ].join('\n'),
  );

  const started = Date.now();
  const results = [];

  for (const width of opts.widths) {
    const outFile = path.join(outDir, `${safeName}-${width}.png`);
    const r = captureOne({
      chrome,
      url: target.url,
      outFile,
      width,
      height: opts.height,
      budget: opts.budget,
      scale: opts.scale,
      profileDir,
    });
    if (r.ok) {
      const kb = (r.bytes / 1024).toFixed(1);
      process.stdout.write(`✅ ${String(width).padStart(4)}  ${outFile}  ${r.bytes} B (${kb} KB)\n`);
      results.push({ width, file: outFile, bytes: r.bytes, ok: true });
    } else {
      process.stderr.write(`❌ ${String(width).padStart(4)}  截图失败 → ${outFile}\n      原因: ${r.reason}\n`);
      results.push({ width, file: outFile, bytes: 0, ok: false, reason: r.reason });
    }
  }

  const totalMs = Date.now() - started;
  const okCount = results.filter((r) => r.ok).length;

  if (okCount !== results.length) {
    process.stderr.write(`\n完成: ${okCount}/${results.length} 张成功 · 总耗时 ${totalMs} ms\n`);
    process.exit(1);
  }

  process.stdout.write(`\n完成: ${okCount}/${results.length} 张成功 · 总耗时 ${totalMs} ms\n`);
  process.exit(0);
}

main();
