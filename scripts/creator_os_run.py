#!/usr/bin/env python3
"""Creator OS — combined pipeline runner (mock mode, $0).

One idea in, eight stage drafts out. Each stage runs the Creator
Studio worker AND the matching YouTube skill/tool where one exists:

  0. Plan         — yt-plan (weekly plan, from hours available)
  1. Research     — TopicResearcher + yt-viral swipe.py
  2. Script       — ScriptWriter + yt-script hookscore.py (21 formulas)
  3. Visual+Pack  — VisualProducer + yt-package title.py (title+thumb)
  4. Edit         — yt-edit deadair.py + yt-chapters chapters.py
                    + yt-shorts (needs --transcript, else skipped honestly)
  5. Caption+SEO  — CaptionWriter + yt-seo (description/tags)
  6. Publish prep — PublishPrep ONLY (prepare, never publish)
  7. Report       — PerformanceTracker + yt-retention retention.py
                    (+ yt-audit, yt-comment — post-publish only)

Usage:
  python3 scripts/creator_os_run.py --topic "AI receptionist for plumbers" \
      --format "short video" [--niche ...] [--audience ...]
      [--transcript transcript.srt] [--retention retention.csv]
      [--collected collected.json] [--hours 6] [--out out/dir]

Mock mode is the DEFAULT: the workers draft through MockLLM (offline,
deterministic, $0) and the YouTube tools are local Python with no
network and no keys. Nothing here publishes, sends, uploads, schedules,
spends, or touches media. The run ends with "ship it, or change it?"
and exits — the owner publishes, if at all, with their own word.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.creator_workers import (  # noqa: E402
    CaptionWriter,
    PerformanceTracker,
    PublishPrep,
    ScriptWriter,
    TopicResearcher,
    VisualProducer,
)
from src.workers.base import MockLLM, Task  # noqa: E402

SKILLS = ROOT / "youtube-skills"
FORMATS = ["short video", "long video", "carousel", "image", "blog",
           "podcast"]
GATE_NOTE = "Gate: nothing publishes without the owner's exact word."


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug or "untitled"


def run_tool(tool: Path, args: list[str]) -> tuple[bool, str]:
    """Run a local YouTube tool (stdlib only, no network) and capture it.

    Returns (ok, stdout-or-error-text). A tool failure never crashes
    the run — it is recorded honestly in the stage file instead.
    """
    if not tool.exists():
        return False, f"tool missing: {tool} (not run)"
    try:
        proc = subprocess.run(
            [sys.executable, str(tool), *args],
            capture_output=True, text=True, timeout=60, cwd=str(ROOT),
        )
    except subprocess.TimeoutExpired:
        return False, f"tool timed out after 60s: {tool.name} (not run)"
    except Exception as exc:  # noqa: BLE001 - record, don't crash
        return False, f"tool could not start ({tool.name}): {exc}"
    out = proc.stdout.strip()
    if proc.returncode != 0:
        detail = out or proc.stderr.strip() or "no output"
        return False, f"{tool.name} exited {proc.returncode}: {detail}"
    return True, out


def run_worker(cls, payload: dict, llm: MockLLM):
    """Run one Creator Studio worker in mock mode; returns its result."""
    worker = cls(f"CRT-{cls.__name__}", "creator-biz-01", "CRT",
                 cls.__name__, llm)
    task = Task(task_id=f"{cls.task_kind}", business_id="creator-biz-01",
                division_id="CRT", kind=cls.task_kind, payload=payload)
    return worker.execute(task)


def stage_header(num: int, title: str, sources: str, gate: str) -> str:
    return (f"# Stage {num} — {title}\n\n"
            f"Sources: {sources}\n"
            f"Mode: mock (no live model, no network, $0). {GATE_NOTE}\n"
            f"Gate: `{gate}`\n\n---\n")


def write_stage(out_dir: Path, name: str, text: str) -> Path:
    path = out_dir / name
    path.write_text(text, encoding="utf-8")
    return path


def derive_hook(topic: str) -> str:
    """Draft hook line, templated from the topic. Rewrite before filming."""
    return f"{topic} — what most people get wrong, and the one fix that matters."


def derive_title(topic: str) -> str:
    return topic.strip()


def derive_tags(topic: str) -> list[str]:
    words = re.findall(r"[a-z0-9']+", topic.lower())
    stop = {"a", "an", "the", "for", "and", "of", "to", "in", "on", "is"}
    tags, seen = [], set()
    for w in words:
        if w not in stop and w not in seen:
            seen.add(w)
            tags.append(w)
    return tags[:8]


# ---------------------------------------------------------------------------
# stages
# ---------------------------------------------------------------------------
def stage_plan(args, out_dir: Path) -> Path:
    text = stage_header(0, "Plan", "yt-plan skill (no scoring tool — "
                        "written draft, per the skill's shape)", "ok")
    text += (
        f"Topic: {args.topic}\nFormat: {args.format}\n"
        f"Niche: {args.niche or '[not given — say it before planning]'}\n"
        f"Audience: {args.audience or '[not given — say who this is for]'}\n"
        f"Hours available this week: {args.hours}\n\n"
        "## The week (yt-plan shape)\n\n"
        "- **One anchor.** This topic, in this format. It gets the most "
        "time.\n"
        "- **One cheap one.** Built from something that already exists: "
        "a clip, a follow-up, or the comment that got the most replies "
        "last week.\n"
        "- **Three Shorts.** Pick from the anchor's strongest moments "
        "after filming (see stage 4, yt-shorts) — not invented here.\n\n"
        "Best day to post: your own analytics say — ask, do not assume. "
        "No day is guessed here.\n\n"
        "## What is still needed\n\n"
        "- Hours are as given above; if the real number differs, the "
        "plan changes.\n- Best posting day (from the channel's own "
        "analytics, not assumed).\n"
    )
    return write_stage(out_dir, "00-plan.md", text)


def stage_research(args, out_dir: Path, llm: MockLLM) -> Path:
    result = run_worker(TopicResearcher, {
        "niche": args.niche, "audience": args.audience,
        "topic": args.topic, "format": args.format}, llm)
    text = stage_header(1, "Research",
                        "TopicResearcher + yt-viral swipe.py", "ok")
    text += "## Topic research (worker draft)\n\n" + result.notes + "\n\n"
    text += "## What is working in the niche (yt-viral)\n\n"
    if args.collected:
        ok, out = run_tool(SKILLS / "yt-viral" / "swipe.py",
                           [args.collected, "--min", "1.5", "--json"])
        if ok:
            try:
                data = json.loads(out)
                outliers = data.get("outliers", [])
                thin = data.get("skipped_thin_channels", [])
                text += (f"Collected file: {args.collected}\n"
                         f"Outliers at 1.5x their own channel median: "
                         f"{len(outliers)}\n\n")
                for row in outliers[:10]:
                    text += (f"- {row.get('multiple')}x  "
                             f"{row.get('channel')} — {row.get('title')} "
                             f"({row.get('formula')})\n")
                if thin:
                    text += ("\nChannels skipped (under 4 videos — a "
                             "median off one or two videos is not a "
                             f"median): {thin}\n")
                if not outliers:
                    text += ("Nothing cleared the threshold — collect "
                             "more per channel or lower --min.\n")
            except json.JSONDecodeError:
                text += f"swipe.py output could not be parsed:\n\n```\n{out}\n```\n"
        else:
            text += f"swipe.py did not run: {out}\n"
    else:
        text += ("No collected videos supplied (--collected not given), "
                 "so swipe.py was not run. To use it, collect videos "
                 "into a JSON list first (see yt-viral SKILL.md — at "
                 "least 4 videos per channel, or the median means "
                 "nothing) and re-run with --collected collected.json.\n")
    return write_stage(out_dir, "01-research.md", text)


def stage_script(args, out_dir: Path, llm: MockLLM) -> Path:
    result = run_worker(ScriptWriter, {
        "topic": args.topic, "format": args.format}, llm)
    hook = args.hook or derive_hook(args.topic)
    text = stage_header(2, "Script",
                        "ScriptWriter + yt-script hookscore.py "
                        "(21 hook formulas)", "ok")
    text += "## Script (worker draft)\n\n" + result.notes + "\n\n"
    text += ("## Hook score (yt-script)\n\n"
             f"Draft hook (template — rewrite before filming):\n> {hook}\n\n")
    ok, out = run_tool(SKILLS / "yt-script" / "hookscore.py",
                       ["--hook", hook, "--json"])
    if ok:
        try:
            rows = json.loads(out)
            row = rows[0] if rows else {}
            text += (f"- Verdict: **{row.get('verdict')} "
                     f"({row.get('band')})**\n"
                     f"- Formula: {row.get('formula')}\n")
            for name, val in (row.get("properties") or {}).items():
                text += f"- {name}: {val}\n"
            text += ("\nA low score is a reason to look again, never a "
                     "high score a promise (hookscore.py's own warning).\n")
        except json.JSONDecodeError:
            text += f"hookscore.py output could not be parsed:\n\n```\n{out}\n```\n"
    else:
        text += f"hookscore.py did not run: {out}\n"
    return write_stage(out_dir, "02-script.md", text)


def stage_visual(args, out_dir: Path, llm: MockLLM) -> Path:
    result = run_worker(VisualProducer, {
        "topic": args.topic, "format": args.format}, llm)
    title = args.title or derive_title(args.topic)
    thumb = args.thumb or "NEVER MISS A CALL"
    text = stage_header(3, "Visual + Package",
                        "VisualProducer + yt-package title.py "
                        "(title + thumbnail as one pairing)", "ok")
    text += "## Visual plan (worker draft)\n\n" + result.notes + "\n\n"
    text += ("## Title + thumbnail lint (yt-package)\n\n"
             f"Title: {title}\nThumbnail text: {thumb}\n\n")
    ok, out = run_tool(SKILLS / "yt-package" / "title.py",
                       ["--title", title, "--thumb", thumb, "--json"])
    if ok:
        try:
            rows = json.loads(out)
            row = rows[0] if rows else {}
            text += (f"- Score: **{row.get('score')}/100**, "
                     f"{row.get('chars')} characters\n")
            for kind, msg in row.get("issues", []):
                text += f"- ISSUE [{kind}]: {msg}\n"
            for msg in row.get("good", []):
                text += f"- OK: {msg}\n"
        except json.JSONDecodeError:
            text += f"title.py output could not be parsed:\n\n```\n{out}\n```\n"
    else:
        text += f"title.py did not run: {out}\n"
    return write_stage(out_dir, "03-visual-package.md", text)


def stage_edit(args, out_dir: Path) -> Path:
    text = stage_header(4, "Edit",
                        "yt-edit deadair.py + yt-chapters chapters.py "
                        "+ yt-shorts (no scoring tool)", "ok")
    if not args.transcript:
        text += ("No transcript supplied (--transcript not given) — "
                 "this stage was skipped honestly.\n\n"
                 "To run it, supply a timestamped transcript (.srt, "
                 ".vtt, or whisper .json) and re-run with "
                 "--transcript transcript.srt. The tools print an edit "
                 "decision list; they never cut media themselves.\n")
        return write_stage(out_dir, "04-edit.md", text)
    text += f"Transcript: {args.transcript}\n\n"
    ok, out = run_tool(SKILLS / "yt-edit" / "deadair.py",
                       [args.transcript, "--json"])
    text += "## Edit decision list (yt-edit)\n\n"
    if ok:
        try:
            data = json.loads(out)
            text += (f"- {len(data.get('cuts', []))} cuts, "
                     f"{data.get('removed')}s removed, "
                     f"{data.get('out')}s out "
                     f"({data.get('duration')}s in)\n\n")
            for cut in data.get("cuts", [])[:20]:
                text += (f"- {cut.get('kind')} {cut.get('start')} → "
                         f"{cut.get('end')} — {cut.get('why')}\n")
        except json.JSONDecodeError:
            text += f"deadair.py output could not be parsed:\n\n```\n{out}\n```\n"
    else:
        text += f"deadair.py did not run: {out}\n"
    ok, out = run_tool(SKILLS / "yt-chapters" / "chapters.py",
                       [args.transcript, "--json"])
    text += "\n## Chapters (yt-chapters)\n\n"
    if ok:
        try:
            data = json.loads(out)
            text += (f"Valid per YouTube's rules: "
                     f"{data.get('valid')}\n\n")
            for ch in data.get("chapters", []):
                text += (f"- {ch.get('label')} "
                         f"{ch.get('draft_title')}\n")
            text += ("\nRetitle every line before pasting — these are "
                     "topic words, not your words.\n")
        except json.JSONDecodeError:
            text += f"chapters.py output could not be parsed:\n\n```\n{out}\n```\n"
    else:
        text += f"chapters.py did not run: {out}\n"
    text += ("\n## Shorts (yt-shorts — no scoring tool)\n\n"
             "No automated picker exists. Read the transcript and find "
             "spans of 20–55 seconds that open on a complete thought, "
             "have a turn, and end on a line (yt-shorts SKILL.md). "
             "Score each candidate's new first line with hookscore.py "
             "before keeping it.\n")
    return write_stage(out_dir, "04-edit.md", text)


def stage_caption(args, out_dir: Path, llm: MockLLM) -> Path:
    result = run_worker(CaptionWriter, {"topic": args.topic}, llm)
    hook = args.hook or derive_hook(args.topic)
    tags = derive_tags(args.topic)
    text = stage_header(5, "Caption + SEO",
                        "CaptionWriter + yt-seo (no scoring tool — "
                        "written draft, per the skill)", "ok")
    text += "## Caption pack (worker draft)\n\n" + result.notes + "\n\n"
    text += ("## Description draft (yt-seo)\n\n"
             f"{hook}\n"
             f"This video covers: {args.topic}.\n\n"
             "[ADD YOUR LINK HERE — nothing invented.]\n\n"
             "Chapters: [ADD FROM STAGE 4 — only if a transcript was "
             "supplied.]\n\n"
             f"Who it is for: {args.audience or '[not given — say who '
             'this is for]'}. What it assumes: nothing — plain words, "
             "no hype, every claim something that can be shown.\n\n"
             "## Tags (draft — from the topic words only)\n\n" +
             (", ".join(tags) if tags else "[no usable words in the "
              "topic — add tags by hand]") + "\n")
    return write_stage(out_dir, "05-caption-seo.md", text)


def stage_publish(args, out_dir: Path, llm: MockLLM) -> Path:
    result = run_worker(PublishPrep, {"topic": args.topic}, llm)
    gate = "upload it" if "video" in args.format else "post it"
    text = stage_header(6, "Publish prep",
                        "PublishPrep ONLY — prepare, never publish", gate)
    text += result.notes + "\n\n"
    text += ("## Gate\n\n"
             f"- ready_to_publish: false\n- gate: `{gate}`\n\n"
             "This file is a checklist, not a publish. Nothing in this "
             "run uploads, posts, schedules, or sends anything. The "
             "owner publishes with their exact word — "
             f"`{gate}` — or not at all.\n")
    return write_stage(out_dir, "06-publish-prep.md", text)


def stage_report(args, out_dir: Path, llm: MockLLM) -> Path:
    result = run_worker(PerformanceTracker, {"topic": args.topic}, llm)
    text = stage_header(7, "Report",
                        "PerformanceTracker + yt-retention retention.py "
                        "(+ yt-audit, yt-comment — post-publish only)",
                        "ok")
    text += "## Report template (worker draft)\n\n" + result.notes + "\n\n"
    text += "## Retention (yt-retention)\n\n"
    if args.retention:
        tool_args = [args.retention, "--json"]
        if args.transcript:
            tool_args += ["--transcript", args.transcript]
        ok, out = run_tool(SKILLS / "yt-retention" / "retention.py",
                           tool_args)
        if ok:
            try:
                data = json.loads(out)
                text += (f"- Points read: {data.get('points')}\n"
                         f"- Start → end: {data.get('start')}% → "
                         f"{data.get('end')}%\n"
                         f"- Hook leak: {data.get('hook_leak')}% lost "
                         "in the opening\n"
                         f"- Slide: {data.get('slide_per_unit')}% per "
                         "unit across the middle\n")
                for cliff in data.get("cliffs", []):
                    where = cliff.get("at_seconds")
                    if where is None:
                        where = f"{cliff.get('from')}% through"
                    text += (f"- Cliff: -{cliff.get('lost')}% at "
                             f"{where}\n")
                if data.get("said"):
                    text += "\nWhat was said at the cliffs:\n"
                    for at, said in data["said"].items():
                        text += f'- At {at}: "{said}"\n'
            except json.JSONDecodeError:
                text += f"retention.py output could not be parsed:\n\n```\n{out}\n```\n"
        else:
            text += f"retention.py did not run: {out}\n"
    else:
        text += ("No retention export supplied (--retention not given) "
                 "— nothing to read. Export it from YouTube Studio "
                 "(Analytics → a video → Engagement → audience "
                 "retention → download) and re-run with --retention "
                 "retention.csv. Numbers are never estimated — only "
                 "what the platform shows.\n")
    text += ("\n## Channel audit + comments (post-publish only)\n\n"
             "- yt-audit: needs the real channel — run the skill with "
             "real numbers after publishing. No audit is faked here.\n"
             "- yt-comment: there are no comments yet — nothing to "
             "triage or draft. After publishing, triage into the "
             "skill's four piles and draft replies in your voice.\n")
    return write_stage(out_dir, "07-report.md", text)


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description="Creator OS combined pipeline — mock mode, $0. "
                    "Writes 8 stage drafts and stops. Never publishes.")
    ap.add_argument("--topic", required=True,
                    help="The one idea this run is about.")
    ap.add_argument("--format", default="short video", choices=FORMATS,
                    help="Content format (default: short video).")
    ap.add_argument("--niche", default="",
                    help="Niche, e.g. 'US home-service owners'.")
    ap.add_argument("--audience", default="",
                    help="Who this is for, in one line.")
    ap.add_argument("--hours", type=float, default=6,
                    help="Hours available this week (yt-plan).")
    ap.add_argument("--hook", default="",
                    help="Hook line to score (default: templated from topic).")
    ap.add_argument("--title", default="",
                    help="Video title to lint (default: the topic).")
    ap.add_argument("--thumb", default="",
                    help="Thumbnail text (default: NEVER MISS A CALL).")
    ap.add_argument("--transcript", default="",
                    help="Timestamped transcript (.srt/.vtt/whisper .json).")
    ap.add_argument("--retention", default="",
                    help="YouTube Studio retention export (.csv).")
    ap.add_argument("--collected", default="",
                    help="Collected videos JSON for yt-viral swipe.py.")
    ap.add_argument("--out", default="",
                    help="Output dir (default: out/<slug>-<YYYY-MM-DD>/).")
    return ap


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    out_dir = Path(args.out) if args.out else (
        ROOT / "out" / f"{slugify(args.topic)}-{date.today().isoformat()}")
    out_dir.mkdir(parents=True, exist_ok=True)

    llm = MockLLM()
    print("Creator OS — combined pipeline (MOCK, $0)")
    print(f"topic: {args.topic} | format: {args.format}")
    print(f"out: {out_dir}\n")

    stages = [
        ("Plan", lambda: stage_plan(args, out_dir)),
        ("Research", lambda: stage_research(args, out_dir, llm)),
        ("Script", lambda: stage_script(args, out_dir, llm)),
        ("Visual + Package", lambda: stage_visual(args, out_dir, llm)),
        ("Edit", lambda: stage_edit(args, out_dir)),
        ("Caption + SEO", lambda: stage_caption(args, out_dir, llm)),
        ("Publish prep", lambda: stage_publish(args, out_dir, llm)),
        ("Report", lambda: stage_report(args, out_dir, llm)),
    ]
    written = []
    for name, fn in stages:
        path = fn()
        written.append(path)
        print(f"  [ok] stage {len(written) - 1}: {name} -> {path.name}")

    print(f"\n{len(written)}/8 stage drafts written to {out_dir}")
    print(f"mock LLM calls: {llm.calls} | spend: $0.00")
    print("Nothing was published, sent, uploaded, or scheduled.")
    print("\nship it, or change it?")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
