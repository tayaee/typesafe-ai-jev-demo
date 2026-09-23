#!/usr/bin/env npx tsx
/**
 * Play 4096 (https://thereal4096.github.io) with a local Laya System-1 model.
 *
 * Same game loop as ../play-4096-jev/play4096.py, but the move comes from
 * https://github.com/receptron/laya (open-source Jev-compatible decision
 * model, ONNX Runtime — no API key, no network after the weights download)
 * instead of the TypeSafe SystemOne (`jev-latest`) HTTP API.
 *
 * Golden path (mirrors the jev version):
 *   state={board,score} object + `choice` question `best_combo`
 *   (multi-key sequence, ON by default; --no-combo for single best_move)
 *   Playwright external loop, DOM `.tile-container .tile` parsing,
 *   real keyboard path (ArrowUp/Right/Down/Left), autoplay until game-over.
 *
 * Usage:
 *   npm start -- [--connect INFO] [--url URL] [--new-game] [--start-delay-secs 10]
 *                [--max-moves N] [--dry-run] [--move-delay-secs 0.0] [--headless]
 *                [--corner CORNER] [--no-combo]
 *                [--combos "down+left,down+down+left,right+left,up+down"]
 *                [--model-dir ./onnx] [--verbose]
 *
 * Model weights (~1.7 GB fp32) download from Hugging Face on first use and
 * are cached under ~/.cache/receptron-laya (override: LAYA_CACHE env or
 * --model-dir for a local export from export/export_onnx.py).
 * --dry-run skips the model entirely (local heuristic, no download).
 */

import { spawn } from "node:child_process";
import fs from "node:fs";
import net from "node:net";
import os from "node:os";
import path from "node:path";
import { chromium, type Browser, type Page } from "playwright";
import { Laya } from "@receptron/laya";

// ---------------------------------------------------------------- args

interface Args {
  connect: string | null;
  url: string;
  newGame: boolean;
  startDelaySecs: number;
  maxMoves: number | null;
  dryRun: boolean;
  moveDelaySecs: number;
  userDataDir: string | null;
  remoteDebuggingPort: number;
  headed: boolean;
  modelDir: string | undefined;
  shotDir: string | null;
  corner: Corner;
  combo: boolean;
  combos: string | null;
  verbose: boolean;
}

type Corner = "upper-left" | "upper-right" | "lower-left" | "lower-right";

function parseArgs(argv: string[]): Args {
  const a: Args = {
    connect: null,
    url: "https://thereal4096.github.io",
    newGame: false,
    startDelaySecs: 2.0,
    maxMoves: null,
    dryRun: false,
    moveDelaySecs: 0.0,
    userDataDir: null,
    remoteDebuggingPort: 0,
    headed: true,
    modelDir: process.env.LAYA_MODEL_DIR || undefined,
    shotDir: null,
    corner: "lower-left",
    combo: true,
    combos: null,
    verbose: false,
  };
  const rest = argv.slice(2);
  const need = (flag: string, i: number): string => {
    const v = rest[i + 1];
    if (v === undefined || v.startsWith("--")) throw new Error(`${flag} needs a value`);
    return v;
  };
  for (let i = 0; i < rest.length; i++) {
    const t = rest[i]!;
    switch (t) {
      case "--connect":
        a.connect = rest[i + 1] && !rest[i + 1]!.startsWith("--") ? rest[++i]! : ".play4096-laya-browser.json";
        break;
      case "--url": a.url = need(t, i); i++; break;
      case "--new-game": a.newGame = true; break;
      case "--start-delay-secs": a.startDelaySecs = parseFloat(need(t, i)); i++; break;
      case "--max-moves": a.maxMoves = parseInt(need(t, i), 10); i++; break;
      case "--dry-run": a.dryRun = true; break;
      case "--move-delay-secs": a.moveDelaySecs = parseFloat(need(t, i)); i++; break;
      case "--user-data-dir": a.userDataDir = need(t, i); i++; break;
      case "--remote-debugging-port": a.remoteDebuggingPort = parseInt(need(t, i), 10); i++; break;
      case "--headed": a.headed = true; break;
      case "--headless": a.headed = false; break;
      case "--model-dir": a.modelDir = need(t, i); i++; break;
      case "--shot-dir": a.shotDir = need(t, i); i++; break;
      case "--corner":
        { const v = need(t, i); i++;
          if (v !== "upper-left" && v !== "upper-right" && v !== "lower-left" && v !== "lower-right")
            throw new Error(`--corner must be one of upper-left/upper-right/lower-left/lower-right (got ${v})`);
          a.corner = v; }
        break;
      case "--combo": a.combo = true; break;
      case "--no-combo": a.combo = false; break;
      case "--combos": a.combos = need(t, i); i++; a.combo = true; break;
      case "--verbose": a.verbose = true; break;
      case "--help":
      case "-h":
        console.log(`Usage: play4096-laya.ts [options]
  --connect [FILE]        persistent Chrome reuse (default file: .play4096-laya-browser.json)
  --url URL               game page (default: https://thereal4096.github.io)
  --new-game              click New Game before starting
  --start-delay-secs N    wait before first move (default: 2.0)
  --max-moves N           stop after N moves (default: until game over)
  --dry-run               no model; local heuristic (no 1.7 GB download)
  --move-delay-secs N     settle delay after each move (0 = fastest)
  --headed / --headless   show window or not (default: headed)
  --model-dir DIR         local ONNX bundle (default: download+cache; or $LAYA_MODEL_DIR)
  --shot-dir DIR          save a PNG screenshot per move here
  --corner C              lower-left (default) | lower-right | upper-left | upper-right
  --combo / --no-combo    multi-key sequences (default: ON)
  --combos LIST           custom combos, e.g. "down+left,down+down+left,right+left,up+down"
  --verbose               board dumps + full probs/timings`);
        process.exit(0);
      default:
        throw new Error(`unknown flag ${t} (see --help)`);
    }
  }
  return a;
}

