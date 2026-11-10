#!/usr/bin/env python3
"""loop_next.py - close the loop: turn the last video's results into
the next video's brief.

Reads the latest run's 08-report.md (+ the retention CSV when one
exists), writes 10-next-plan.md with concrete adjustments, AND
writes next-brief.json - a small machine-readable brief the next
run's Plan stage reads automatically when present.

    python3 scripts/loop_next.py --out-dir out/<run>/
    python3 scripts/loop_next.py --out-dir out/<new-run>/
        --prev-out out/<last-run>/ --retention retention.csv

Finding the report: --prev-out wins; otherwise the most recent
sibling directory of --out-dir that holds an 08-report.md; else
--out-dir's own 08-report.md. Retention: --retention wins, else a
retention.csv sitting next to the report that was read.

Adjustments are rule-based and honest - only numbers actually
present in the report are used, never estimated:
    - hook leak >= 30%  -> rewrite the hook; the payoff must land
      in the first 3 seconds; re-score with hookscore.py.
    - a cliff of -10%+  -> rework or cut the segment at that point;
      move its payoff earlier.
    - end retention >= 50% -> keep the ending/CTA shape; it holds.
    - start retention low -> the title/thumbnail promised more
      than the opening delivered; align them.
If no report and no retention exist, both files say so honestly
and list exactly what to collect (publish first, then the
retention export from YouTube Studio) - no adjustments are
invented from nothing.

next-brief.json shape:
    {"status": "ok" | "no-data", "source_run": "...",
     "keep": [...], "change": [...],
     "next_topic_angle": "...", "date": "YYYY-MM-DD"}
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from datetime import date
from pathlib import Path

HOOK_LEAK_RE = re.compile(r"Hook leak:\s*([\d.]+)%")
CLIFF_RE = re.compile(r"Cliff:\s*-([\d.]+)%\s+at\s+([^\n]+)")
POINTS_RE = re.compile(r"Points read:\s*(\d+)")
START_END_RE = re.compile(r"Start [^:]*:\s*([\d.]+)%\s*→\s*([\d.]+)%")


def _read_report(path: Path) -> str | None:
    if path.exists():
        return path.read_text(encoding="utf-8")
    return None


def find_report(out_dir: Path, prev_out: Path | None) -> tuple[str | None,
                                                              Path | None]:
    """Return (report text, report dir). Search order: --prev-out,
    most recent sibling run dir with 08-report.md, own out dir."""
    candidates: list[Path] = []
    if prev_out is not None:
        candidates.append(prev_out)
    parent = out_dir.parent
    if parent.exists():
        siblings = sorted(
            (p for p in parent.iterdir()
             if p.is_dir() and p != out_dir
             and (p / "08-report.md").exists()),
            key=lambda p: p.stat().st_mtime, reverse=True)
        candidates.extend(siblings)
    candidates.append(out_dir)
    for cand in candidates:
        text = _read_report(cand / "08-report.md")
        if text is not None:
            return text, cand
    return None, None


def find_retention(report_dir: Path | None, explicit: Path | None,
                   out_dir: Path) -> Path | None:
    if explicit is not None and explicit.exists():
        return explicit
    for base in (report_dir, out_dir):
        if base is not None and (base / "retention.csv").exists():
            return base / "retention.csv"
    return None


def parse_retention(path: Path) -> dict | None:
    """Read a YouTube Studio retention export, if it parses. The
    export is two columns (seconds, retention %) or (time, %)."""
    try:
        with open(path, encoding="utf-8", newline="") as fh:
            rows = list(csv.reader(fh))
    except (OSError, csv.Error):
        return None
    points = []
    for row in rows:
        if len(row) < 2:
            continue
        try:
            points.append((float(row[0]), float(row[1])))
        except ValueError:
            continue  # header row
    if len(points) < 5:
        return None
    start = points[0][1]
    end = points[-1][1]
    # The hook is judged on the first seconds: the last sample at or
    # before 10s (else the second sample - the first is the start).
    early = [p for p in points if p[0] <= 10]
    hook = (early[-1][1] if early else points[1][1])
    return {
        "points": len(points),
        "start": start,
        "end": end,
        "hook_leak": round(start - hook, 1),
    }


def parse_report(text: str) -> dict:
    """Pull only the numbers the report actually printed."""
    data: dict = {"hook_leak": None, "cliffs": [], "points": None,
                  "start": None, "end": None}
    m = HOOK_LEAK_RE.search(text)
    if m:
        data["hook_leak"] = float(m.group(1))
    for lost, at in CLIFF_RE.findall(text):
        data["cliffs"].append({"lost": float(lost), "at": at.strip()})
    m = POINTS_RE.search(text)
    if m:
        data["points"] = int(m.group(1))
    m = START_END_RE.search(text)
    if m:
        data["start"] = float(m.group(1))
        data["end"] = float(m.group(2))
    return data


def build_adjustments(report: dict, retention: dict | None) -> tuple[
        list[str], list[str], str]:
    """(keep, change, next_topic_angle) - rule-based, no invented
    numbers. Every line names the number it came from."""
    keep: list[str] = []
    change: list[str] = []
    leak = report.get("hook_leak")
    if retention is not None and retention.get("hook_leak") is not None:
        leak = retention["hook_leak"]
    if leak is not None:
        if leak >= 30:
            change.append(
                f"Hook leaks {leak:g}% in the opening - rewrite the "
                "hook so the payoff lands in the first 3 seconds, "
                "then re-score it with hookscore.py before filming.")
        elif leak >= 15:
            change.append(
                f"Hook leaks {leak:g}% - tighten the opening: cut the "
                "setup and start on the payoff line.")
        else:
            keep.append(f"Opening holds (only {leak:g}% leak) - keep "
                        "the hook shape.")
    for cliff in report.get("cliffs", []):
        if cliff["lost"] >= 10:
            change.append(
                f"Cliff of -{cliff['lost']:g}% at {cliff['at']} - "
                "rework or cut that segment; move its payoff "
                "earlier in the video.")
    end = report.get("end")
    if retention is not None:
        end = retention.get("end")
    if end is not None:
        if end >= 50:
            keep.append(f"Ending holds at {end:g}% retention - keep "
                        "the end-card / CTA shape.")
        elif end < 25:
            change.append(
                f"Only {end:g}% watch to the end - shorten the video "
                "or move the CTA earlier; the ending is not earning "
                "its time.")
    if not keep and not change:
        change.append("No usable numbers were found in the report - "
                      "collect the retention export before judging "
                      "this video.")
    angle = ("Keep the same topic, new angle: open on the payoff, "
             "cut the weakest segment found above.")
    if not change:
        angle = ("Same topic family, next angle from "
                 "02-concept-score.md - the last video held, so push "
                 "the next concept, not the same one.")
    return keep, change, angle


def build_plan(out_dir: Path, prev_out: Path | None,
               retention_path: Path | None) -> dict:
    """Write 10-next-plan.md + next-brief.json into out_dir.
    Returns the brief dict."""
    report_text, report_dir = find_report(out_dir, prev_out)
    retention_file = find_retention(report_dir, retention_path, out_dir)
    retention = (parse_retention(retention_file)
                 if retention_file is not None else None)
    today = date.today().isoformat()
    source = (str(report_dir) if report_dir is not None else None)

    report = parse_report(report_text or "") if report_text else {}
    has_numbers = bool(
        report.get("hook_leak") is not None
        or report.get("cliffs") or report.get("points") is not None
        or report.get("start") is not None) or retention is not None
    if not has_numbers:
        # No report at all, or a report that holds no performance
        # numbers yet (e.g. this run's own template report) and no
        # retention CSV: there is nothing to learn from yet, and
        # nothing is invented.
        brief = {
            "status": "no-data",
            "date": today,
            "source_run": None,
            "keep": [],
            "change": [],
            "next_topic_angle": ("[no data yet - reuse the last "
                                 "topic angle, or pick the next "
                                 "concept from 02-concept-score.md]"),
            "collect": [
                "Publish the video first (gate: upload it).",
                "Wait for real views, then export the retention CSV "
                "from YouTube Studio (Analytics -> a video -> "
                "Engagement -> audience retention -> download).",
                "Re-run with --retention retention.csv (or put the "
                "CSV next to 08-report.md) so the loop has numbers.",
            ],
        }
        found_note = ""
        if report_dir is not None:
            found_note = (f"A report was found ({report_dir}) but it "
                          "holds no performance numbers yet - the "
                          "video it describes has not been published "
                          "or measured.\n\n")
        text = ("# Stage 10 - Next plan (closed loop)\n\n"
                f"Date: {today}\n"
                "Mode: mock (no live model, no network, $0). "
                "Gate: nothing publishes without the owner's exact "
                "word.\n\n---\n"
                "## No performance data yet\n\n"
                + found_note +
                "No retention CSV was found either, so there is "
                "nothing to learn from yet - and nothing was "
                "invented.\n\n"
                "## What to collect\n\n"
                + "".join(f"- {c}\n" for c in brief["collect"])
                + "\n## Next topic angle\n\n"
                f"{brief['next_topic_angle']}\n")
        (out_dir / "10-next-plan.md").write_text(text, encoding="utf-8")
        (out_dir / "next-brief.json").write_text(
            json.dumps(brief, indent=1), encoding="utf-8")
        return brief

    if retention is not None and report.get("points") is None:
        report["points"] = retention["points"]
    keep, change, angle = build_adjustments(report, retention)
    brief = {
        "status": "ok",
        "date": today,
        "source_run": source,
        "keep": keep,
        "change": change,
        "next_topic_angle": angle,
        "numbers_used": {
            "hook_leak": report.get("hook_leak"),
            "cliffs": report.get("cliffs"),
            "points": report.get("points"),
            "start": report.get("start"),
            "end": (retention or {}).get("end", report.get("end")),
        },
    }
    lines = [
        "# Stage 10 - Next plan (closed loop)\n",
        f"Date: {today}\n",
        f"Source run: {source or '[this run]'}\n",
        ("Retention file: "
         f"{retention_file if retention_file is not None else '[none]'}\n"),
        "Mode: mock (no live model, no network, $0). "
        "Gate: nothing publishes without the owner's exact word.\n",
        "\n---\n",
        "## Keep (what worked)\n",
    ]
    lines += [f"- {k}\n" for k in keep] or ["- [nothing measured yet]\n"]
    lines += ["\n## Change (what to fix next time)\n"]
    lines += [f"- {c}\n" for c in change] or ["- [nothing measured yet]\n"]
    lines += ["\n## Next topic angle\n\n", angle + "\n",
              "\nThis brief was also saved as `next-brief.json` - "
              "the next run's Plan stage reads it automatically.\n"]
    (out_dir / "10-next-plan.md").write_text(
        "".join(lines), encoding="utf-8")
    (out_dir / "next-brief.json").write_text(
        json.dumps(brief, indent=1), encoding="utf-8")
    return brief


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description="Closed feedback loop: read the last run's "
                    "08-report.md (+ retention CSV), write "
                    "10-next-plan.md and next-brief.json. No network, "
                    "no keys, $0. Honest when there is no data yet.")
    ap.add_argument("--out-dir", required=True,
                    help="This run's output dir (files are written here).")
    ap.add_argument("--prev-out", default="",
                    help="Previous run's output dir (default: most "
                         "recent sibling dir with 08-report.md).")
    ap.add_argument("--retention", default="",
                    help="Retention CSV export (default: retention.csv "
                         "next to the report, if present).")
    ap.add_argument("--json", action="store_true",
                    help="Print the brief as JSON.")
    return ap


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    prev_out = Path(args.prev_out) if args.prev_out else None
    retention = Path(args.retention) if args.retention else None
    brief = build_plan(out_dir, prev_out, retention)
    if args.json:
        print(json.dumps(brief, indent=1))
    else:
        status = brief["status"]
        print(f"loop: status={status} "
              f"-> {out_dir / '10-next-plan.md'}")
        print(f"brief: {out_dir / 'next-brief.json'}")
        for item in brief["change"]:
            print(f"  change: {item}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
