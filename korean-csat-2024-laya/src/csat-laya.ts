#!/usr/bin/env npx tsx
/**
 * CSAT(수능) 문제를 Laya(System 1)에게 그대로 출제하고 채점하는 프로그램.
 *
 * Sibling ../korean-csat-2024-jev/csat.py 와 같은 문제 풀이를 TypeSafe Jev
 * HTTP API 대신 로컬 https://github.com/receptron/laya 모델로 수행한다
 * (open-source, Jev-compatible, ONNX Runtime — API 키 불필요).
 * 출제 형식(state 텍스트, choice 질문 1개, 채점/출력 스키마)은 jev 버전과
 * 동일하게 유지해 두 백엔드의 결과를 비교할 수 있다.
 *
 * Usage:
 *   npm start -- --file csat2024_jev_full.json --subject-id korean
 *   npm start -- --file csat2024_jev_full.json --subject-id physics1
 *   npm start -- --file csat2024_jev_full.json --subject-id bio1
 *   npm start -- --file csat2024_jev_full.json --subject-id japanese
 *
 * Model weights download from Hugging Face on first use and are cached under
 * ~/.cache/receptron-laya (override: LAYA_CACHE env or --model-dir for a
 * local export from laya's export/export_onnx.py).
 * --dry-run skips the model entirely (wiring test, no download).
 */

import fs from "node:fs";
import os from "node:os";
import { Laya } from "@receptron/laya";

const LABELS = ["①", "②", "③", "④", "⑤"];

type Format = "text" | "table" | "json" | "csv";

interface Args {
  file: string;
  subjectId: string;
  format: Format;
  limit: number;
  output: string | null;
  modelDir: string | undefined;
  repo: string | undefined;
  subfolder: string | undefined;
  revision: string | undefined;
  dryRun: boolean;
}

function parseArgs(argv: string[]): Args {
  const a: Args = {
    file: "",
    subjectId: "",
    format: "text",
    limit: 0,
    output: null,
    modelDir: process.env.LAYA_MODEL_DIR || undefined,
    repo: undefined,
    subfolder: undefined,
    revision: undefined,
    dryRun: false,
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
      case "-f":
      case "--file": a.file = need(t, i); i++; break;
      case "--subject-id": a.subjectId = need(t, i); i++; break;
      case "--format": {
        const v = need(t, i); i++;
        if (v !== "text" && v !== "table" && v !== "json" && v !== "csv")
          throw new Error(`--format must be one of text/table/json/csv (got ${v})`);
        a.format = v;
        break;
      }
      case "--limit": a.limit = parseInt(need(t, i), 10); i++; break;
      case "-o":
      case "--output": a.output = need(t, i); i++; break;
      case "--model-dir": a.modelDir = need(t, i); i++; break;
      case "--repo": a.repo = need(t, i); i++; break;
      case "--subfolder": a.subfolder = need(t, i); i++; break;
      case "--revision": a.revision = need(t, i); i++; break;
      case "--dry-run": a.dryRun = true; break;
      case "--help":
      case "-h":
        console.log(`Usage: csat-laya.ts --file FILE --subject-id ID [options]
  -f, --file FILE      문제 JSON 파일 (예: csat2024_jev_full.json)
  --subject-id ID      과목 id (예: korean, physics1, bio1, japanese)
  --format F           콘솔 표시 형식: text (기본값) | table | json | csv
  --limit N            테스트용: 처음 N문항만 풀이 (0=전체)
  -o, --output PATH    결과 JSON 경로 (기본값: result-csat-<subject>-<machine-id>.json)
  --model-dir DIR      로컬 ONNX 번들 (기본값: 다운로드+캐시; 또는 $LAYA_MODEL_DIR)
  --repo ID            Hugging Face repo (기본값: receptron/laya-onnx)
  --subfolder NAME     repo 안 subfolder (기본값: repo root — English 체크포인트)
  --revision REV       모델 revision pin (기본값: main)
  --dry-run            모델 없이 배선 테스트 (문항 번호로 순환 답안, 다운로드 없음)`);
        process.exit(0);
      default:
        throw new Error(`unknown flag ${t} (see --help)`);
    }
  }
  if (!a.file) throw new Error("--file is required");
  if (!a.subjectId) throw new Error("--subject-id is required");
  return a;
}

// ---------------------------------------------------------------- machine id

function getMachineId(): string {
  try {
    const mid = fs.readFileSync("/etc/machine-id", "utf8").trim().toLowerCase();
    if (mid) {
      const safe = mid.replace(/[^a-z0-9_-]+/g, "-").replace(/^[-_]+|[-_]+$/g, "");
      if (safe) return safe.slice(0, 8);
    }
  } catch { /* fall through to hostname */ }
  try {
    const name = os.hostname().trim().toLowerCase();
    if (name) {
      const safe = name.replace(/[^a-z0-9_-]+/g, "-").replace(/^[-_]+|[-_]+$/g, "");
      if (safe) return safe;
    }
  } catch { /* ignore */ }
  return "unknown";
}