// ---------------------------------------------------------------- board logic

type Board = number[][];

const POS_RE = /tile-position-(\d+)-(\d+)/;

interface GameSnapshot { board: Board; score: number; over: boolean; won: boolean; }

async function snapshot(page: Page): Promise<GameSnapshot> {
  // NOTE: pass a real function (not a string): page.evaluate(string) treats
  // "() => {...}" as an unevaluated expression in some versions and returns
  // undefined instead of calling it.
  const data = await page.evaluate(() => {
    const tiles = [...document.querySelectorAll(".tile-container .tile")].map((el) => ({
      cls: el.className,
      text: el.querySelector(".tile-inner")?.textContent || "",
    }));
    const sc = document.querySelector(".score-container");
    let score = 0;
    if (sc) {
      const first = sc.firstChild;
      const raw = (first?.textContent ? first.textContent : sc.textContent) || "0";
      score = parseInt(raw.replace(/[^0-9-]/g, ""), 10) || 0;
    }
    const msg = document.querySelector(".game-message");
    return {
      tiles, score,
      over: !!(msg && msg.classList.contains("game-over")),
      won: !!(msg && msg.classList.contains("game-won")),
    };
  });
  const board: Board = Array.from({ length: 4 }, () => [0, 0, 0, 0]);
  for (const t of data.tiles ?? []) {
    const m = POS_RE.exec(t.cls ?? "");
    if (!m) continue;
    const x = parseInt(m[1]!, 10) - 1, y = parseInt(m[2]!, 10) - 1;
    if (x < 0 || x > 3 || y < 0 || y > 3) continue;
    const v = parseInt((t.text ?? "").trim(), 10);
    if (!Number.isFinite(v)) continue;
    if (v > board[y]![x]!) board[y]![x] = v;
  }
  return { board, score: data.score ?? 0, over: !!data.over, won: !!data.won };
}

function boardKey(b: Board): string { return b.flat().join(","); }

let STOP = false;

async function waitSettled(page: Page, timeout = 2.5): Promise<GameSnapshot> {
  let prev: string | null = null;
  let stable = 0;
  const deadline = Date.now() + timeout * 1000;
  let last: GameSnapshot = { board: [[0,0,0,0],[0,0,0,0],[0,0,0,0],[0,0,0,0]], score: 0, over: false, won: false };
  while (Date.now() < deadline && !STOP) {
    last = await snapshot(page);
    const k = boardKey(last.board) + "|" + last.score;
    if (k === prev) { if (++stable >= 2) return last; }
    else { stable = 0; prev = k; }
    await sleep(100);
  }
  return last;
}

function fmtBoard(b: Board): string {
  return b.map((r) => r.map((v) => String(v).padStart(5)).join(" ")).join("\n");
}

function fmtProb(probs: Record<string, number>, key: string): string {
  const v = probs[key];
  return typeof v === "number" ? v.toFixed(2) : "--";
}

function fmtMoveLine(n: number, score: number, seq: string, probs: Record<string, number>, dtMs: number): string {
  return `[move ${String(n).padStart(3, "0")}] board score=${score}, ` +
    `laya decision (${(dtMs / 1000).toFixed(3)} sec) => ${seq} prob ${fmtProb(probs, seq)}`;
}

