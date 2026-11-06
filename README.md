# Creator OS — Combined Content System

**One idea in, nine stage drafts out. Nothing publishes until the
owner says so.**

Creator OS joins two systems that were built separately into one
pipeline:

| Half | What it is | Lives in |
|---|---|---|
| **Creator Studio** (engine) | 6 Python workers that run the content flow for ANY platform and format — research, script, visual, caption, publish prep, report. Standalone now: vendored worker base, no other checkout needed. | `src/` |
| **YouTube Agent** (skill pack) | 11 instruction skills + 6 local scoring tools, YouTube only. Adapted from Jake Schincariol's youtube-agent-skill (MIT — original copyright retained, see `LICENSE`). | `youtube-skills/` |

They are **not the same thing**: different code, different job,
different origin. Creator Studio is a running program with workers;
YouTube Agent is a set of skills and tools loaded one at a time. This
repo wires the YouTube tools into the Creator Studio stages, so one
run produces the full pipeline with real hook scores, title lints,
edit lists, chapters, and retention reads — all local, all $0.

## The combined pipeline

```
CEO decision (gate: ok)
  0. Plan         — yt-plan (weekly plan, from hours available)
  1. Research     — TopicResearcher + yt-viral swipe.py
  2. Script       — ScriptWriter + yt-script hookscore.py (21 formulas)
  3. Visual+Pack  — VisualProducer + yt-package title.py (title+thumb)
  4. Video        — Reel Factory build: real footage + TTS voiceover
                    + burned-in captions + exact-logo end card.
                    Without --footage it writes the production plan
                    + the exact missing inputs and builds no video.
  5. Edit         — yt-edit deadair.py + yt-chapters + yt-shorts
                    (needs --transcript, else skipped honestly)
  6. Caption+SEO  — CaptionWriter + yt-seo (description + tags)
  7. Publish prep — PublishPrep ONLY — gate: "post it" / "upload it"
  8. Report       — PerformanceTracker + yt-retention retention.py
                    (+ yt-audit, yt-comment — post-publish only)
```

## Run it (mock, $0)

```bash
python3 -m pytest tests/ -q
python3 scripts/creator_os_run.py --topic "AI receptionist for plumbers" \
    --format "short video"
```

With inputs (all optional):

```bash
python3 scripts/creator_os_run.py --topic "AI receptionist for plumbers" \
    --format "long video" --niche "US home-service owners" \
    --audience "plumbers who miss calls on the job" \
    --transcript transcript.srt --retention retention.csv \
    --collected collected.json --hours 6 \
    --footage footage.mp4 --voice avocado_v2:MAI_01
```

Output: `out/<slug>-<YYYY-MM-DD>/` with one markdown draft per
stage (`00-plan.md` … `08-report.md`). The run ends by printing
**"ship it, or change it?"** and exits.

## The video stage (stage 4, Reel Factory)

Needs: real footage — one video file, or a folder of clips, passed
with `--footage <path>`. The story order is fixed: (1) a real worker
working, (2) a phone ringing and missed, (3) Talvenor answering and
booking. Real footage only; no stills with motion.

Produces (video formats only): `<out-dir>/video.mp4` — footage
scaled/cropped to 9:16 1080x1920 for short video (16:9 1920x1080 for
long video), 30fps, H.264 + AAC, faststart — plus `04-video.md`,
which records exactly what was built (scenes, voiceover lines, end
card, verification) and any fallbacks. Intermediates live in
`<out-dir>/video_work/` so the build is rebuildable.

- Voiceover: the three templated brand lines, spoken by the
  `tts` binary (default voice `avocado_v2:MAI_01` — Sophia/Aria;
  override with `--voice`). If synthesis fails, that line plays
  silent and the stage file says so — never a fake voice claim.
- Captions: line-level, burned in verbatim from the voiceover text
  (not word-level karaoke — the faster-whisper caption helper is not
  present on this machine).