// ---------------------------------------------------------------- questions

type JsonValue = string | number | boolean | null | JsonObject | JsonValue[];
interface JsonObject { [k: string]: JsonValue | undefined; }

function getField(q: JsonObject, ...names: string[]): JsonValue | undefined {
  for (const n of names) {
    const v = q[n];
    if (v !== undefined && v !== null) return v;
  }
  return undefined;
}

function asText(v: JsonValue | undefined): string {
  return typeof v === "string" ? v : v === undefined || v === null ? "" : String(v);
}

function asInt(v: JsonValue | undefined): number | null {
  if (typeof v === "number" && Number.isFinite(v)) return Math.trunc(v);
  if (typeof v === "string" && v.trim() !== "" && Number.isFinite(Number(v))) return Math.trunc(Number(v));
  return null;
}

function loadQuestions(path: string, subjectId: string): { exam: string; subjName: string; qs: JsonObject[] } {
  const data = JSON.parse(fs.readFileSync(path, "utf8")) as JsonObject;
  const items = (data["문항"] ?? data["questions"] ?? []) as JsonObject[];
  const exam = asText(data["시험"] ?? data["exam"]);
  const qs = items
    .filter((q) => {
      const code = asText(getField(q, "subject_code", "과목코드")).trim();
      if (code === subjectId) return true;
      return String(q["id"] ?? "").startsWith(subjectId + "-");
    })
    .sort((x, y) => (asInt(getField(x, "number", "번호")) ?? 0) - (asInt(getField(y, "number", "번호")) ?? 0));
  if (!qs.length) {
    const avail = [...new Set(items.map((q) => String(getField(q, "subject_code", "과목코드") ?? "")))].sort();
    throw new Error(`과목 '${subjectId}' 문항이 없습니다. 파일 내 과목: ${JSON.stringify(avail)}`);
  }
  const subjName = asText(getField(qs[0]!, "과목명", "subject_name")) || subjectId;
  return { exam, subjName, qs };
}

// ---------------------------------------------------------------- prompt building (same shape as the jev version)

function buildState(q: JsonObject): string {
  const passage = asText(getField(q, "지문", "passage_text"));
  const passageRef = getField(q, "지문번호", "passage_ref");
  const question = asText(getField(q, "문제", "question"));
  const choices = (getField(q, "보기", "choices") ?? []) as JsonValue[];
  const lines: string[] = [];
  if (passageRef !== undefined && passageRef !== null && String(passageRef) !== "")
    lines.push(`[지문 ${String(passageRef)}]`);
  if (passage) {
    lines.push(passage.trim());
    lines.push("");
  }
  lines.push("[문제]");
  lines.push(question.trim());
  lines.push("");
  lines.push("[보기]");
  choices.forEach((c, i) => {
    const text = (typeof c === "object" && c !== null ? asText((c as JsonObject)["text"]) : String(c)).trim();
    lines.push(`${i < 5 ? LABELS[i] : `(${i + 1})`} ${text}`);
  });
  if (getField(q, "그림포함", "has_figure")) {
    lines.push("");
    lines.push("(참고: 원본 문항에 그림/도표가 포함되어 있으나 텍스트로만 출제한다.)");
  }
  return lines.join("\n");
}

function buildCriteria(q: JsonObject): Record<string, string> {
  const choices = (getField(q, "보기", "choices") ?? []) as JsonValue[];
  const criteria: Record<string, string> = {};
  choices.forEach((c, i) => {
    const text = (typeof c === "object" && c !== null ? asText((c as JsonObject)["text"]) : String(c)).trim();
    if (text) criteria[String(i + 1)] = text;
  });
  return criteria;
}

const INSTRUCTIONS = "위 대학수학능력시험 문제의 정답으로 가장 적절한 보기를 반드시 하나만 고르시오.";

function labelOf(n: number | null | undefined): string {
  return typeof n === "number" && n >= 1 && n <= 5 ? LABELS[n - 1]! : "?";
}

/** Laya의 choice 응답('5' 등)을 정답 번호 int로 변환. */
function parseChoice(raw: unknown, nChoices: number): number | null {
  const n = parseInt(String(raw ?? "").trim(), 10);
  if (Number.isInteger(n) && (n as number) >= 1 && (n as number) <= nChoices) return n as number;
  const s = String(raw ?? "").trim();
  if (LABELS.includes(s)) return LABELS.indexOf(s) + 1;
  return null;
}