function sleep(ms: number): Promise<void> { return new Promise((r) => setTimeout(r, ms)); }

// --- 2048 slide simulation (dry-run validity filter) ---

function slideRowLeft(row: number[]): number[] {
  const tiles = row.filter((v) => v);
  const out: number[] = [];
  let i = 0;
  while (i < tiles.length) {
    if (i + 1 < tiles.length && tiles[i] === tiles[i + 1]) { out.push(tiles[i]! * 2); i += 2; }
    else { out.push(tiles[i]!); i += 1; }
  }
  while (out.length < 4) out.push(0);
  return out;
}

type Move = "up" | "right" | "down" | "left";
const VALID_MOVES: Move[] = ["up", "right", "down", "left"];

function movedBoard(board: Board, move: Move): Board {
  const b = board.map((r) => [...r]);
  if (move === "left") return b.map(slideRowLeft);
  if (move === "right") return b.map((r) => [...slideRowLeft([...r].reverse())].reverse());
  const t = b[0]!.map((_, c) => b.map((r) => r[c]!));
  const s = move === "up" ? t.map(slideRowLeft)
    : t.map((r) => [...slideRowLeft([...r].reverse())].reverse());
  return s[0]!.map((_, c) => s.map((r) => r[c]!));
}

function validMoves(board: Board): Move[] {
  const key = boardKey(board);
  return (["up", "right", "down", "left"] as Move[]).filter((m) => boardKey(movedBoard(board, m)) !== key);
}

function cornerWeight(y: number, x: number, corner: Corner): number {
  const tx = corner.includes("left") ? 3 - x : x;
  const ty = corner.includes("upper") ? 3 - y : y;
  return 2 ** (tx + ty);
}

function boardScore(b: Board, corner: Corner): [number, number] {
  let s = 0, empty = 0;
  b.forEach((row, y) => row.forEach((v, x) => { s += v * cornerWeight(y, x, corner); if (v === 0) empty++; }));
  return [s, empty];
}

function heuristicMove(board: Board, corner: Corner): Move | null {
  const vm = validMoves(board);
  if (!vm.length) return null;
  const hTarget = corner.includes("right") ? "right" : "left";
  const vTarget = corner.includes("lower") ? "down" : "up";
  const hAvoid = hTarget === "right" ? "left" : "right";
  const vAvoid = vTarget === "down" ? "up" : "down";
  const pref: Move[] = [hTarget as Move, vTarget as Move, hAvoid as Move, vAvoid as Move];
  let best = vm[0]!, bestKey: [number, number, number] | null = null;
  for (const m of vm) {
    const [s, e] = boardScore(movedBoard(board, m), corner);
    const k: [number, number, number] = [s, e, -pref.indexOf(m)];
    if (!bestKey || k[0] > bestKey[0] || (k[0] === bestKey[0] && (k[1] > bestKey[1] || (k[1] === bestKey[1] && k[2] > bestKey[2])))) {
      bestKey = k; best = m;
    }
  }
  return best;
}

// ---------------------------------------------------------------- prompts (same strategy text as the jev version)

const CORNER_DESCR: Record<Corner, string> = {
  "upper-left": "upper-left corner (top row, leftmost column)",
  "upper-right": "upper-right corner (top row, rightmost column)",
  "lower-left": "lower-left corner (bottom row, leftmost column)",
  "lower-right": "lower-right corner (bottom row, rightmost column)",
};

function buildInstructions(corner: Corner): string {
  return (
    "You play 4096 (a 2048 variant) on a 4x4 grid. Rows go top-to-bottom, " +
    "columns left-to-right, 0 means empty. Merge equal tiles by sliding; " +
    "after each slide a 2 or 4 appears. Keep the largest tile in the " +
    `${CORNER_DESCR[corner]} and the board organized so it can keep merging toward 4096. ` +
    "If the rows near the corner are full and sorted descending toward it, " +
    "merge the stack above the edge column downward first; " +
    "do not shuffle the sorted rows. " +
    "Given the board, reply with exactly one of up/down/left/right: the best next slide."
  );
}

function buildCriteria(corner: Corner): Record<string, string> {
  const hTarget = corner.includes("right") ? "right" : "left";
  const vTarget = corner.includes("lower") ? "down" : "up";
  const base: Record<Move, string> = {
    up: "Slide all tiles up.",
    right: "Slide all tiles right.",
    down: "Slide all tiles down.",
    left: "Slide all tiles left.",
  };
  const out: Record<string, string> = {};
  for (const [move, text] of Object.entries(base)) {
    out[move] = (move === hTarget || move === vTarget)
      ? `${text} Excellent: pushes tiles toward the ${CORNER_DESCR[corner]}.`
      : `${text} Usually bad: moves tiles away from the ${CORNER_DESCR[corner]}.`;
  }
  return out;
}