- End card: 3s, exact logo lockup from
  `~/workspace/talvenor-brand/logos/talvenor-logo.png`, pasted flat
  on black, never redrawn, with the brand line "You run the jobs.
  We run the phone." and the CTA "Book a call with Talvenor.
  Link in bio."
- Without `--footage` (or with `--no-video`): the stage still runs
  and writes its plan + the exact missing inputs. It builds no
  video and claims none.

Honest limits: no AI text-to-video generation exists here
(region-blocked) — footage-based assembly only. The video is a
local file; the run never uploads it (gate: `upload it`).

## Gates (the rule that never bends)

- `ok` — plan / research / script / visual / video / caption / report.
- `post it` — publish a post. `upload it` — upload a video.
- Nothing publishes, uploads, sends, schedules, or spends from this
  repo. Stage 7 is a checklist with `ready_to_publish: false`.
  The owner publishes, if at all, with their exact word.

## File map

```
README.md                  — this file
LICENSE                    — MIT (Jake Schincariol + combined work)
.gitignore
src/
  __init__.py
  creator_workers.py       — the 6 Creator Studio workers
  workers/
    base.py                — vendored WorkerBase + Task + MockLLM
                             (+ LiveLLMProvider hook, unwired by design)
scripts/
  creator_os_run.py        — the 9-stage combined runner
  video_build.py           — Reel Factory video stage (FFmpeg + tts,
                             footage-based assembly only)
tests/
  test_combined.py         — pytest, mock end-to-end (replaces the old
                             boss-ceo-dependent test_creator.py)
youtube-skills/            — 11 yt-* skills, 6 Python tools, hooks.json,
                             VOICE.md (DRAFT), UPSTREAM-LICENSE
                             (untouched from the adaptation)
out/                       — generated stage drafts (gitignored)
```

## Honest status

- **Mock by default.** Workers draft through MockLLM (offline,
  deterministic, $0). Mock output is always labelled `[MOCK DRAFT]`
  — replace it with a real draft before shipping.
- **YouTube tools are real local Python** (stdlib only, no network,
  no keys). They score, lint, and read files you supply — they do
  not fetch, scrape, upload, or log in anywhere.
- **VOICE.md is a DRAFT** until Boss corrects it — he has no YouTube
  videos yet, so no transcript exists to copy. Correct it before the
  first script ships.
- **Stages that need your files say so.** No transcript → stage 5 is
  skipped honestly. No retention export → stage 8 reads nothing.
  No collected videos → swipe.py does not run. No footage → stage 4
  builds no video and names the exact footage needed. Missing inputs
  are named, never invented.
- **No network calls anywhere in `src/`, `scripts/`, or `tests/`**
  (enforced by a test). The live-LLM hook (`LiveLLMProvider` in
  `src/workers/base.py`) reads its key only from the environment
  variable `CREATOR_OS_LLM_API_KEY` and is deliberately unwired —
  this repo makes no network calls by design.
- **Performance numbers are never estimated** — only what the owner
  pastes from the platforms.

## Rules (inherited from both halves — unchanged)

- No invented stats, clients, testimonials, prices, or results.
- No copyrighted music, characters, or copied work. No real
  person's face/voice imitation.
- Brand is Talvenor only. No dental/medical targeting.
- $0 spend.

## Attribution

YouTube skills adapted from
[Jake Schincariol's youtube-agent-skill](https://github.com/Jakeschincariol/youtube-agent-skill)
(MIT, original copyright (c) 2026 Jake Schincariol retained).
Boss's adapted copy lives at
https://github.com/msredc5-bit/youtube-agent-multi (private).
The 21 hook formulas, checklists, workflows, and scoring rules are
the original author's work, preserved as-is; only the tool-coupling
mechanics were changed (see the adaptation changelog in the YouTube
repo).

## GitHub status (2026-11-06)

- Pushed 2026-11-06 23:24 Dhaka:
  https://github.com/msredc5-bit/Creator-Studio (PRIVATE),
  commit `53a5a99b`, 29 files (the 8-stage combined repo).
- The video stage (stage 4) was added after that push and is **not
  pushed yet** — pushing is a separate step, handled by the parent.
