#!/usr/bin/env python3
"""Creator OS — combined pipeline runner (mock mode, $0).

One idea in, thirteen stage files out. Each stage runs the Creator
Studio worker AND the matching YouTube skill/tool where one exists:

  0a. Niche finder — yt-niche niche_score.py (runs when --find-niche
                    is passed or no --topic is given; skipped
                    honestly when the topic/niche is already known)
  0b. Plan         — yt-plan (weekly plan, from hours available;
                    reads the last run's next-brief.json when one
                    exists - the closed loop)
  1. Research     — TopicResearcher + yt-viral swipe.py
  2a. Concept     — concept_score.py (3-5 concepts scored 1-10;
                    the picked concept feeds the Script stage)
  2b. Script       — ScriptWriter + yt-script hookscore.py (21 formulas)
  3. Visual+Pack  — VisualProducer + yt-package title.py (title+thumb)
  4. Video        — Reel Factory build through a pluggable video
                    provider (see README.md "Video providers"): real
                    footage when --footage is given, otherwise the
                    configured provider — AI-generated stills
                    (Pollinations, free) + slow Ken Burns motion by
                    default, or true AI video motion from a local
                    model (your GPU) or a paid cloud API (your key).
                    With --no-gen-visuals and no footage it writes
                    the production plan + the exact missing inputs
                    and builds no video.
  5. Edit         — yt-edit deadair.py + yt-chapters chapters.py
                    + yt-shorts (needs --transcript, else skipped honestly)
  6. Caption+SEO  — CaptionWriter + yt-seo (description/tags)
  7. Publish prep — PublishPrep ONLY (prepare, never publish)
  8. Report       — PerformanceTracker + yt-retention retention.py
                    (+ yt-audit, yt-comment — post-publish only)
  9. Upload       — upload_youtube.py (DEFAULT OFF - only with
                    --auto-upload AND YOUTUBE_UPLOAD_ENABLED=1 AND
                    the owner's own credentials; --upload-dry-run
                    prints the plan with no network)
  10. Next plan   — loop_next.py (reads the last run's 08-report.md
                    + retention CSV, writes 10-next-plan.md and
                    next-brief.json for the next run's Plan stage)

Usage:
  python3 scripts/creator_os_run.py --topic "AI receptionist for plumbers" \
      --format "short video" [--niche ...] [--audience ...]
      [--transcript transcript.srt] [--retention retention.csv]
      [--collected collected.json] [--hours 6] [--out out/dir]
      [--footage footage.mp4] [--voice avocado_v2:MAI_01]
      [--gen-visuals | --no-gen-visuals]
      [--video-provider {footage|stills|local|api|auto}]
      [--video-config video_providers.yaml]
      [--find-niche] [--niches niches.json] [--concepts concepts.json]
      [--auto-upload] [--upload-dry-run] [--prev-out out/<last-run>/]

  python3 scripts/creator_os_run.py --find-niche
      # no topic: the niche finder picks one, and the run uses it.

Mock mode is the DEFAULT: the workers draft through MockLLM (offline,
deterministic, $0) and the YouTube tools are local Python with no
network and no keys. The video stage builds a local mp4 from real
footage when supplied, otherwise from the configured video provider
(default: AI-generated stills — Pollinations, free; the network
calls in this repo live only in scripts/gen_visuals.py and in the
api provider of scripts/video_providers.py, which runs only when
the user configures it with their own key). Nothing here publishes,
sends, uploads, schedules, or spends unless the owner enables the
upload stage twice (flag + env var) with their own credentials.
The run ends with "ship it, or change it?" and exits — the owner
publishes, if at all, with their own word.
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
from scripts.gen_visuals import is_talvenor  # noqa: E402
from scripts.make_thumbnail import build_thumbnail  # noqa: E402
from scripts.video_build import build_video  # noqa: E402
from scripts.video_providers import _run as run_cmd  # noqa: E402
from scripts.video_providers import collect_footage  # noqa: E402
from scripts.loop_next import build_plan as build_loop_plan  # noqa: E402
from scripts.upload_youtube import (  # noqa: E402
    UploadError,
    do_upload,
    missing_setup,
    plan_upload,
    resolve_credentials,
)

SKILLS = ROOT / "youtube-skills"
TOOLS = ROOT / "tools"
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


def run_niche_tool(args) -> dict | None:
    """Run tools/niche_score.py --json. Returns the parsed output,
    or None with the error printed when it cannot run."""
    tool_args = ["--json"]
    if args.niches:
        tool_args += ["--niches", args.niches]
    ok, out = run_tool(TOOLS / "niche_score.py", tool_args)
    if not ok:
        print(f"  [warn] niche_score.py did not run: {out}")
        return None
    try:
        return json.loads(out)
    except json.JSONDecodeError:
        print("  [warn] niche_score.py output could not be parsed")
        return None


def find_next_brief(out_dir: Path, explicit: str) -> dict | None:
    """Find the last run's next-brief.json: --brief wins, else the
    most recent sibling run dir holding one. None when there is none
    yet (first run)."""
    if explicit:
        path = Path(explicit)
        if path.exists():
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                print(f"  [warn] --brief file could not be read: {path}")
                return None
        print(f"  [warn] --brief file not found: {path}")
        return None
    parent = out_dir.parent
    if not parent.exists():
        return None
    siblings = sorted(
        (p for p in parent.iterdir()
         if p.is_dir() and p != out_dir
         and (p / "next-brief.json").exists()),
        key=lambda p: (p / "next-brief.json").stat().st_mtime,
        reverse=True)
    if not siblings:
        return None
    try:
        return json.loads(
            (siblings[0] / "next-brief.json").read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


# ---------------------------------------------------------------------------
# stages
# ---------------------------------------------------------------------------
def stage_niche(args, out_dir: Path,
                precomputed: dict | None) -> Path:
    """Stage 0a - Niche finder (yt-niche). Skipped honestly when the
    topic/niche is already known and --find-niche was not passed."""
    text = stage_header(0, "Niche finder",
                        "yt-niche niche_score.py (demand 30% + "
                        "competition-gap 30% + monetization 25% + "
                        "fresher-fit 15%)", "ok")
    if precomputed is None:
        text += ("Skipped - the topic/niche was already given, so "
                 "there was nothing to find.\n\n"
                 f"Topic: {args.topic}\n"
                 f"Niche: {args.niche or '[same as topic]'}\n\n"
                 "To run the finder, pass --find-niche (or run with "
                 "no --topic) and re-run.\n")
        return write_stage(out_dir, "00-niche.md", text)
    rows = precomputed.get("ranked", [])
    if not rows:
        text += ("niche_score.py ran but returned no ranked niches - "
                 "the finder could not pick anything. Give --topic "
                 "or --niches niches.json and re-run.\n")
        return write_stage(out_dir, "00-niche.md", text)
    if precomputed.get("sample"):
        text += ("SAMPLE niches (mock mode - fixed samples, not real "
                 "research). A high score is a reason to research "
                 "that niche for real, never proof it will work.\n\n")
    else:
        text += (f"Niches scored from: {args.niches}\n\n")
    text += "## Ranked niches\n\n"
    for i, row in enumerate(rows, 1):
        parts = row["parts"]
        text += (f"{i}. **{row['name']}** - {row['total']}/10 "
                 f"{row['band']}\n"
                 f"   demand {parts['demand']}, competition-gap "
                 f"{parts['competition_gap']}, monetization "
                 f"{parts['monetization']}, fresher-fit "
                 f"{parts['fresher_fit']}\n")
        if row.get("notes"):
            text += f"   {row['notes']}\n"
    text += (f"\n## Picked niche\n\n**{precomputed['picked']}** "
             f"({rows[0]['total']}/10, {rows[0]['band']})\n\n"
             "This run uses the picked niche as its topic.\n")
    return write_stage(out_dir, "00-niche.md", text)


def stage_concept(args, out_dir: Path) -> tuple[Path, dict | None]:
    """Stage 2a - Viral concept score. Runs after Research, before
    Script. Returns (path, picked concept row or None)."""
    text = stage_header(2, "Viral concept score",
                        "concept_score.py (hook 40% + trend-fit 25% + "
                        "competition-gap 20% + fresher-fit 15% - "
                        "adapted from the viral-clips skill)", "ok")
    tool_args = ["--json"]
    if args.concepts:
        tool_args += ["--concepts", args.concepts]
    else:
        tool_args += ["--topic", args.topic]
    ok, out = run_tool(TOOLS / "concept_score.py", tool_args)
    if not ok:
        text += f"concept_score.py did not run: {out}\n\nThe Script "
        text += ("stage falls back to the templated hook - fix the "
                 "tool input and re-run for a scored concept.\n")
        return write_stage(out_dir, "02-concept-score.md", text), None
    try:
        data = json.loads(out)
    except json.JSONDecodeError:
        text += f"concept_score.py output could not be parsed:\n\n```\n{out}\n```\n"
        return write_stage(out_dir, "02-concept-score.md", text), None
    rows = data.get("ranked", [])
    if not rows:
        text += ("concept_score.py ran but returned no ranked "
                 "concepts.\n")
        return write_stage(out_dir, "02-concept-score.md", text), None
    if data.get("sample"):
        text += ("SAMPLE concepts (mock mode - template angles from "
                 "the topic, not research). Research them for real "
                 "before filming.\n\n")
    elif args.concepts:
        text += (f"Concepts scored from: {args.concepts}\n"
                 "Outliers from stage 1 research fed the list.\n\n")
    text += "## Ranked concepts\n\n"
    for i, row in enumerate(rows, 1):
        parts = row["parts"]
        text += (f"{i}. **{row['concept']}** - {row['total']}/10 "
                 f"{row['band']}\n")
        if row.get("hook"):
            text += f"   hook: \"{row['hook']}\"\n"
        text += (f"   hook {parts['hook_strength']}, trend-fit "
                 f"{parts['trend_fit']}, competition-gap "
                 f"{parts['competition_gap']}, fresher-fit "
                 f"{parts['fresher_fit']}\n")
    picked = rows[0]
    text += (f"\n## Picked concept\n\n**{picked['concept']}** "
             f"({picked['total']}/10, {picked['band']})\n\n"
             "The Script stage writes this concept. Only 7+ counts "
             "as strong; below 5, rework the hook before anything "
             "else.\n")
    return write_stage(out_dir, "02-concept-score.md", text), picked


def stage_plan(args, out_dir: Path) -> Path:
    text = stage_header(0, "Plan", "yt-plan skill (no scoring tool — "
                        "written draft, per the skill's shape)", "ok")
    text += (
        f"Topic: {args.topic}\nFormat: {args.format}\n"
        f"Niche: {args.niche or '[not given — say it before planning]'}\n"
        f"Audience: {args.audience or '[not given — say who this is for]'}\n"
        f"Hours available this week: {args.hours}\n\n"
    )
    brief = find_next_brief(out_dir, args.brief)
    if brief is not None:
        text += "## Carried over from the last video (closed loop)\n\n"
        if brief.get("status") == "no-data":
            text += ("The last run had no performance data yet - "
                     "nothing carried over. Collect the retention "
                     "export after publishing.\n\n")
        else:
            text += (f"From run: {brief.get('source_run') or '[unknown]'}\n\n")
            if brief.get("keep"):
                text += "Keep:\n"
                for item in brief["keep"]:
                    text += f"- {item}\n"
                text += "\n"
            if brief.get("change"):
                text += "Change:\n"
                for item in brief["change"]:
                    text += f"- {item}\n"
                text += "\n"
            if brief.get("next_topic_angle"):
                text += ("Next angle: "
                         f"{brief['next_topic_angle']}\n\n")
    else:
        text += ("## Carried over from the last video (closed loop)\n\n"
                 "No next-brief.json found - this is the first run, "
                 "or the last run had no stage 10 yet.\n\n")
    text += (
        "## The week (yt-plan shape)\n\n"
        "- **One anchor.** This topic, in this format. It gets the most "
        "time.\n"
        "- **One cheap one.** Built from something that already exists: "
        "a clip, a follow-up, or the comment that got the most replies "
        "last week.\n"
        "- **Three Shorts.** Pick from the anchor's strongest moments "
        "after filming (see stage 5, yt-shorts) — not invented here.\n\n"
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


def stage_script(args, out_dir: Path, llm: MockLLM,
                 concept: dict | None) -> Path:
    result = run_worker(ScriptWriter, {
        "topic": args.topic, "format": args.format}, llm)
    hook = args.hook or (concept or {}).get("hook") or derive_hook(args.topic)
    text = stage_header(2, "Script",
                        "ScriptWriter + yt-script hookscore.py "
                        "(21 hook formulas)", "ok")
    if concept is not None:
        text += (f"## Concept picked (stage 2a)\n\n"
                 f"**{concept['concept']}** ({concept['total']}/10, "
                 f"{concept['band']}) - this script writes that "
                 "concept.\n\n")
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


def build_thumbnail_for_run(args, out_dir: Path,
                            thumb_text: str) -> tuple[str | None, str]:
    """Build thumbnail.jpg in the out dir from the best visual.

    Returns (path_str | None, note). Best visual, in order: the
    first frame of --footage (grabbed with ffmpeg), else
    video_work/stills/scene1.jpg when it already exists (a re-run,
    or the video stage's stills). No visual yet → (None, honest
    reason): at stage 3 the stills do not exist yet — they are
    generated in stage 4, which retries this same helper.
    """
    source: Path | None = None
    footage = getattr(args, "footage", "") or ""
    if footage:
        clips = collect_footage(footage)
        if clips:
            work = out_dir / "video_work"
            work.mkdir(parents=True, exist_ok=True)
            frame = work / "thumb-frame.jpg"
            ok, _ = run_cmd(["ffmpeg", "-y", "-ss", "0.5", "-i",
                             str(clips[0]["path"]), "-frames:v", "1",
                             str(frame)], timeout=60)
            if ok and frame.exists():
                source = frame
    if source is None:
        still = out_dir / "video_work" / "stills" / "scene1.jpg"
        if still.exists():
            source = still
    if source is None:
        return None, ("no thumbnail built — no visual exists yet: "
                      "no --footage was given and the AI stills are "
                      "generated in stage 4 (the video stage retries "
                      "the thumbnail from scene 1 then)")
    thumb_path = out_dir / "thumbnail.jpg"
    res = build_thumbnail(source, thumb_text, thumb_path)
    if not res["ok"]:
        return None, f"thumbnail build failed: {res['error']}"
    note = res.get("note", "")
    return str(thumb_path), note


def thumb_text_for(args) -> tuple[str, str]:
    """The (title, thumbnail text) for this run.

    Thumbnail text: --thumb when given; the Talvenor line only
    for Talvenor runs; otherwise the first 3 words of the title,
    uppercased.
    """
    title = args.title or derive_title(args.topic)
    if args.thumb:
        thumb = args.thumb
    elif is_talvenor(args.topic, getattr(args, "brand", "auto")):
        thumb = "NEVER MISS A CALL"
    else:
        thumb = " ".join(title.split()[:3]).upper() or "WATCH THIS TEST"
    return title, thumb


def stage_visual(args, out_dir: Path, llm: MockLLM) -> Path:
    result = run_worker(VisualProducer, {
        "topic": args.topic, "format": args.format}, llm)
    title, thumb = thumb_text_for(args)
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
    thumb_path, thumb_note = build_thumbnail_for_run(args, out_dir, thumb)
    text += "\n## Thumbnail\n\n"
    if thumb_path:
        text += (f"- Built: `{thumb_path}` (1280x720 JPG)\n"
                 f"- Text: \"{thumb}\"\n")
        if thumb_note:
            text += f"- Note: {thumb_note}\n"
    else:
        text += f"- Not built: {thumb_note}\n"
    return write_stage(out_dir, "03-visual-package.md", text)


def stage_video(args, out_dir: Path) -> Path:
    # The header is written by hand here: the video stage is a local
    # build (FFmpeg + the tts binary, plus Pollinations image
    # generation when no footage is given), not a mock draft, so the
    # generic "no network" line in stage_header would not be honest
    # about TTS (the tts binary synthesises through its own service)
    # or about Pollinations (the one network call in this repo).
    result = build_video(args, out_dir, out_dir / "video_work")
    # Thumbnail retry: stage 3 could not build one without a visual
    # (stills are generated here, in stage 4). Build it from scene 1
    # now and record it in 03-visual-package.md. Skipped on dry
    # runs — nothing was executed, so there is no visual to use.
    thumb_path = out_dir / "thumbnail.jpg"
    if not thumb_path.exists() and not getattr(args, "video_dry_run",
                                               False):
        _, thumb = thumb_text_for(args)
        built, thumb_note = build_thumbnail_for_run(args, out_dir, thumb)
        if built:
            visual_path = out_dir / "03-visual-package.md"
            with open(visual_path, "a", encoding="utf-8") as fh:
                fh.write("\n## Thumbnail (built in stage 4)\n\n"
                         f"- Built: `{built}` (1280x720 JPG)\n"
                         f"- Text: \"{thumb}\"\n"
                         "- Source: scene 1 still (stage 3 had no "
                         "visual yet)\n")
                if thumb_note:
                    fh.write(f"- Note: {thumb_note}\n")
    # The end card follows the plan's brand: Talvenor runs get the
    # exact logo; any other topic gets a text-only card.
    endcard_phrase = ("exact-logo end card"
                      if result.get("endcard", {}).get("logo_used")
                      else "text-only end card (no brand logo)")
    if result["source"] == "real footage":
        sources = ("Reel Factory build — real footage + TTS voiceover "
                   f"+ burned-in captions + {endcard_phrase}")
        mode = "local build (FFmpeg + tts binary, $0)"
    elif result["gen"]["attempted"]:
        sources = ("Reel Factory build — AI-generated stills + slow "
                   "Ken Burns motion (Pollinations, free) + TTS voiceover "
                   f"+ burned-in captions + {endcard_phrase}")
        mode = ("local build (FFmpeg + tts binary + Pollinations image "
                "generation, $0, no key)")
    else:
        sources = ("Reel Factory build — real footage + TTS voiceover "
                   f"+ burned-in captions + {endcard_phrase}")
        mode = "local build (FFmpeg + tts binary, $0)"
    text = ("# Stage 4 — Video (Reel Factory)\n\n"
            f"Sources: {sources}\n"
            f"Mode: {mode}. "
            f"{GATE_NOTE}\nGate: `upload it`\n\n"
            f"VO source: {result.get('vo_source', 'templated lines')}\n\n---\n")
    plan = result["plan"]
    if result["built"]:
        text += (f"## Built\n\n- Output: `{result['video_path']}`\n"
                 f"- Duration: {result['duration']}s, "
                 f"{result['width']}x{result['height']} 30fps, "
                 f"H.264 + {result.get('audio', '')}, faststart\n"
                 f"- Size: {result['size_bytes']} bytes\n"
                 "- Verified: ffprobe reads the video stream and the "
                 "file decodes cleanly (ffmpeg -f null).\n\n")
    else:
        text += (f"## No video was built\n\n{result['reason']}.\n\n")
    if result.get("dry_run"):
        text += ("## Dry run — nothing was executed\n\n"
                 "What the resolved provider WOULD do on a real run "
                 "(--video-dry-run). No engine started, no still was "
                 "fetched, no key was read, no video was built.\n\n")
        for line in result["dry_run"]:
            text += f"- {line}\n"
        text += "\n"
    if result["missing"]:
        text += "## Missing inputs — needed from Boss\n\n"
        for item in result["missing"]:
            text += f"- {item}\n"
        text += "\n"
    if result["gen"]["attempted"]:
        text += "## Visual source\n\n"
        text += f"- Source: {result['source']}\n"
        for rec in result["gen"]["per_scene"]:
            if rec["ok"]:
                text += (f"- Scene {rec['scene']}: still generated — "
                         f"`{rec['path']}` ({rec['note']})\n")
            else:
                text += (f"- Scene {rec['scene']}: GENERATION FAILED — "
                         f"{rec['note']}\n")
        text += ("\nAI stills + motion: the images are AI-generated "
                 "stills given slow zoom/pan motion. That is not real "
                 "footage and not true AI video motion.\n\n")
    if result.get("provider"):
        text += "## Video provider\n\n"
        text += f"- Provider: `{result['provider']}`\n"
        for rec in result.get("provider_scenes", []):
            status = "OK" if rec.get("ok") else "FAILED"
            text += (f"- Scene {rec.get('scene')}: {status} — "
                     f"{rec.get('note')}\n")
        text += "\n"
    text += "## Production plan (shot list)\n\n"
    for scene in plan.get("scenes", []):
        text += (f"- Scene {scene['scene']} ({scene['seconds']}): "
                 f"{scene['shows']}\n"
                 f"  Voiceover: \"{scene['vo_line']}\"\n")
    text += ("\nCaptions: " + plan.get("captions", "") +
             " (line-level, not word-level karaoke).\n"
             f"Voice: {plan.get('voice', '')} "
             "(override with --voice).\n\n")
    endcard = plan.get("endcard", {})
    if endcard.get("logo"):
        logo_line = (f"- Logo: exact file `{endcard.get('logo')}` — "
                     "pasted flat, never redrawn\n")
    else:
        logo_line = "- Logo: none — text-only end card (no brand logo)\n"
    text += ("## End card\n\n"
             f"- Duration: {endcard.get('duration_s')}s\n"
             + logo_line +
             f"- Headline: \"{endcard.get('headline')}\"\n"
             f"- CTA: \"{endcard.get('cta')}\"\n")
    if result["built"]:
        text += "\n## What was used\n\n"
        for scene in result["scenes"]:
            text += (f"- Scene {scene['scene']}: "
                     f"{scene['footage']}, "
                     f"voiceover {'spoken' if scene['vo_ok'] else 'SILENT (TTS failed)'} — "
                     f"\"{scene['vo_line']}\"\n")
        end = result.get("endcard", {})
        if end.get("logo_used"):
            end_note = (f"{end.get('duration')}s, exact logo "
                        f"({end.get('note')})")
        else:
            end_note = (f"{end.get('duration')}s, TEXT-ONLY "
                        f"({end.get('note')})")
        text += f"- End card: {end_note}\n"
        if result["fallbacks"]:
            text += "\n## Fallbacks (read before shipping)\n\n"
            for fb in result["fallbacks"]:
                text += f"- {fb}\n"
    vo_source = result.get("vo_source", "templated lines")
    if vo_source.startswith("--script") or vo_source == "vo-lines.txt":
        vo_line = ("- Voiceover lines came from the agent's script file "
                   f"({vo_source}); rewrite them there, then re-run.\n")
    elif result.get("endcard", {}).get("logo_used"):
        vo_line = ("- Voiceover lines are templated from the brand pitch; "
                   "rewrite them before shipping.\n")
    else:
        vo_line = ("- Voiceover lines are templated from the topic; "
                   "rewrite them before shipping.\n")
    text += ("\n## Limits\n\n"
             "- The $0 default visual source is AI stills (Pollinations, "
             "free) with slow Ken Burns motion — AI stills + motion, "
             "not real footage and not true AI video motion. True AI "
             "video motion comes from the local provider (your own GPU: "
             "WanGP/FramePack) or the api provider (your own paid key: "
             "Muapi Sora/Runway) — see README.md 'Video providers'. "
             "Neither a GPU nor a key is wired in here.\n"
             + vo_line +
             "- This file is a build record, not an upload. Gate: "
             "`upload it` — the owner uploads, if at all.\n")
    return write_stage(out_dir, "04-video.md", text)


def stage_edit(args, out_dir: Path) -> Path:
    text = stage_header(5, "Edit",
                        "yt-edit deadair.py + yt-chapters chapters.py "
                        "+ yt-shorts (no scoring tool)", "ok")
    if not args.transcript:
        text += ("No transcript supplied (--transcript not given) — "
                 "this stage was skipped honestly.\n\n"
                 "To run it, supply a timestamped transcript (.srt, "
                 ".vtt, or whisper .json) and re-run with "
                 "--transcript transcript.srt. The tools print an edit "
                 "decision list; they never cut media themselves.\n")
        return write_stage(out_dir, "05-edit.md", text)
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
    return write_stage(out_dir, "05-edit.md", text)


def stage_caption(args, out_dir: Path, llm: MockLLM) -> Path:
    result = run_worker(CaptionWriter, {"topic": args.topic}, llm)
    hook = args.hook or derive_hook(args.topic)
    tags = derive_tags(args.topic)
    text = stage_header(6, "Caption + SEO",
                        "CaptionWriter + yt-seo (no scoring tool — "
                        "written draft, per the skill)", "ok")
    text += "## Caption pack (worker draft)\n\n" + result.notes + "\n\n"
    text += ("## Description draft (yt-seo)\n\n"
             f"{hook}\n"
             f"This video covers: {args.topic}.\n\n"
             "[ADD YOUR LINK HERE — nothing invented.]\n\n"
             "Chapters: [ADD FROM STAGE 5 — only if a transcript was "
             "supplied.]\n\n"
             f"Who it is for: {args.audience or '[not given — say who '
             'this is for]'}. What it assumes: nothing — plain words, "
             "no hype, every claim something that can be shown.\n\n"
             "## Tags (draft — from the topic words only)\n\n" +
             (", ".join(tags) if tags else "[no usable words in the "
              "topic — add tags by hand]") + "\n")
    return write_stage(out_dir, "06-caption-seo.md", text)


def stage_publish(args, out_dir: Path, llm: MockLLM) -> Path:
    result = run_worker(PublishPrep, {"topic": args.topic}, llm)
    gate = "upload it" if "video" in args.format else "post it"
    text = stage_header(7, "Publish prep",
                        "PublishPrep ONLY — prepare, never publish", gate)
    text += result.notes + "\n\n"
    text += ("## Gate\n\n"
             f"- ready_to_publish: false\n- gate: `{gate}`\n\n"
             "This file is a checklist, not a publish. Nothing in this "
             "run uploads, posts, schedules, or sends anything. The "
             "owner publishes with their exact word — "
             f"`{gate}` — or not at all.\n")
    return write_stage(out_dir, "07-publish-prep.md", text)


def stage_report(args, out_dir: Path, llm: MockLLM) -> Path:
    result = run_worker(PerformanceTracker, {"topic": args.topic}, llm)
    text = stage_header(8, "Report",
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
    return write_stage(out_dir, "08-report.md", text)


def stage_upload(args, out_dir: Path) -> Path:
    """Stage 9 - Auto-upload (upload_youtube.py). DEFAULT OFF.
    Only runs with --auto-upload AND YOUTUBE_UPLOAD_ENABLED=1 AND
    the owner's own credentials. Everything else writes the honest
    not-enabled / missing-setup file - never a fake upload."""
    import os as _os

    video = out_dir / "video.mp4"
    title = args.title or derive_title(args.topic)
    hook = args.hook or derive_hook(args.topic)
    tags = derive_tags(args.topic)
    text = stage_header(9, "Upload",
                        "upload_youtube.py - YouTube Data API v3 "
                        "(resumable upload)", "upload it")
    enabled = bool(args.auto_upload) and (
        _os.environ.get("YOUTUBE_UPLOAD_ENABLED") == "1")
    if not enabled:
        text += ("## Status: NOT ENABLED - nothing was uploaded\n\n"
                 "Auto-upload is off by default. It only runs with "
                 "the flag AND the env var, plus the owner's own "
                 "credentials.\n\n"
                 "## To enable it\n\n"
                 "- Re-run with `--auto-upload` and "
                 "`YOUTUBE_UPLOAD_ENABLED=1`.\n")
        for step in missing_setup():
            text += f"- {step}\n"
        text += ("\n## What WOULD upload (when enabled)\n\n"
                 f"- Video: `{video}`"
                 f"{' (exists)' if video.exists() else ' (NOT BUILT YET - stage 4 built no video)'}\n"
                 f"- Title: {title}\n"
                 f"- Description: {hook}\n"
                 f"- Tags: {', '.join(tags) if tags else '[none]'}\n"
                 f"- Privacy: {args.upload_privacy} (default private - "
                 "never public by accident)\n")
        return write_stage(out_dir, "09-upload.md", text)
    if not video.exists():
        text += ("## Status: NOTHING TO UPLOAD\n\n"
                 "Upload was enabled, but stage 4 built no video "
                 "(`video.mp4` does not exist in this run). Give "
                 "--footage, or run without --no-gen-visuals so the "
                 "stills provider builds one, then re-run with "
                 "--auto-upload.\n")
        return write_stage(out_dir, "09-upload.md", text)
    if args.upload_dry_run:
        try:
            plan = plan_upload(str(video), title, hook, tags,
                               args.upload_privacy, args.upload_category)
        except UploadError as exc:
            text += f"## Status: DRY RUN FAILED\n\n{exc}\n"
            return write_stage(out_dir, "09-upload.md", text)
        text += ("## Status: DRY RUN - nothing was sent, nothing "
                 "was uploaded\n\n"
                 "This is exactly what WOULD upload with "
                 "--auto-upload (no --upload-dry-run):\n\n")
        for key, value in plan.items():
            if key in ("dry_run", "note"):
                continue
            text += f"- {key}: {value}\n"
        return write_stage(out_dir, "09-upload.md", text)
    try:
        creds = resolve_credentials(args.upload_credentials or None,
                                    args.upload_token or None)
        result = do_upload(str(video), title, hook, tags,
                           args.upload_privacy, args.upload_category,
                           creds)
    except UploadError as exc:
        text += ("## Status: UPLOAD FAILED\n\n"
                 f"{exc}\n\n"
                 "Nothing was uploaded. Fix the error above and "
                 "re-run with --auto-upload.\n")
        return write_stage(out_dir, "09-upload.md", text)
    text += ("## Status: UPLOADED\n\n"
             f"- Video URL: {result['url']}\n"
             f"- Video id: {result['video_id']}\n"
             f"- Privacy: {result['privacy']}\n"
             f"- Title: {result['title']}\n\n"
             "Now collect real numbers for the loop: after views "
             "arrive, export the retention CSV from YouTube Studio "
             "and re-run with --retention so stage 10 learns from "
             "this video.\n")
    return write_stage(out_dir, "09-upload.md", text)


def stage_loop(args, out_dir: Path) -> Path:
    """Stage 10 - Closed feedback loop (loop_next.py). Reads the
    last run's 08-report.md + retention CSV and writes
    10-next-plan.md + next-brief.json. Honest when there is no
    performance data yet."""
    prev_out = args.prev_out or None
    retention = args.retention or None
    build_loop_plan(out_dir,
                    Path(prev_out) if prev_out else None,
                    Path(retention) if retention else None)
    return out_dir / "10-next-plan.md"


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description="Creator OS combined pipeline — mock mode, $0. "
                    "Writes 13 stage files and stops. Never publishes "
                    "unless the owner enables the upload stage twice.")
    ap.add_argument("--topic", default="",
                    help="The one idea this run is about. If omitted, "
                         "the niche finder picks one (see --find-niche).")
    ap.add_argument("--brand", default="auto",
                    choices=["auto", "talvenor", "generic"],
                    help="Video template brand. auto (default): the "
                         "Talvenor template (missed-call lines, logo, "
                         "plumber scenes) applies ONLY when the topic "
                         "mentions Talvenor or the AI receptionist; any "
                         "other topic gets neutral topic-derived lines "
                         "and a text-only end card. talvenor forces the "
                         "brand template; generic forces the neutral one.")
    ap.add_argument("--format", default="short video", choices=FORMATS,
                    help="Content format (default: short video).")
    ap.add_argument("--niche", default="",
                    help="Niche, e.g. 'US home-service owners'.")
    ap.add_argument("--find-niche", action="store_true",
                    help="Run the niche finder (yt-niche) before "
                         "planning. Also runs automatically when no "
                         "--topic is given.")
    ap.add_argument("--niches", default="",
                    help="Candidate niches JSON for niche_score.py "
                         "(default: fixed mock samples).")
    ap.add_argument("--concepts", default="",
                    help="Concepts JSON for concept_score.py (default: "
                         "template concepts from the topic).")
    ap.add_argument("--audience", default="",
                    help="Who this is for, in one line.")
    ap.add_argument("--hours", type=float, default=6,
                    help="Hours available this week (yt-plan).")
    ap.add_argument("--hook", default="",
                    help="Hook line to score (default: the picked "
                         "concept's hook, else templated from topic).")
    ap.add_argument("--title", default="",
                    help="Video title to lint (default: the topic).")
    ap.add_argument("--thumb", default="",
                    help="Thumbnail text (default: first 3 words of the "
                         "title, uppercased; Talvenor runs: "
                         "NEVER MISS A CALL).")
    ap.add_argument("--script", default="",
                    help="Voiceover script file: one line per scene "
                         "(first 3 lines used for the 3 scenes). The "
                         "agent writes this in pass 2 — a vo-lines.txt "
                         "left in the out dir is picked up "
                         "automatically. A missing/unreadable --script "
                         "file fails the video stage honestly; it never "
                         "silently falls back to templated lines.")
    ap.add_argument("--transcript", default="",
                    help="Timestamped transcript (.srt/.vtt/whisper .json).")
    ap.add_argument("--retention", default="",
                    help="YouTube Studio retention export (.csv).")
    ap.add_argument("--collected", default="",
                    help="Collected videos JSON for yt-viral swipe.py.")
    ap.add_argument("--out", default="",
                    help="Output dir (default: out/<slug>-<YYYY-MM-DD>/).")
    ap.add_argument("--footage", default="",
                    help="Video file or folder of clips for the video stage.")
    ap.add_argument("--video-provider", default=None,
                    choices=["footage", "stills", "local", "api", "auto"],
                    help="Video provider: footage (needs --footage), "
                         "stills (free default), local (your GPU: "
                         "WanGP/FramePack/custom), api (your paid key: "
                         "Muapi Sora/Runway), or auto (default: footage "
                         "if given, else the configured provider, else "
                         "stills).")
    ap.add_argument("--video-config", default="",
                    help="Video provider config file (default: "
                         "video_providers.yaml at the repo root).")
    ap.add_argument("--video-dry-run", action="store_true",
                    help="Dry run for the video stage: print what the "
                         "resolved provider WOULD do (exact command, GPU "
                         "check, missing setup) and stop — no engine "
                         "starts, no still is fetched, no key is read, "
                         "no video is built. Use it to check a GPU "
                         "machine's setup before a real run.")
    ap.add_argument("--gen-visuals", dest="gen_visuals",
                    action="store_true", default=True,
                    help="Generate AI stills when no --footage is given "
                         "(default: on).")
    ap.add_argument("--no-gen-visuals", dest="gen_visuals",
                    action="store_false",
                    help="Do not generate stills; without --footage the "
                         "video stage builds no video.")
    ap.add_argument("--voice", default="avocado_v2:MAI_01",
                    help="TTS voice id for the video stage voiceover.")
    ap.add_argument("--no-video", action="store_true",
                    help="Skip building a video (stage 4 still writes its plan).")
    ap.add_argument("--auto-upload", action="store_true",
                    help="Enable stage 9 auto-upload. ALSO needs "
                         "YOUTUBE_UPLOAD_ENABLED=1 and the owner's "
                         "own credentials, or the stage fails honestly.")
    ap.add_argument("--upload-dry-run", action="store_true",
                    help="Stage 9 prints exactly what WOULD upload; "
                         "no network, no credentials needed.")
    ap.add_argument("--upload-privacy", default="private",
                    choices=["private", "unlisted", "public"],
                    help="Upload privacy (default: private).")
    ap.add_argument("--upload-category", default="22",
                    help="YouTube category id (default: 22).")
    ap.add_argument("--upload-credentials", default="",
                    help="OAuth client secrets JSON path (or "
                         "YOUTUBE_CLIENT_SECRETS_FILE).")
    ap.add_argument("--upload-token", default="",
                    help="Stored token JSON path (or YOUTUBE_TOKEN_FILE).")
    ap.add_argument("--prev-out", default="",
                    help="Previous run's output dir for the loop "
                         "(stage 10). Default: most recent sibling run "
                         "dir with 08-report.md.")
    ap.add_argument("--brief", default="",
                    help="next-brief.json to carry into the Plan stage "
                         "(default: most recent sibling run's).")
    return ap


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)

    # The niche finder runs before anything else needs a topic: when
    # no --topic is given, or --find-niche is passed, its picked
    # niche becomes the run's topic. When the topic/niche is already
    # known and no flag is passed, the finder is skipped honestly.
    niche_data = None
    if not args.topic and not args.niche:
        niche_data = run_niche_tool(args)
        if niche_data and niche_data.get("picked"):
            args.topic = niche_data["picked"]
            args.niche = niche_data["picked"]
    elif args.find_niche:
        niche_data = run_niche_tool(args)
    if not args.topic:
        args.topic = args.niche
    if not args.topic:
        print("no topic: give --topic, give --niche, or run with "
              "--find-niche (or no --topic) so the niche finder "
              "picks one.", file=sys.stderr)
        return 2

    out_dir = Path(args.out) if args.out else (
        ROOT / "out" / f"{slugify(args.topic)}-{date.today().isoformat()}")
    out_dir.mkdir(parents=True, exist_ok=True)

    llm = MockLLM()
    print("Creator OS — combined pipeline (MOCK, $0)")
    print(f"topic: {args.topic} | format: {args.format}")
    print(f"out: {out_dir}\n")

    concept: dict | None = None

    def do_concept():
        nonlocal concept
        path, concept = stage_concept(args, out_dir)
        return path

    stages = [
        ("Niche finder", lambda: stage_niche(args, out_dir, niche_data)),
        ("Plan", lambda: stage_plan(args, out_dir)),
        ("Research", lambda: stage_research(args, out_dir, llm)),
        ("Concept score", do_concept),
        ("Script", lambda: stage_script(args, out_dir, llm, concept)),
        ("Visual + Package", lambda: stage_visual(args, out_dir, llm)),
        ("Video", lambda: stage_video(args, out_dir)),
        ("Edit", lambda: stage_edit(args, out_dir)),
        ("Caption + SEO", lambda: stage_caption(args, out_dir, llm)),
        ("Publish prep", lambda: stage_publish(args, out_dir, llm)),
        ("Report", lambda: stage_report(args, out_dir, llm)),
        ("Upload", lambda: stage_upload(args, out_dir)),
        ("Next plan (loop)", lambda: stage_loop(args, out_dir)),
    ]
    written = []
    for name, fn in stages:
        path = fn()
        written.append(path)
        print(f"  [ok] {name} -> {path.name}")

    print(f"\n{len(written)} stage files written to {out_dir}")
    print(f"mock LLM calls: {llm.calls} | spend: $0.00")
    print("Nothing was published, sent, or scheduled.")
    print("Upload: only if --auto-upload + YOUTUBE_UPLOAD_ENABLED=1 "
          "with the owner's credentials (see 09-upload.md).")
    print("\nship it, or change it?")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
