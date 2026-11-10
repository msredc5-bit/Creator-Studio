---
name: creator-studio
description: >-
  Run Creator Studio — the 13-stage content pipeline that turns one idea
  (or no idea: it finds a viral niche for a fresher) into a finished
  video with script, hook/title scores, captions, and a next-video plan.
  Use for "make a video", "find me a niche", "plan my channel",
  "score my concept", "upload my video", or any YouTube content job.
  Nothing publishes or uploads without the owner's exact word.
---

# Creator Studio

One idea in, thirteen stage files out — plan, research, script, video,
captions, publish checklist, and a plan for the *next* video learned
from the last one's numbers. All local, $0 by default. **Nothing here
publishes, uploads, sends, schedules, or spends without the owner's
exact word.**

## YOU ARE THE BRAIN — read this before you run anything

The pipeline writes `[MOCK DRAFT]` **scaffolds only** — a checklist
with the shape of each stage, never real content. It cannot write a
real script, real research, or real captions, and no LLM API key is
needed to fix that: **you, the agent (Claude / Muse), ARE the
brain.** You are an LLM yourself — you do the writing, the pipeline
does the building. The pipeline is the checklist and the builder,
never the writer.

**Two-pass flow — always do both passes:**

- **Pass 1 — mock run (the demo).** Run the pipeline once. It proves
  all 13 stages work end to end, $0, no keys, no signup. Show the
  owner the stage files and say plainly: this is the demo — the
  script, research, and captions inside are scaffolds, not the
  video's real words.