// ---------------------------------------------------------------- combos (multi-key sequences)

const MAX_COMBOS = 10;
const MAX_SEQ_LEN = 4;

type ComboSpec = [id: string, seq: Move[], why: string];

function comboSpecs(corner: Corner): ComboSpec[] {
  const hTarget = corner.includes("right") ? "right" : "left";
  const vTarget = corner.includes("lower") ? "down" : "up";
  const hAvoid = hTarget === "right" ? "left" : "right";
  const vAvoid = vTarget === "down" ? "up" : "down";
  return [
    [`${vTarget}+${hTarget}`, [vTarget as Move, hTarget as Move], `${vTarget} then ${hTarget}: main loop, gather into the corner.`],
    [`${hTarget}+${vTarget}`, [hTarget as Move, vTarget as Move], `${hTarget} then ${vTarget}: main-loop variant, merge rows first.`],
    [`${vTarget}+${vTarget}+${hTarget}`, [vTarget as Move, vTarget as Move, hTarget as Move],
      `${vTarget} twice then ${hTarget}: merge vertically, then gather. Sorted-board cleanup: merges the stack above the edge column into it.`],
    [`${hTarget}+${hTarget}+${vTarget}`, [hTarget as Move, hTarget as Move, vTarget as Move],
      `${hTarget} twice then ${vTarget}: merge horizontally, then gather.`],
    [`${vTarget}+${hTarget}+${vTarget}+${hTarget}`,
      [vTarget as Move, hTarget as Move, vTarget as Move, hTarget as Move],
      `${vTarget}-${hTarget} twice: double main loop without new model call. Best pick when the two corner rows are full and sorted.`],
    [`${vTarget}+${vTarget}+${hTarget}+${hTarget}`,
      [vTarget as Move, vTarget as Move, hTarget as Move, hTarget as Move],
      `2x ${vTarget} then 2x ${hTarget}: full tidy into the corner.`],
    [`${hAvoid}+${hTarget}`, [hAvoid as Move, hTarget as Move],
      `${hAvoid} then ${hTarget}: emergency when ${vTarget} is blocked, return at once.`],
    [`${hAvoid}+${hTarget}+${vTarget}`, [hAvoid as Move, hTarget as Move, vTarget as Move],
      `${hAvoid} then ${hTarget} then ${vTarget}: emergency sidestep, then corner.`],
    [`${vAvoid}+${vTarget}`, [vAvoid as Move, vTarget as Move],
      `${vAvoid} then ${vTarget}: only when forced ${vAvoid}, restore immediately.`],
    [`${vAvoid}+${vTarget}+${hTarget}`, [vAvoid as Move, vTarget as Move, hTarget as Move],
      `${vAvoid} then ${vTarget} then ${hTarget}: forced ${vAvoid} recovery into corner.`],
  ];
}

function parseCombosArg(s: string): [string, Move[]][] {
  const parts = s.split(",").map((p) => p.trim()).filter(Boolean);
  if (!parts.length) throw new Error("--combos is empty");
  if (parts.length > MAX_COMBOS) throw new Error(`--combos takes at most ${MAX_COMBOS} sequences (got ${parts.length})`);
  const out: [string, Move[]][] = [];
  for (const p of parts) {
    const seq = p.split(/[+\s>]+/).map((k) => k.trim().toLowerCase()).filter(Boolean) as Move[];
    if (!seq.length) throw new Error(`empty sequence in --combos: ${JSON.stringify(p)}`);
    if (seq.length > MAX_SEQ_LEN) throw new Error(`sequence ${JSON.stringify(p)} exceeds max ${MAX_SEQ_LEN} keys`);
    for (const k of seq) {
      if (!(["up", "right", "down", "left"] as string[]).includes(k))
        throw new Error(`invalid move ${JSON.stringify(k)} in --combos (use up/down/left/right)`);
    }
    out.push([seq.join("+"), seq]);
  }
  const seen = new Map<string, Move[]>();
  for (const [cid, seq] of out) if (!seen.has(cid)) seen.set(cid, seq);
  return [...seen.entries()];
}

