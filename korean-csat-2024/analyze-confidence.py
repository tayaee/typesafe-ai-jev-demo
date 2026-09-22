#!/usr/bin/env python3
"""result-csat-*.json의 confidence를 기준으로 목표 정확도를 달성하기 위한 기각 임계값 분석.

정확도 = 정답 / (정답 + 오답), 모름(기각) 처리한 문항은 제외.
규칙: confidence <= 임계값 → 모름 처리, 나머지로 정확도 계산.

사용법:
    uv run analyze-confidence.py FILE... [--target-accuracy 0.75 0.90 0.95 0.99]
        [--detail] [--format text|json|csv]

    uv run analyze-confidence.py result-csat-*.json
    uv run analyze-confidence.py result-csat-korean-*.json --target-accuracy 0.95 0.99 --detail
"""

import argparse
import csv
import io
import json
import sys
import unicodedata


def parse_args(argv=None):
    p = argparse.ArgumentParser(
        description="confidence 기준 기각 임계값을 분석한다 "
        "(정확도 = 정답/(정답+오답), 모름 제외)."
    )
    p.add_argument("files", nargs="+", help="결과 JSON 파일 (예: result-csat-*.json)")
    p.add_argument(
        "--target-accuracy",
        nargs="+",
        type=float,
        default=[0.75, 0.90, 0.95, 0.99],
        help="목표 정확도 목록 (기본값: 0.75 0.90 0.95 0.99)",
    )
    p.add_argument(
        "--detail",
        action="store_true",
        help="임계값 스윕 테이블(임계값/유지/기각/정답률)도 함께 출력",
    )
    p.add_argument(
        "--format",
        default="text",
        choices=["text", "json", "csv"],
        help="출력 형식 (기본값: text)",
    )
    return p.parse_args(argv)


def pct(x):
    return f"{x * 100:.1f}%"


def fmt_target(t):
    return f"{t * 100:g}%"


def fmt_threshold(t):
    return f"{t:g}"


def check_items(items, path):
    for it in items:
        if it.get("confidence") is None:
            raise SystemExit(f"{path}: '{it.get('id')}' 문항에 confidence가 없습니다.")


def accuracy_of(kept):
    return sum(1 for it in kept if it["correct"]) / len(kept)


def analyze(items, target):
    """목표를 만족하는 가장 작은 임계값(= 기각 수 최소)을 찾는다."""
    n = len(items)
    base = accuracy_of(items)
    if base >= target:
        return {
            "status": "no_reject",
            "threshold": None,
            "rejected": 0,
            "kept": n,
            "accuracy": base,
        }
    uniq = sorted(set(it["confidence"] for it in items))
    for t in uniq:
        kept = [it for it in items if it["confidence"] > t]
        if not kept:
            break
        acc = accuracy_of(kept)
        if acc >= target:
            return {
                "status": "achieved",
                "threshold": t,
                "rejected": n - len(kept),
                "kept": len(kept),
                "accuracy": acc,
            }
    # 달성 불가: 전 구간(기각 없음 포함, 유지 0 제외) 최고 정답률 보고
    best = {"accuracy": base, "kept": n, "threshold": None}
    for t in uniq:
        kept = [it for it in items if it["confidence"] > t]
        if not kept:
            continue
        acc = accuracy_of(kept)
        if acc > best["accuracy"] or (
            acc == best["accuracy"] and len(kept) > best["kept"]
        ):
            best = {"accuracy": acc, "kept": len(kept), "threshold": t}
    return {
        "status": "unreachable",
        "threshold": None,
        "rejected": None,
        "kept": None,
        "accuracy": None,
        "best_accuracy": best["accuracy"],
        "best_kept": best["kept"],
    }


def sweep_rows(items):
    """(임계값, 유지, 기각, 정답률) 행. 첫 행은 기각 없음."""
    n = len(items)
    rows = [(None, n, 0, accuracy_of(items))]
    for t in sorted(set(it["confidence"] for it in items)):
        kept = [it for it in items if it["confidence"] > t]
        acc = accuracy_of(kept) if kept else None
        rows.append((t, len(kept), n - len(kept), acc))
    return rows


def _dlen(s):
    return sum(2 if unicodedata.east_asian_width(c) in ("F", "W") else 1 for c in s)