// ---------------------------------------------------------------- rendering (same formats as the jev version)

interface Row {
  id: string; number: number; points: number; nChoices: number;
  answer: number; answerLabel: string;
  layaAnswer: number | null; layaLabel: string;
  layaChoiceRaw: unknown; confidence: number | null;
  probabilities: Record<string, number>; score: number; correct: boolean;
}

interface Excluded {
  id: string; number: number; points: number; nChoices: number;
  answer: number; answerLabel: string; reason: string;
}

function summaryLine(total: number, maxTotal: number, excluded: Excluded[]): string {
  if (excluded.length) {
    const exPts = excluded.reduce((s, e) => s + e.points, 0);
    const orig = maxTotal + exPts;
    let base = `합산 점수: ${total}/${maxTotal} (원만점 ${orig}에서 ${excluded.length}문항 ${exPts}점 제외`;
    if (maxTotal !== 100 && maxTotal) base += `, 백분률 환산: ${(total / maxTotal * 100).toFixed(1)}점`;
    return base + ")";
  }
  if (maxTotal !== 100) {
    const pct = maxTotal ? (total / maxTotal * 100).toFixed(1) : "0.0";
    return `합산 점수: ${total}/${maxTotal} (백분률 환산: ${pct}점)`;
  }
  return `합산 점수: ${total}/${maxTotal}`;
}

function renderText(rows: Row[], total: number, maxTotal: number, excluded: Excluded[]): string {
  const out = rows.map((r) =>
    `${r.id} 번호=${r.number} 배점=${r.points} 보기수=${r.nChoices} ` +
    `정답=${r.answerLabel}(${r.answer}) laya=${r.layaLabel}(${r.layaAnswer}) ` +
    `점수=${r.score} ${r.correct ? "O" : "X"}`);
  for (const e of excluded)
    out.push(`${e.id} 번호=${e.number} 배점=${e.points} 제외(이미지/그림 필요) 점수=제외 -`);
  out.push(summaryLine(total, maxTotal, excluded));
  return out.join("\n");
}

function renderTable(rows: Row[], total: number, maxTotal: number, excluded: Excluded[]): string {
  const cols = ["과목id", "번호", "배점", "보기수", "정답", "laya답", "점수"];
  const data: string[][] = rows.map((r) => [
    r.id, String(r.number), String(r.points), String(r.nChoices),
    `${r.answerLabel}(${r.answer})`, `${r.layaLabel}(${r.layaAnswer})`, String(r.score),
  ]);
  for (const e of excluded)
    data.push([e.id, String(e.number), String(e.points), "0", `${e.answerLabel}(${e.answer})`, "제외", "제외"]);
  const widths = cols.map((c) => c.length);
  for (const row of data) row.forEach((c, i) => { widths[i] = Math.max(widths[i]!, c.length); });
  const fmt = (row: string[]) => row.map((c, i) => c.padEnd(widths[i]!)).join("  ");
  return [fmt(cols), widths.map((w) => "-".repeat(w)).join("  "),
    ...data.map(fmt), summaryLine(total, maxTotal, excluded)].join("\n");
}

function csvCell(v: unknown): string {
  const s = String(v ?? "");
  return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
}

function renderCsv(rows: Row[], total: number, maxTotal: number, excluded: Excluded[]): string {
  const lines = [["과목id", "번호", "배점", "보기수", "정답", "laya답", "점수"].map(csvCell).join(",")];
  for (const r of rows)
    lines.push([r.id, r.number, r.points, r.nChoices, r.answer, r.layaAnswer, r.score].map(csvCell).join(","));
  for (const e of excluded)
    lines.push([e.id, e.number, e.points, 0, e.answer, "제외", "제외"].map(csvCell).join(","));
  lines.push("");
  lines.push(["합산점수", total, "만점", maxTotal].map(csvCell).join(","));
  if (excluded.length) {
    const exPts = excluded.reduce((s, e) => s + e.points, 0);
    lines.push(["제외문항", excluded.length, "제외점수", exPts].map(csvCell).join(","));
  }
  if (maxTotal !== 100) lines.push(["백분률환산", (total / maxTotal * 100).toFixed(1)].map(csvCell).join(","));
  return lines.join("\n");
}

// ---------------------------------------------------------------- main