function buildComboInstructions(corner: Corner, specs: ComboSpec[]): string {
  const hTarget = corner.includes("right") ? "right" : "left";
  const vTarget = corner.includes("lower") ? "down" : "up";
  const hAvoid = hTarget === "right" ? "left" : "right";
  const opts = specs.map(([cid, seq]) => `${cid} (= ${seq.join(" then ")})`).join(", ");
  return (
    "You play 4096 (a 2048 variant) on a 4x4 grid. Rows go top-to-bottom, " +
    "columns left-to-right, 0 means empty. Merge equal tiles by sliding; " +
    "after each slide a 2 or 4 appears. Keep the largest tile in the " +
    `${CORNER_DESCR[corner]} and the board organized so it can keep merging toward 4096. ` +
    "Sorted-board rule: if the two rows nearest the corner are full and sorted " +
    "descending toward the corner, prefer " +
    `${vTarget}+${hTarget}+${vTarget}+${hTarget} or ${vTarget}+${vTarget}+${hTarget}: ` +
    "they merge the tiles stacked above the edge column into it, then merge the row pair " +
    "beside the corner, then drop the result, without shuffling the sorted rows. " +
    `Never lead with ${hAvoid} when the corner row is full: ` +
    "it drags the largest tile out of the corner. " +
    `Given the board, reply with exactly one of: ${opts}. ` +
    "The browser will press the keys in that sequence at once, in order."
  );
}

function buildComboCriteria(specs: ComboSpec[]): Record<string, string> {
  return Object.fromEntries(specs.map(([cid, seq, why]) => [cid, `Press ${seq.join(" then ")} in order. ${why}`]));
}

function applySequence(board: Board, seq: Move[]): Board {
  let cur = board.map((r) => [...r]);
  for (const m of seq) {
    const nb = movedBoard(cur, m);
    if (boardKey(nb) !== boardKey(cur)) cur = nb;
  }
  return cur;
}

function heuristicCombo(board: Board, corner: Corner, seqs: [string, Move[]][]): string | null {
  let best: string | null = null;
  let bestKey: [number, number, number] | null = null;
  seqs.forEach(([cid, seq], i) => {
    if (boardKey(applySequence(board, seq)) === boardKey(board)) return; // whole sequence is a no-op
    const [s, e] = boardScore(applySequence(board, seq), corner);
    const k: [number, number, number] = [s, e, -i];
    if (!bestKey || k[0] > bestKey[0] || (k[0] === bestKey[0] && (k[1] > bestKey[1] || (k[1] === bestKey[1] && k[2] > bestKey[2])))) {
      bestKey = k; best = cid;
    }
  });
  if (best) return best;
  const single = heuristicMove(board, corner);
  if (!single) return null;
  return seqs.find(([, seq]) => seq[0] === single)?.[0] ?? seqs[0]?.[0] ?? null;
}

// ---------------------------------------------------------------- browser (persistent --connect via CDP, like the jev version)

const VIEWPORT = { width: 1280, height: 1080 };
const CONFIRM_OVERRIDE = "window.confirm = () => true;";
const KEYS: Record<Move, string> = { up: "ArrowUp", right: "ArrowRight", down: "ArrowDown", left: "ArrowLeft" };

function findFreePort(): Promise<number> {
  return new Promise((resolve) => {
    const s = net.createServer();
    s.listen("127.0.0.1", 0, () => {
      const p = (s.address() as net.AddressInfo).port;
      s.close(() => resolve(p));
    });
  });
}

function findChromeExe(): string | null {
  for (const dir of (process.env.PATH ?? "").split(path.delimiter)) {
    for (const name of ["google-chrome", "chromium", "chromium-browser", "chrome"]) {
      const p = path.join(dir, name);
      if (fs.existsSync(p)) return p;
    }
  }
  return null;
}

async function waitCdp(port: number, timeout = 30): Promise<string> {
  const deadline = Date.now() + timeout * 1000;
  while (Date.now() < deadline) {
    try {
      const res = await fetch(`http://127.0.0.1:${port}/json/version`);
      if (res.ok) { await res.json(); return `http://127.0.0.1:${port}`; }
    } catch { /* not up yet */ }
    await sleep(300);
  }
  throw new Error(`Chrome CDP not ready on port ${port}`);
}

async function launchDetachedChrome(userDataDir: string, port: number, headed: boolean): Promise<string> {
  const exe = findChromeExe();
  if (!exe) throw new Error("No Chrome/Chromium found (need google-chrome or `npx playwright install chromium`).");
  fs.mkdirSync(userDataDir, { recursive: true });
  const cmd = [exe, `--remote-debugging-port=${port}`, `--user-data-dir=${userDataDir}`,
    "--no-first-run", "--no-default-browser-check",
    "--disable-dev-shm-usage", "--no-sandbox",
    "--disable-search-engine-choice-screen", "about:blank"];
  if (!headed) cmd.splice(1, 0, "--headless=new", "--disable-gpu");
  else cmd.splice(1, 0, `--window-size=${VIEWPORT.width},${VIEWPORT.height + 100}`);
  const child = spawn(cmd[0]!, cmd.slice(1), { detached: true, stdio: "ignore" });
  child.unref();
  return waitCdp(port);
}