def _pad(s, w, align="<"):
    rem = max(0, w - _dlen(s))
    if align == ">":
        return " " * rem + s
    elif align == "^":
        l = rem // 2
        return " " * l + s + " " * (rem - l)
    return s + " " * rem


def render_text(path, subject, items, targets, detail):
    n = len(items)
    base_acc = accuracy_of(items)
    out = [
        f"=== {path} (전체 {n}문항, 전체 정답률 {pct(base_acc)})",
        "※ 목표 accuracy 확보를 위한 confidence 기각 기준과 수용률:",
    ]
    headers = ["목표", "기각 기준", "기각 / 수용", "수용률"]
    widths = [6, 13, 13, 8]
    out.append("  " + " | ".join(_pad(h, w, "^") for h, w in zip(headers, widths)))

    for t in targets:
        r = analyze(items, t)
        tgt_s = fmt_target(t)
        if r["status"] == "no_reject":
            criteria = "기각 없음"
            rej_kept = f"0 / {n}"
            acc_rate = "100.0%"
        elif r["status"] == "achieved":
            criteria = f"conf ≤ {fmt_threshold(r['threshold'])}"
            rej_kept = f"{r['rejected']} / {r['kept']}"
            acc_rate = pct(r["kept"] / n)
        else:
            criteria = "달성 불가"
            rej_kept = "-"
            acc_rate = f"(최고 {pct(r['best_accuracy'])})"
        row = [
            _pad(tgt_s, widths[0], "^"),
            _pad(criteria, widths[1], "<"),
            _pad(rej_kept, widths[2], "^"),
            _pad(acc_rate, widths[3], ">"),
        ]
        out.append("  " + " | ".join(row))

    if detail:
        out.append("")
        out.append(f"--- {subject or path} 스윕 테이블 (임계값 이하 기각)")
        out.append(f"{'임계값':>8}  {'유지':>4}  {'기각':>4}  {'정답률':>7}")
        for th, kept, rej, acc in sweep_rows(items):
            th_s = "-(기각 없음)" if th is None else fmt_threshold(th)
            acc_s = pct(acc) if acc is not None else "-"
            out.append(f"{th_s:>8}  {kept:>4}  {rej:>4}  {acc_s:>7}")
    return "\n".join(out)


def render_json(results):
    return json.dumps(results, ensure_ascii=False, indent=2)


def render_csv(results):
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["file", "subject", "total", "base_accuracy", "target",
                "threshold", "rejected", "kept", "accuracy", "status"])
    for r in results:
        for t in r["targets"]:
            w.writerow([r["file"], r["subject"], r["total"], f'{r["base_accuracy"]:.4f}',
                        t["target"], t["threshold"], t["rejected"], t["kept"],
                        f'{t["accuracy"]:.4f}' if t["accuracy"] is not None else "",
                        t["status"]])
    return buf.getvalue().rstrip("\n")


def main(argv=None):
    args = parse_args(argv)
    targets = sorted(set(args.target_accuracy))
    for t in targets:
        if not 0 < t <= 1:
            raise SystemExit(f"--target-accuracy 값 오류: {t} (0 < t <= 1 이어야 함)")

    results = []
    for path in args.files:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        items = data.get("items", [])
        if not items:
            raise SystemExit(f"{path}: 문항(items)이 없습니다.")
        check_items(items, path)
        subject = data.get("subject_id") or data.get("subject_name") or ""
        entry = {
            "file": path,
            "subject": subject,
            "total": len(items),
            "base_accuracy": accuracy_of(items),
            "targets": [],
        }
        for t in targets:
            r = analyze(items, t)
            entry["targets"].append({
                "target": t,
                "status": r["status"],
                "threshold": r["threshold"],
                "rejected": r["rejected"],
                "kept": r["kept"],
                "accuracy": r["accuracy"],
            })
        results.append(entry)

    if args.format == "json":
        print(render_json(results))
    elif args.format == "csv":
        print(render_csv(results))
    else:
        blocks = []
        for path, r in zip(args.files, results):
            with open(path, encoding="utf-8") as f:
                items = json.load(f)["items"]
            blocks.append(render_text(path, r["subject"], items, targets, args.detail))
        print("\n\n".join(blocks))


if __name__ == "__main__":
    main()
