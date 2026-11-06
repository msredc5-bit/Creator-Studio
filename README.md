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
  4. Video        — Reel Factory build through a pluggable video
                    provider (see "Video providers" below): real
                    footage when --footage is given, otherwise the
                    configured provider — AI-generated stills
                    (Pollinations, free) + slow Ken Burns motion by
                    default, or true AI video motion from a local
                    model (your GPU) or a paid cloud API (your key).
                    With --no-gen-visuals and no footage it writes
                    the production plan + the exact missing inputs
                    and builds no video.
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

No footage? Just leave `--footage` out — the video stage generates
its own stills (see below) and the run still ends with a real
`video.mp4`. Pass `--no-gen-visuals` to turn generation off.
Pass `--video-provider local` (your GPU) or `--video-provider api`
(your paid key) for true AI video motion instead of stills —
see "Video providers" below.

Output: `out/<slug>-<YYYY-MM-DD>/` with one markdown draft per
stage (`00-plan.md` … `08-report.md`). The run ends by printing
**"ship it, or change it?"** and exits.

## The video stage (stage 4, Reel Factory)

Two visual sources, in order of preference:

1. **Real footage (preferred)** — one video file, or a folder of
   clips, passed with `--footage <path>`. The story order is fixed:
   (1) a real worker working, (2) a phone ringing and missed,
   (3) Talvenor answering and booking. Real footage only; when it
   is supplied, no stills are ever generated.
2. **AI-generated stills (default when no footage is given)** — the
   stage generates one still per scene itself (Pollinations.ai,
   free, no API key — see `scripts/gen_visuals.py`) and gives each
   still slow Ken Burns motion (FFmpeg zoompan: zoom in, zoom out,
   slow pan). Topic in, video out, no footage input needed. Turn
   it off with `--no-gen-visuals`; force it on with
   `--gen-visuals` (it is already the default when no footage is
   supplied).

Produces (video formats only): `<out-dir>/video.mp4` — visuals
scaled/cropped to 9:16 1080x1920 for short video (16:9 1920x1080 for
long video), 30fps, H.264 + AAC, faststart — plus `04-video.md`,
which records exactly what was built (visual source, scenes,
voiceover lines, end card, verification) and any fallbacks.
Intermediates live in `<out-dir>/video_work/` (stills in
`video_work/stills/`) so the build is rebuildable.

- Generation details: prompts show workers from behind / hands /
  over-the-shoulder — never a recognizable face, never a named real
  person. One retry with a simpler prompt per scene; a scene that
  still fails gets a plain dark slate, recorded honestly. If all 3
  scenes fail, no video is built and the stage file records exactly
  why. The bottom 8% of each still is cropped (Pollinations
  watermark corner).
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
- Without `--footage` AND with `--no-gen-visuals` (or with
  `--no-video`): the stage still runs and writes its plan + the
  exact missing inputs. It builds no video and claims none.

Honest limits: the $0 default visual source is AI stills + motion,
not real footage and not true AI video motion. Generated stills are
draft quality (free sana model: soft detail, weak prompt
adherence, occasional watermark) — good enough to prove the
pipeline end to end, not final creative. True AI video motion is
available through the pluggable providers (see below) — local
models on the user's own GPU, or a paid cloud API on the user's
own key. Neither is wired to a GPU or a key here. The video is a
local file; the run never uploads it (gate: `upload it`).

## Video providers

The Video stage (stage 4) builds from one of four **pluggable
video providers**. Whoever has the hardware or the paid key uses
it; whoever doesn't gets an honest missing-input list instead of
a fake video. A provider is never silently swapped unless a
fallback is set in the config.

| Provider | What it is | What the user needs | Cost | What it produces | Status |
|---|---|---|---|---|---|
| `footage` | Real video files the user supplies (`--footage`) | A video file or a folder of clips | $0 | The real footage, cut to 3 scenes | **Works** — always preferred when footage is given |
| `stills` | AI-generated stills (Pollinations, free) + slow Ken Burns motion | Nothing — no key, no GPU | $0 | AI stills + motion (not true AI video, not real footage) | **Works, free** — the default |
| `local` | Open-source local video models on the user's own machine (WanGP, FramePack, or a custom command) | A CUDA GPU + the model installed (see below) | $0 after hardware | True AI video motion, 5s clips per scene | **Code ready, NOT VERIFIED here** — this machine has no GPU; adapter is unit-tested with mocks only |
| `api` | Paid cloud video via a generic HTTP adapter (Muapi Sora / Runway as the documented example) | A paid API key + billing on the provider | Pay-per-request (see below) | True AI video motion, 5s clips per scene | **Code ready, NOT verified with a real call** — tested against a fake local server only |

### How to switch

- Flag: `--video-provider {footage|stills|local|api|auto}` (default
  `auto` — footage if given, else the configured provider, else
  stills). A bad flag value is rejected by the runner with a clear
  error.
- Config: `video_providers.yaml` at the repo root (documented, no
  secrets in it) — `provider:`, `fallback:`, `local:` (engine,
  command, wangp_dir, output_dir, timeout), `api:` (url, poll_url,
  model, body_json, timeout, poll_interval). Use `--video-config`
  to point at a different file.
- Environment: `VIDEO_PROVIDER`, `VIDEO_API_KEY`, `VIDEO_API_URL`,
  `VIDEO_MODEL`, `LOCAL_VIDEO_CMD`. **Keys live only in environment
  variables — never in files, never in the repo.**