async function main(): Promise<number> {
  const args = parseArgs(process.argv);

  const { exam, subjName, qs: allQs } = loadQuestions(args.file, args.subjectId);
  const qs = args.limit > 0 ? allQs.slice(0, args.limit) : allQs;

  let laya: Laya | null = null;
  let modelUsed = "dry-run";
  if (!args.dryRun) {
    console.error("[laya] loading local model (first run downloads weights to ~/.cache/receptron-laya) ...");
    laya = await Laya.load({
      modelDir: args.modelDir,
      repo: args.repo,
      subfolder: args.subfolder,
      revision: args.revision,
      onProgress: ({ file, received, total }) => {
        if (total) process.stderr.write(`\r[laya] ${file}: ${((received / total) * 100).toFixed(0)}%   `);
      },
    });
    process.stderr.write("\n");
    console.error(`[laya] ready (config max_len=${laya.config.max_len}, head_max_len=${laya.config.head_max_len})`);
  } else {
    console.error("[dry-run] heuristic wiring test only, model not loaded.");
  }

  try {
    const rows: Row[] = [];
    const excluded: Excluded[] = [];
    let total = 0;
    let maxTotal = 0;

    for (let i = 0; i < qs.length; i++) {
      const q = qs[i]!;
      const number = asInt(getField(q, "number", "번호")) ?? i + 1;
      const qid = asText(q["id"]) || `${args.subjectId}-${String(number).padStart(2, "0")}`;
      const points = asInt(getField(q, "points", "배점")) ?? 0;
      let answer = asInt(getField(q, "answer", "정답번호"));
      if (answer === null) {
        const a = asText(getField(q, "answer_label", "정답"));
        answer = LABELS.includes(a) ? LABELS.indexOf(a) + 1 : null;
      }
      if (answer === null) throw new Error(`${qid}: 정답 번호를 읽을 수 없습니다.`);
      const criteria = buildCriteria(q);
      const nChoices = Object.keys(criteria).length;

      if (nChoices === 0) {
        excluded.push({
          id: qid, number, points, nChoices: 0,
          answer, answerLabel: labelOf(answer),
          reason: "보기 없음(이미지 선택지/그림 필요)",
        });
        console.error(`[${i + 1}/${qs.length}] ${qid}: 그림/이미지 문항이므로 제외 (배점 ${points}점)`);
        continue;
      }

      let choiceRaw: unknown;
      let confidence: number | null = null;
      let probabilities: Record<string, number> = {};
      if (laya) {
        const res = await laya.systemOne(buildState(q), {
          answer: { type: "choice", instructions: INSTRUCTIONS, criteria },
        });
        const ans = res.answers.answer;
        choiceRaw = ans.choice;
        confidence = ans.confidence;
        probabilities = ans.probabilities;
        modelUsed = res.model;
      } else {
        // wiring test: rotate through the options by question number
        choiceRaw = String((number % nChoices) + 1);
        confidence = 1 / nChoices;
        probabilities = Object.fromEntries(Object.keys(criteria).map((k) => [k, 1 / nChoices]));
      }

      const layaAnswer = parseChoice(choiceRaw, nChoices);
      const correct = layaAnswer === answer;
      const score = correct ? points : 0;
      total += score;
      maxTotal += points;
      rows.push({
        id: qid, number, points, nChoices, answer,
        answerLabel: labelOf(answer), layaAnswer,
        layaLabel: layaAnswer ? labelOf(layaAnswer) : "?",
        layaChoiceRaw: choiceRaw, confidence, probabilities, score, correct,
      });
      console.error(
        `[${i + 1}/${qs.length}] ${qid}: 정답 ${labelOf(answer)}(${answer}) ` +
        `laya ${layaAnswer ? labelOf(layaAnswer) : "?"}(${layaAnswer}) ${correct ? "O" : "X"}`,
      );
    }

    const pct = maxTotal ? Math.round((total / maxTotal) * 1000) / 10 : 0.0;
    const excludedScore = excluded.reduce((s, e) => s + e.points, 0);
    const result = {
      exam,
      subject_id: args.subjectId,
      subject_name: subjName,
      model: modelUsed,
      total_questions: rows.length,
      excluded_count: excluded.length,
      excluded_score: excludedScore,
      original_max_score: maxTotal + excludedScore,
      max_score: maxTotal,
      total_score: total,
      percentage: pct,
      excluded_items: excluded,
      items: rows,
    };

    const outPath = args.output ?? `result-csat-${args.subjectId}-${getMachineId()}.json`;
    fs.writeFileSync(outPath, JSON.stringify(result, null, 2) + "\n", "utf8");
    console.error(`결과 저장: ${outPath}`);

    if (args.format === "json") console.log(JSON.stringify(result, null, 2));
    else if (args.format === "table") console.log(renderTable(rows, total, maxTotal, excluded));
    else if (args.format === "csv") console.log(renderCsv(rows, total, maxTotal, excluded));
    else console.log(renderText(rows, total, maxTotal, excluded));
    return 0;
  } finally {
    if (laya) await laya.close().catch(() => {});
  }
}

const code = await main().catch((e) => {
  console.error(`ERROR: ${e instanceof Error ? e.message : e}`);
  return 1;
});
process.exit(code);