- **Pass 2 — you write the real content.** Read the stage files you
  just made. Then write the REAL research, script, captions, and
  description yourself — in the owner's voice (read
  `youtube-skills/VOICE.md` first, or the channel's own videos) —
  replacing each `[MOCK DRAFT]` scaffold in the stage files. Never
  present a scaffold as finished work. Then write `vo-lines.txt`
  into the out dir (one voiceover line per line; the first 3 lines
  are the video's 3 scenes) and re-run with `--script vo-lines.txt`
  so the video stage speaks YOUR lines, not the templates. The
  re-run rebuilds the video and the thumbnail; everything else in
  the out dir stays.

A run that stops at pass 1 is a demo, not a video. Never tell the
owner a pass-1 run is ready to upload.

## The 13 stages (one run, in order)

| # | Stage | What it does | Output |
|---|---|---|---|
| 0a | Niche finder | Scores candidate niches 1–10 (demand 30%, competition-gap 30%, monetization 25%, fresher-fit 15%). Runs when `--find-niche` is passed or no `--topic` is given. Skipped honestly when the topic is already known. | `00-niche.md` |
| 0b | Plan | Weekly plan from hours available (yt-plan). Reads the last run's `next-brief.json` — the closed loop. | `00-plan.md` |
| 1 | Research | Topic research + yt-viral swipe.py (outlier videos in the niche, vs their own channel median). | `01-research.md` |
| 2a | Concept score | Scores 3–5 video concepts 1–10 (hook 40%, trend-fit 25%, competition-gap 20%, fresher-fit 15%). Only 7+ counts as strong. The picked concept feeds the Script stage. | `02-concept-score.md` |
| 2b | Script | Script draft + hookscore.py (21 hook formulas). | `02-script.md` |
| 3 | Visual + Package | Visual plan + title.py (title + thumbnail linted as one pairing, /100). | `03-visual-package.md` |
| 4 | Video | Reel Factory build: real footage when `--footage` is given, else AI stills (Pollinations, free) + slow Ken Burns motion, TTS voiceover, burned-in captions, exact-logo end card. Or true AI video motion from the owner's GPU (`local`) or paid key (`api`). | `04-video.md` + `video.mp4` |
| 5 | Edit | deadair.py + chapters.py + yt-shorts. Needs `--transcript`; skipped honestly without one. | `05-edit.md` |
| 6 | Caption + SEO | Caption pack + description/tags draft. | `06-caption-seo.md` |
| 7 | Publish prep | Checklist ONLY. `ready_to_publish: false`. Never publishes. | `07-publish-prep.md` |
| 8 | Report | Report template + retention.py (reads the owner's retention CSV). yt-audit / yt-comment are post-publish only. | `08-report.md` |
| 9 | Upload | **DEFAULT OFF.** Runs only with `--auto-upload` AND `YOUTUBE_UPLOAD_ENABLED=1` AND the owner's own YouTube OAuth credentials. `--upload-dry-run` prints what WOULD upload, no network. | `09-upload.md` |
| 10 | Next plan | Reads the last run's `08-report.md` + retention CSV, writes the next video's plan + `next-brief.json` for the next run's Plan stage. Honest when there is no performance data yet. | `10-next-plan.md` + `next-brief.json` |

## How to run it

```bash
# From the repo root. Python 3.10+, no install step, no keys, $0.
python3 scripts/creator_os_run.py --topic "AI tools for beginners" --format "short video"

# No idea yet? The niche finder picks one:
python3 scripts/creator_os_run.py --find-niche --format "short video"

# Real footage instead of generated stills:
python3 scripts/creator_os_run.py --topic "..." --format "short video" --footage clips.mp4

# Long video, with your own inputs:
python3 scripts/creator_os_run.py --topic "..." --format "long video" \
    --niche "US home-service owners" --audience "plumbers who miss calls" \
    --transcript transcript.srt --retention retention.csv \
    --collected collected.json --hours 6
```

Output: `out/<slug>-<YYYY-MM-DD>/` — one markdown file per stage plus
`next-brief.json`. The run ends by printing **"ship it, or change
it?"** and exits. Show the stage files to the owner; do not publish
anything yourself.

That first run is only pass 1 (the demo — see YOU ARE THE BRAIN
above). Pass 2 is where the real video comes from: you write the
real content into the stage files, write `vo-lines.txt` (one
voiceover line per line, first 3 = the 3 scenes) into the out dir,
and re-run with `--script`:

```bash
# Pass 2: the video speaks your lines, not the templates.
python3 scripts/creator_os_run.py --topic "AI tools for beginners" --format "short video" \
    --out out/<slug>-<YYYY-MM-DD> --script out/<slug>-<YYYY-MM-DD>/vo-lines.txt
```

## Defaults ($0) and the two things that cost

- **Default is free:** mock writing (offline, deterministic, always
  labelled `[MOCK DRAFT]`) — and YOU replace it with real writing
  in pass 2 (see YOU ARE THE BRAIN). AI-stills video (Pollinations,
  no key).
- **True AI video motion costs the owner** — their own CUDA GPU
  (`--video-provider local`, WanGP/FramePack) or their own paid key
  (`--video-provider api`, e.g. Muapi Sora). Keys live ONLY in
  environment variables, never in files. Without a GPU/key the stage
  fails honestly and names the exact missing input. Three paths, one
  line each: a GPU → `local` (full guide:
  `docs/gpu-video-setup.md`; check first with
  `--video-provider local --video-dry-run`, which prints the exact
  command and missing setup without executing anything); no GPU →
  `stills` (the default — AI stills + motion, NOT true motion);
  a paid video tool → `api` (any submit → poll → download API:
  set `api.url`, `api.poll_url`, `api.body_json`) or `local` with
  a `custom` command for any local tool.
- **Upload costs nothing but setup** — the owner's own YouTube OAuth
  (see below). Never upload without their exact word (`upload it`).

## Gates (never bend these)

- `ok` — plan / research / script / visual / video / caption / report.
- `post it` — publish a post. `upload it` — upload a video.
- Stage 7 is a checklist, never a publish. Stage 9 is off unless the
  owner turns it on twice (flag + env var) with their own
  credentials. Privacy defaults to `private` — never public by
  accident.

## Rules

- Never invent a number, a client, a testimonial, a price, or a
  result. Mock samples are labelled SAMPLE, never findings.
- No dental/medical targeting. No copyrighted music, characters, or
  copied work. No real person's face/voice imitation.
- Performance numbers are never estimated — only what the owner
  pastes from the platforms.
- Brand is Talvenor only (in this repo's own content). The logo is
  pasted flat from the exact file, never redrawn.

## Where the parts live (repo root)

```
skills/creator-studio/SKILL.md  — this file (the entry skill)
youtube-skills/                 — 12 yt-* skills, one SKILL.md each:
  yt-niche, yt-plan, yt-viral, yt-script, yt-package, yt-edit,
  yt-chapters, yt-shorts, yt-seo, yt-retention, yt-audit, yt-comment
  Each skill is a playbook: read it before doing that one job.
  (Adapted from Jake Schincariol's youtube-agent-skill, MIT —
  original copyright retained, see youtube-skills/UPSTREAM-LICENSE.)
tools/                          — 8 local Python tools, stdlib only:
  niche_score.py, concept_score.py, and the yt-* tools inside
  youtube-skills/*/ (hookscore.py, title.py, deadair.py,
  chapters.py, retention.py, swipe.py). They score, lint, and read
  files the owner supplies — they do not fetch or log in anywhere.
src/                            — the 6 Creator Studio workers
  (TopicResearcher, ScriptWriter, VisualProducer, CaptionWriter,
  PublishPrep, PerformanceTracker) + vendored worker base.
scripts/creator_os_run.py       — the 13-stage runner
scripts/video_build.py          — Reel Factory video stage
scripts/video_providers.py      — pluggable video providers
scripts/gen_visuals.py          — free still generation (Pollinations)
scripts/upload_youtube.py       — stage 9 (YouTube Data API v3)
scripts/loop_next.py            — stage 10 (closed loop)
video_providers.yaml            — provider config (no secrets in it)
youtube-skills/VOICE.md         — DRAFT voice profile: correct it from
  the owner's real videos before the first script ships, or the
  writing will not sound like them.
tests/test_combined.py           — pytest, mock end-to-end (39 tests)
INSTALL.md                      — setup for a new person (3 ways)
```

Load a yt-* skill when you do that one job (e.g. read `yt-script`
before writing a script, `yt-viral` before researching a niche).
The runner already wires the tools into the stages — you do not need
to call them by hand for a normal run.

## Upload setup (only when the owner asks for it)

1. Google Cloud Console: a project with **YouTube Data API v3**
   enabled + an OAuth consent screen + a Desktop-app OAuth client.
   Download the client secrets JSON.
2. `YOUTUBE_UPLOAD_ENABLED=1` and the secrets path
   (`--upload-credentials client_secrets.json` or env
   `YOUTUBE_CLIENT_SECRETS_FILE`); the stored token goes in
   `--upload-token` / `YOUTUBE_TOKEN_FILE`.
3. First run with `--upload-dry-run` (prints the plan, no network),
   then `--auto-upload` with the owner's `upload it`.
4. Without credentials, stage 9 fails honestly in `09-upload.md`
   with the exact setup steps — never a fake upload.

## Before the first real script ships

Read `youtube-skills/VOICE.md`. If it is still the draft, ask the
owner for three of their own videos (or transcripts) and write the
voice profile from those. A script in the wrong voice is worse than
no script.