// ---------------------------------------------------------------- main

async function main(): Promise<number> {
  const args = parseArgs(process.argv);
  const vprint = (...a: unknown[]) => { if (args.verbose) console.log(...a); };
  process.on("SIGINT", () => { STOP = true; console.log("\n[signal SIGINT] graceful stop after current move..."); });
  process.on("SIGTERM", () => { STOP = true; console.log("\n[signal SIGTERM] graceful stop after current move..."); });

  const comboMode = args.combo || args.combos !== null;
  let comboFull: ComboSpec[] = [];
  if (comboMode) {
    comboFull = args.combos
      ? parseCombosArg(args.combos).map(([cid, seq]): ComboSpec => [cid, seq, `Custom sequence ${cid}: press in order.`])
      : comboSpecs(args.corner);
    console.log(`[combo] multi-key mode: ${comboFull.length} options, ${comboFull.map(([c]) => c).join(", ")}`);
    console.log("[prompt] instructions:\n  " + buildComboInstructions(args.corner, comboFull));
    console.log("[prompt] criteria:");
    for (const [cid, , why] of comboFull) console.log(`  ${cid}: ${why}`);
  } else {
    console.log("[prompt] instructions:\n  " + buildInstructions(args.corner));
    console.log("[prompt] criteria:");
    for (const [m, t] of Object.entries(buildCriteria(args.corner))) console.log(`  ${m}: ${t}`);
  }
  const comboById = new Map(comboFull.map(([cid, seq]) => [cid, seq] as [string, Move[]]));

  // Load the local model unless --dry-run (heuristic only, no 1.7 GB download).
  let laya: Laya | null = null;
  if (!args.dryRun) {
    console.log("[laya] loading local model (first run downloads ~1.7 GB to ~/.cache/receptron-laya) ...");
    laya = await Laya.load({
      modelDir: args.modelDir,
      onProgress: ({ file, received, total }) => {
        if (total) process.stderr.write(`\r[laya] ${file}: ${((received / total) * 100).toFixed(0)}%   `);
      },
    });
    if (process.stderr.writableLength !== undefined) process.stderr.write("\n");
    console.log(`[laya] ready (config max_len=${laya.config.max_len}, head_max_len=${laya.config.head_max_len})`);
  } else {
    console.log("[dry-run] heuristic only, model not loaded.");
  }

  let browser: Browser | null = null;
  let ownsBrowser = false;
  try {
    let page: Page;
    if (args.connect) {
      let info: { cdp_url?: string; user_data_dir?: string } | null = null;
      if (fs.existsSync(args.connect)) {
        try { info = JSON.parse(fs.readFileSync(args.connect, "utf8")); }
        catch (e) { vprint(`[connect] unreadable ${args.connect}: ${e}; relaunching.`); }
      }
      if (info?.cdp_url) {
        vprint(`[connect] attaching to ${info.cdp_url} ...`);
        browser = await chromium.connectOverCDP(info.cdp_url);
        vprint("[connect] attached. (script exit will NOT kill this browser)");
      } else {
        const port = args.remoteDebuggingPort || await findFreePort();
        const profile = args.userDataDir ?? args.connect + ".profile";
        vprint(`[launch] detached Chrome port=${port} profile=${profile} (${args.headed ? "headed" : "headless"}) ...`);
        const cdp = await launchDetachedChrome(profile, port, args.headed);
        info = { cdp_url: cdp, user_data_dir: profile };
        fs.writeFileSync(args.connect, JSON.stringify(info, null, 2));
        vprint(`[launch] wrote ${args.connect}; re-run with the same --connect to reattach.`);
        browser = await chromium.connectOverCDP(cdp);
      }
      const ctx = browser.contexts()[0] ?? await browser.newContext({ viewport: VIEWPORT });
      page = ctx.pages()[0] ?? await ctx.newPage();
      try { await page.setViewportSize(VIEWPORT); } catch { /* keep old size */ }
    } else {
      vprint("[launch] ephemeral browser (no --connect; closes on exit) ...");
      const launchArgs = ["--no-sandbox", "--disable-dev-shm-usage"];
      if (args.headed) launchArgs.push(`--window-size=${VIEWPORT.width},${VIEWPORT.height + 100}`);
      try {
        browser = await chromium.launch({ headless: !args.headed, channel: "chrome", args: launchArgs });
      } catch (e) {
        vprint(`[launch] channel=chrome failed (${e}); trying bundled chromium ...`);
        browser = await chromium.launch({ headless: !args.headed, args: launchArgs });
      }
      ownsBrowser = true;
      const ctx = await browser.newContext({ viewport: VIEWPORT });
      page = await ctx.newPage();
    }

    await page.addInitScript(CONFIRM_OVERRIDE);
    vprint(`[goto] ${args.url}`);
    try { await page.goto(args.url, { waitUntil: "domcontentloaded", timeout: 30000 }); }
    catch (e) { vprint(`[goto] warning: ${e}`); }
    await page.evaluate(CONFIRM_OVERRIDE);
    // NOTE: .tile-container is empty (hence hidden) until the first tiles
    // render, so wait for attached, not visible.
    await page.waitForSelector(".tile-container", { state: "attached", timeout: 15000 });
    await page.waitForSelector(".game-container", { state: "attached", timeout: 15000 });

    if (args.newGame) {
      vprint("[game] New Game");
      await page.click(".restart-button");
      await sleep(600);
    }
    if (args.startDelaySecs > 0) {
      vprint(`[wait] start in ${args.startDelaySecs}s (--start-delay-secs) ...`);
      const end = Date.now() + args.startDelaySecs * 1000;
      while (Date.now() < end && !STOP) await sleep(200);
    }
    if (args.shotDir) fs.mkdirSync(args.shotDir, { recursive: true });
    const snap = async (tag: string) => {
      if (!args.shotDir) return;
      try { await page.screenshot({ path: path.join(args.shotDir, `${tag}.png`) }); }
      catch (e) { vprint(`[shot] failed: ${e}`); }
    };

    let moves = 0;
    const latencies: number[] = [];
    let tokTotal = 0;
    let endedNoMove = false;
    await snap("move-000");

    const askModel = async (board: Board, score: number): Promise<{
      seqId: string; seq: Move[]; probs: Record<string, number>; dt: number;
    }> => {
      if (comboMode) {
        if (!laya) {
          const cid = heuristicCombo(board, args.corner, [...comboById.entries()]);
          return { seqId: cid ?? "?", seq: comboById.get(cid ?? "") ?? [], probs: {}, dt: 0 };
        }
        const state = {
          game: "4096 (2048 variant), 4x4 grid, rows top-to-bottom, 0 = empty",
          board, score,
          goal: "Merge tiles to reach 4096 and beyond without filling the board.",
          strategy: `Keep the largest tile in the ${CORNER_DESCR[args.corner]}. Prefer 2-4 key sequences; the browser presses them in order at once.`,
          combos: Object.fromEntries([...comboById.entries()].map(([cid, seq]) => [cid, seq.join("+")])),
        };
        const t0 = performance.now();
        const res = await laya.systemOne(state, {
          best_combo: { type: "choice", instructions: buildComboInstructions(args.corner, comboFull), criteria: buildComboCriteria(comboFull) },
        });
        const dt = performance.now() - t0;
        const ans = res.answers.best_combo;
        tokTotal += res.usage.input_tokens ?? 0;
        return { seqId: ans.choice, seq: comboById.get(ans.choice) ?? [], probs: ans.probabilities, dt };
      }
      if (!laya) {
        const m = heuristicMove(board, args.corner);
        return { seqId: m ?? "?", seq: m ? [m] : [], probs: {}, dt: 0 };
      }
      const state = {
        game: "4096 (2048 variant), 4x4 grid, rows top-to-bottom, 0 = empty",
        board, score,
        goal: "Merge tiles to reach 4096 and beyond without filling the board.",
        strategy: `Keep the largest tile in the ${CORNER_DESCR[args.corner]}.`,
      };
      const t0 = performance.now();
      const res = await laya.systemOne(state, {
        best_move: { type: "choice", instructions: buildInstructions(args.corner), criteria: buildCriteria(args.corner) },
      });
      const dt = performance.now() - t0;
      const ans = res.answers.best_move;
      tokTotal += res.usage.input_tokens ?? 0;
      return { seqId: ans.choice, seq: [ans.choice as Move], probs: ans.probabilities, dt };
    };

    while (!STOP) {
      const { board, score, over, won } = await waitSettled(page);
      if (over) { console.log(`[over] game over after ${moves} moves, score=${score}`); vprint(fmtBoard(board)); endedNoMove = true; break; }
      if (won) {
        try { await page.click(".keep-playing-button", { timeout: 2000 }); await sleep(400); continue; }
        catch { /* keep going with banner */ }
      }
      if (args.maxMoves !== null && moves >= args.maxMoves) { console.log(`[done] max-moves=${args.maxMoves} reached, score=${score}`); break; }
      if (!validMoves(board).length) { console.log(`[over] no valid moves detected, score=${score}`); vprint(fmtBoard(board)); endedNoMove = true; break; }

      let { seqId, seq, probs, dt } = await askModel(board, score);
      latencies.push(dt);
      // Model picked a dead combo/move: try next-best by probability, then heuristic.
      const effective = (() => {
        if (comboMode) {
          if (seqId && boardKey(applySequence(board, comboById.get(seqId) ?? [])) !== boardKey(board)) return true;
          const ordered = Object.entries(probs).sort((x, y) => y[1]! - x[1]!).map(([k]) => k);
          const cands = [...ordered, ...comboById.keys()];
          const alt = cands.find((c) => c !== seqId && comboById.has(c) &&
            boardKey(applySequence(board, comboById.get(c)!)) !== boardKey(board));
          vprint(`[warn] combo ${seqId} is no-op; trying ${alt}`);
          const pick = alt ?? heuristicCombo(board, args.corner, [...comboById.entries()]);
          if (!pick) return false;
          seqId = pick; seq = comboById.get(pick) ?? [];
          return seq.length > 0;
        }
        if (seq[0] && validMoves(board).includes(seq[0])) return true;
        const ordered = Object.entries(probs).sort((x, y) => y[1]! - x[1]!).map(([k]) => k as Move);
        const alt = [...ordered, ...validMoves(board)].find((m) => m !== seq[0] && validMoves(board).includes(m));
        vprint(`[warn] model said ${seq[0]} (no-op); trying ${alt}`);
        const pick = alt ?? heuristicMove(board, args.corner);
        if (!pick) return false;
        seqId = pick; seq = [pick];
        return true;
      })();
      if (!effective || !seq.length) { console.log(`[over] no effective move, score=${score}`); vprint(fmtBoard(board)); endedNoMove = true; break; }

      console.log(fmtMoveLine(moves + 1, score, seqId, probs, dt));
      if (args.verbose) {
        console.log(fmtBoard(board));
        console.log(`  -> ${seqId} (${seq.join("+")}) (${dt.toFixed(0)}ms${args.dryRun ? " dry-run" : ""} probs=${JSON.stringify(probs)})`);
      }
      for (const step of seq) {
        if (STOP) break;
        if (args.maxMoves !== null && moves >= args.maxMoves) break;
        const cur = (await snapshot(page)).board;
        await page.keyboard.press(KEYS[step]);
        moves++;
        await sleep(Math.max(50, args.moveDelaySecs * 1000));
        const deadline = Date.now() + 1500;
        while (Date.now() < deadline && !STOP) {
          const nb = (await snapshot(page)).board;
          if (boardKey(nb) !== boardKey(cur)) break;
          await sleep(80);
        }
      }
      if (args.maxMoves !== null && moves >= args.maxMoves) { console.log(`[done] max-moves=${args.maxMoves} reached, score=${score}`); break; }
      await snap(`move-${String(moves).padStart(3, "0")}`);
    }

    if (latencies.length) {
      const avg = latencies.reduce((x, y) => x + y, 0) / latencies.length;
      console.log(`[stats] moves=${moves} model_calls=${latencies.length} ` +
        `avg_latency=${avg.toFixed(0)}ms min=${Math.min(...latencies).toFixed(0)}ms max=${Math.max(...latencies).toFixed(0)}ms ` +
        `input_tokens=${tokTotal}`);
    } else {
      console.log(`[stats] moves=${moves} (no model calls)`);
    }
    await snap("final");
    if (endedNoMove && !STOP && process.stdin.isTTY) {
      console.log("[exit] no more moves - press enter to exit");
      await new Promise<void>((r) => { process.stdin.resume(); process.stdin.once("data", () => r()); });
    }
    return 0;
  } finally {
    if (laya) await laya.close().catch(() => {});
    // Never kill a --connect browser: just detach. Ephemeral: close.
    if (args.connect) {
      try { await browser?.close(); } catch { /* detach-only best effort */ }
      vprint(`[exit] detached; browser stays alive. Reattach: npm start -- --connect ${args.connect}`);
    } else if (browser && ownsBrowser) {
      try { await browser.close(); } catch { /* ignore */ }
    }
  }
}

const code = await main().catch((e) => { console.error(`ERROR: ${e instanceof Error ? e.message : e}`); return 1; });
process.exit(code);
