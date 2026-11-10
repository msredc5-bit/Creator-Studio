#!/usr/bin/env python3
"""Creator Studio — one-command setup.

Installs the Creator Studio skills into your AI agent's skills
directory, so you can tell your agent "set this up for me" and then
just talk to it. Stdlib only, no network, no secrets, $0.

Usage:
  python3 setup.py                  # auto-detect the skills dir
  python3 setup.py --check          # dry run: print what it WOULD do
  python3 setup.py --target DIR     # install into DIR instead
  python3 setup.py --force          # overwrite skills already there

What it does:
  1. Checks Python is 3.10+ (exits with a clear error if not).
  2. Finds the agent skills directory:
       - Muse: ~/workspace/custom-skills (when that path exists)
       - Claude Code: ~/.claude/skills (when ~/.claude exists)
       - or --target DIR (always wins)
     If none can be found, it exits and tells you exactly what to do.
  3. Copies skills/creator-studio + every youtube-skills/* skill
     into it. Existing skills are NEVER overwritten unless --force.
  4. Creates video_providers.yaml from the built-in default, but
     only if the file is missing (never touches an existing one).
  5. Prints the exact next steps (first-run commands).

It never touches the network, never asks for a key, and never
publishes or uploads anything. Run `bash setup.sh` for the same
thing with a friendlier error when python3 is missing.
"""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

MIN_PYTHON = (3, 10)
ROOT = Path(__file__).resolve().parent
ENTRY_SKILL = ROOT / "skills" / "creator-studio"
YT_SKILLS = ROOT / "youtube-skills"
CONFIG = ROOT / "video_providers.yaml"

# The fallback config, used ONLY when video_providers.yaml is missing
# from the repo checkout. No secrets in it — keys come from the
# environment only, never from this file.
DEFAULT_VIDEO_PROVIDERS_YAML = """# Video providers — Creator OS video stage (stage 4).
# NO SECRETS IN THIS FILE. API keys live ONLY in environment
# variables (VIDEO_API_KEY etc.) — never here, never committed.
# Valid providers: auto, footage, stills, local, api
#   auto    — footage if --footage is given, else stills (the $0 default).
#   footage — real footage from --footage. Preferred whenever given.
#   stills  — AI stills (Pollinations, free, no key) + Ken Burns motion.
#   local   — open-source video models on YOUR machine (WanGP/FramePack).
#             Needs a CUDA GPU.
#   api     — paid cloud video via a generic HTTP adapter (Muapi Sora
#             is the documented example). Needs your own paid key.
provider: auto
fallback: null
retries: 1
local:
  engine: wangp
  command: ""
  wangp_dir: ""
  queue: ""
  output_dir: ""
  timeout: 1800
api:
  url: https://api.muapi.ai/api/v1/openai-sora-2-text-to-video
  poll_url: https://api.muapi.ai/api/v1/predictions/{request_id}/result
  key_env: VIDEO_API_KEY
  model: openai-sora-2-text-to-video
  body_json: '{"prompt": "", "aspect_ratio": "16:9", "duration": 8, "resolution": "1080p"}'
  timeout: 900
  poll_interval: 15
"""


def fail(message: str) -> int:
    print(f"setup.py: ERROR: {message}", file=sys.stderr)
    return 2


def check_python() -> int | None:
    if sys.version_info < MIN_PYTHON:
        return fail(
            f"Python {MIN_PYTHON[0]}.{MIN_PYTHON[1]}+ is required, "
            f"but this python3 is {sys.version.split()[0]}. "
            "Install a newer Python (python.org/downloads) and "
            "re-run: python3 setup.py")
    return None


def check_layout() -> int | None:
    missing = []
    if not (ENTRY_SKILL / "SKILL.md").exists():
        missing.append("skills/creator-studio/SKILL.md")
    if not YT_SKILLS.is_dir():
        missing.append("youtube-skills/")
    if missing:
        return fail(
            "this does not look like a Creator Studio checkout — "
            f"missing: {', '.join(missing)}. Run setup.py from the "
            "repo root (the folder you cloned from "
            "https://github.com/msredc5-bit/Creator-Studio).")
    return None