- Precedence: `--video-provider` flag > `VIDEO_PROVIDER` >
  `video_providers.yaml` > default (`stills`).
- Honest failure: a missing binary, GPU, or key stops the stage
  with the exact missing item in `04-video.md` and builds no
  video. `--no-gen-visuals` still disables the stills provider
  only.

### Local provider — setup

1. Install WanGP (`deepbeepmeep/WanGP`) or FramePack
   (`lllyasviel/FramePack`) on your own machine and download the
   model weights.
2. Set `local.engine` (`wangp` / `framepack` / `custom`) and the
   path in `video_providers.yaml` (`local.wangp_dir`,
   `local.command`, or `LOCAL_VIDEO_CMD`).
3. Run with `--video-provider local`.

Requirements, verified from the projects' own READMEs (2026-11-07):

- **WanGP:** "8 GB of VRAM is enough to get started"; "run select
  models with as little as 4 GB of VRAM" — Wan 2.1 T2V 1.3B is the
  fastest/lowest-VRAM model (6 GB), 14B is the best quality
  (12 GB+). Headless batch mode is documented: create a queue in
  the web UI, "Save Queue", then `python wgp.py --process
  my_queue.zip`.
- **FramePack:** "the minimal required GPU memory is 6GB. (Yes
  6 GB, not a typo. Laptop GPUs are okay.)" Needs Nvidia RTX
  30XX/40XX/50XX, Linux or Windows, Python 3.10; models 30 GB+
  from Hugging Face. FramePack ships as a Gradio desktop app
  (`demo_gradio.py`) — **no official headless CLI was found in its
  README, so its CLI invocation is UNVERIFIED**; the adapter runs
  whatever command the user configures.

`local` is NOT verified on this machine (no GPU here): the adapter
code and its mock tests pass, but no real local generation has
been run or claimed.

### API provider — setup

1. Create an account with a paid video provider and buy credits.
2. Set `VIDEO_API_KEY` (and `VIDEO_API_URL` / `VIDEO_MODEL` if you
   use anything other than the Muapi default) in your environment.
3. Run with `--video-provider api`.

Documented example — **Muapi** (muapi.ai, the Open Generative AI
pay-per-call backend), verified from its official docs
(2026-11-07): POST `https://api.muapi.ai/api/v1/<endpoint>` with
header `x-api-key: YOUR_API_KEY` and a JSON body; the response
carries `request_id`; poll
`GET https://api.muapi.ai/api/v1/predictions/REQUEST_ID/result`
until the status is completed, then download the video URL from
the outputs. Sora 2 text-to-video body:
`{"prompt": "...", "aspect_ratio": "16:9", "duration": 8,
"resolution": "1080p"}`. Prices shown on Muapi's docs 2026-11-07
(check the live Playground before shipping — prices change):
Sora 2 standard $0.80/request (720p, 8s), Sora 2 Pro $2.40/request
(up to 1080p), Sora 2 Pro Storyboard $0.58/request, original Sora
$0.50/request; Runway text-to-video $0.09/request, image-to-video
$0.15/request, Act Two i2v $0.07, Act Two v2v $0.30, Aleph v2v
$0.20. The adapter defaults to Sora 2 standard; set `api.model`
and `api.body_json` for anything else.

**Other paid providers (Runway, Kling, Luma, Veo direct APIs) are
NOT documented here** — their endpoints were not verified from
official docs while writing this, so they are left out rather
than guessed. The generic adapter accepts any provider whose
submit → poll → download shape matches Muapi's; configure
`api.url`, `api.poll_url`, and `api.body_json` accordingly.

`api` is NOT verified with a real call: no key exists here and no
paid call was made. The adapter is tested against a fake local
HTTP server that returns a canned clip.

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
                             resolves the video provider, then
                             builds from its visuals)
  video_providers.py       — pluggable video providers
                             (footage / stills / local / api) —
                             the second network-calling module:
                             the api provider calls a paid video
                             API only when the user configures it
                             with their own key
  gen_visuals.py           — AI still generation (Pollinations, free,
                             no key) — a network-calling module
video_providers.yaml       — provider config (documented, no
                             secrets): provider, fallback, local,
                             api — keys come from the environment
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
  generates AI stills itself (or, with `--no-gen-visuals`, builds no
  video and names the exact footage needed). Missing inputs are
  named, never invented.
- **Almost no network calls.** The core pipeline (`src/`, the runner,
  the YouTube tools) makes no network calls. The two exceptions are
  `scripts/gen_visuals.py`, which fetches free stills from
  Pollinations.ai (no API key), and `scripts/video_providers.py`,
  whose api provider calls a paid video API only when the user
  configures it with their own key — both clearly documented in
  their modules and enforced by a test
  (`test_network_calls_only_in_documented_modules`).
  The live-LLM hook (`LiveLLMProvider` in `src/workers/base.py`)
  reads its key only from the environment variable
  `CREATOR_OS_LLM_API_KEY` and is deliberately unwired — this repo
  makes no other network calls by design.
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

## GitHub status (2026-11-07)

- Pushed 2026-11-06 23:24 Dhaka:
  https://github.com/msredc5-bit/Creator-Studio (PRIVATE),
  commit `53a5a99b`, 29 files (the 8-stage combined repo).
- Video stage pushed 2026-11-07 00:12, commit `e063d375`, 30 files;
  self-generating visuals pushed 2026-11-07 00:35, commit
  `e1556e5e`, 31 files.
- The pluggable video providers (this change) are **not pushed
  yet** — pushing is a separate step, handled by the parent.