def detect_targets() -> list[Path]:
    """Agent skills directories found on this machine, best first."""
    home = Path.home()
    found: list[Path] = []
    # Muse: the skills folder lives inside the Muse workspace.
    muse_dir = home / "workspace" / "custom-skills"
    if muse_dir.is_dir():
        found.append(muse_dir)
    # Claude Code: ~/.claude/skills (created on install if needed).
    claude_home = home / ".claude"
    if claude_home.is_dir():
        found.append(claude_home / "skills")
    return found


def skill_sources() -> list[tuple[str, Path]]:
    """(skill name, source dir) for every skill this repo ships."""
    sources = [("creator-studio", ENTRY_SKILL)]
    for child in sorted(YT_SKILLS.iterdir()):
        if child.is_dir() and (child / "SKILL.md").exists():
            sources.append((child.name, child))
    return sources


def plan(target: Path) -> list[tuple[str, Path, Path]]:
    """One row per skill: (name, source, dest)."""
    return [(name, src, target / name)
            for name, src in skill_sources()]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Install Creator Studio skills into your AI "
                    "agent's skills directory. No network, no keys, $0.")
    ap.add_argument("--target", default="",
                    help="Skills directory to install into "
                         "(overrides auto-detection).")
    ap.add_argument("--check", action="store_true",
                    help="Dry run: print what WOULD happen, change "
                         "nothing.")
    ap.add_argument("--force", action="store_true",
                    help="Overwrite skills that already exist in the "
                         "target (default: never overwrite).")
    args = ap.parse_args(argv)

    err = check_python()
    if err is not None:
        return err
    err = check_layout()
    if err is not None:
        return err

    if args.target:
        target = Path(args.target).expanduser()
        detected = False
    else:
        found = detect_targets()
        if not found:
            return fail(
                "no agent skills directory found on this machine. "
                "Either install Claude Code (it creates ~/.claude/skills), "
                "or point setup.py at a folder yourself: "
                "python3 setup.py --target /path/to/skills")
        target = found[0]
        detected = True

    rows = plan(target)
    config_missing = not CONFIG.exists()

    print("Creator Studio setup")
    print(f"  skills dir: {target}"
          f"{' (auto-detected)' if detected else ' (--target)'}")
    print(f"  skills to install: {len(rows)} "
          f"(creator-studio + {len(rows) - 1} yt-* skills)")
    print(f"  video_providers.yaml: "
          f"{'missing — will create from default' if config_missing else 'exists — will leave it alone'}")
    if args.check:
        print("\n--check: dry run, nothing was changed.\n")
    print()

    copied, skipped, overwritten = [], [], []
    for name, src, dest in rows:
        exists = dest.exists()
        if args.check:
            action = ("overwrite (exists — --force)"
                      if exists and args.force else
                      "skip (already there)"
                      if exists else "copy")
            print(f"  [{action}] {name} -> {dest}")
            continue
        if exists and not args.force:
            skipped.append(name)
            continue
        if exists:
            shutil.rmtree(dest)
            overwritten.append(name)
        else:
            copied.append(name)
        shutil.copytree(src, dest)

    if not args.check and config_missing:
        CONFIG.write_text(DEFAULT_VIDEO_PROVIDERS_YAML, encoding="utf-8")
        print(f"  [created] {CONFIG.name} (built-in default, no secrets)")

    print()
    if args.check:
        print("Dry run done — re-run without --check to install.")
        return 0
    if copied:
        print(f"Installed {len(copied)} skill(s): {', '.join(copied)}")
    if overwritten:
        print(f"Overwrote {len(overwritten)} (--force): "
              f"{', '.join(overwritten)}")
    if skipped:
        print(f"Skipped {len(skipped)} already installed "
              f"(re-run with --force to overwrite): "
              f"{', '.join(skipped)}")
    print()
    print("Next steps — first run (from this repo folder):")
    print()
    print("  python3 scripts/creator_os_run.py --find-niche "
          "--format \"short video\"")
    print("    # no idea yet? the niche finder picks one, then the")
    print("    # pipeline plans, researches, scripts, builds the")
    print("    # video and hands you 13 stage files in out/")
    print()
    print("  python3 scripts/creator_os_run.py --topic "
          "\"AI tools for beginners\" --format \"short video\"")
    print("    # you already know the topic")
    print()
    print("Or just tell your agent: \"run Creator Studio for me\" —")
    print("it reads skills/creator-studio/SKILL.md and does the rest.")
    print("Nothing publishes or uploads without your exact word.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
