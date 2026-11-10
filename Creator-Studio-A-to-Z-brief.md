# Creator Studio — A-to-Z Brief

**One line:** A combined content factory — 6 worker agents + 12 YouTube skills + 8 real Python tools + a 13-stage pipeline + a pluggable Video stage — that turns one topic (or a niche it finds for a fresher) into a finished video (script, titles, captions, SEO, video file), uploads it only when the owner enables upload twice, and learns from the last video's numbers for the next one.

**Status (2026-11-10):** BUILT, TESTED, PUSHED. Repo: https://github.com/msredc5-bit/Creator-Studio (PRIVATE). Latest pushed commit `4abfa906` (2026-11-10) — 13 stages, pytest 42/42 green. The CI workflow (`.github/workflows/python-app.yml`) and `TESTING.md` are new in this change and not pushed yet — pushing is Boss's word, before the repo is flipped to public. Local folder: `~/workspace/creator-os-combined/`.

---

## 1. Who it is for

Any content creator who makes YouTube videos (or Shorts, carousels, blogs, podcasts) and wants the repetitive work — planning, research, scripting, titles, editing prep, captions, SEO, video assembly — done in one run, with a human deciding what ships.

## 2. The parts

| Part | What it is | Count |
|---|---|---|
| Workers | Small agents: each takes a task, drafts with an LLM, returns notes | 6 |
| Skills | Playbooks (SKILL.md): how to do one YouTube job well | 12 |
| Tools | Real Python programs that measure/cut/score | 8 |
| Runner | `scripts/creator_os_run.py` — runs the 13 stages in order | 1 |
| Video builders | `scripts/video_build.py` (Reel Factory assembly), `scripts/gen_visuals.py` (AI stills), `scripts/video_providers.py` (pluggable backends) | 3 |
| Upload | `scripts/upload_youtube.py` — YouTube Data API v3 resumable upload, DEFAULT OFF | 1 |
| Loop | `scripts/loop_next.py` — reads the last run's report + retention, writes the next brief | 1 |
| Config | `video_providers.yaml` — which video backend to use (no secrets) | 1 |

### The 6 workers (Creator Studio)

1. **TopicResearcher** — finds what to make, for whom
2. **ScriptWriter** — writes the script
3. **VisualProducer** — plans visuals, title + thumbnail pairing
4. **CaptionWriter** — captions + hashtags + CTA
5. **PublishPrep** — prepares the publish checklist (never publishes)
6. **PerformanceTracker** — reads results, advises the next video

### The 12 YouTube skills (11 adapted from Jake Schincariol's youtube-agent-skill, MIT + 1 new)

yt-plan, yt-script, yt-package, yt-edit, yt-chapters, yt-shorts, yt-retention, yt-seo, yt-viral, yt-comment, yt-audit. Each is a SKILL.md playbook. Attribution + MIT license retained. Plus **yt-niche** (new, 2026-11-10): pick a niche a fresher can start in.

### The 8 real tools (local Python, no network, no keys)

- `hookscore.py` — scores a hook against 21 formulas
- `title.py` — lints title + thumbnail as one pairing (score /100)
- `deadair.py` — finds dead-air cuts in a transcript
- `chapters.py` — drafts YouTube chapters from a transcript
- `retention.py` — reads a retention export, finds cliffs/leaks
- `swipe.py` — finds outlier videos in a niche (multiples of channel median)
- `tools/niche_score.py` — scores candidate niches 1-10 (demand 30% + competition-gap 30% + monetization 25% + fresher-fit 15%)
- `tools/concept_score.py` — scores video concepts 1-10 (hook 40% + trend-fit 25% + competition-gap 20% + fresher-fit 15%, adapted from the viral-clips skill)

## 3. The 13-stage pipeline

One topic in, thirteen stage files out. Every run ends with **"ship it, or change it?"** and exits.

| Stage | Name | Worker + skill/tool | Output |
|---|---|---|---|
| 0a | Niche finder | yt-niche niche_score.py | `00-niche.md` — ranked niches + picked niche |
| 0b | Plan | yt-plan (+ last run's next-brief.json when present) | `00-plan.md` — weekly plan |
| 1 | Research | TopicResearcher + yt-viral swipe.py | `01-research.md` |
| 2a | Concept score | concept_score.py | `02-concept-score.md` — ranked concepts + picked concept |
| 2b | Script | ScriptWriter + hookscore.py | `02-script.md` + hook score |
| 3 | Visual + Package | VisualProducer + title.py | `03-visual-package.md` + title score |
| 4 | Video | Reel Factory build (see §4) | `04-video.md` + `video.mp4` |
| 5 | Edit | deadair.py + chapters.py + yt-shorts | `05-edit.md` (needs `--transcript`) |
| 6 | Caption + SEO | CaptionWriter + yt-seo | `06-caption-seo.md` |
| 7 | Publish prep | PublishPrep ONLY | `07-publish-prep.md` — checklist, never publishes |
| 8 | Report | PerformanceTracker + retention.py | `08-report.md` (needs `--retention`) |
| 9 | Upload | upload_youtube.py (DEFAULT OFF) | `09-upload.md` — uploaded URL, or exact missing setup |
| 10 | Next plan (loop) | loop_next.py | `10-next-plan.md` + `next-brief.json` for the next run |

## 4. The Video stage (stage 4)

Builds a real mp4: 3 scenes (worker working → phone missed → Talvenor answers/books), TTS voiceover, burned-in line-level captions, exact-logo end card (3s). Short video: 9:16 1080×1920. Long video: 16:9 1920×1080.

### Video providers — pluggable, the user brings their own

| Provider | Needs | Cost | Status |
|---|---|---|---|
| `footage` | `--footage` file/folder | $0 | Works — preferred when given |
| `stills` | Nothing | $0 | Works, free — default |
| `local` | User's CUDA GPU + WanGP / FramePack | $0 after hardware | Code ready, NOT VERIFIED here (no GPU on the build machine) |
| `api` | User's paid key + billing | Pay-per-request | Code ready, NOT VERIFIED with a real call |

- Selection: `--video-provider {footage|stills|local|api|auto}` or `VIDEO_PROVIDER` env var or `video_providers.yaml`. Precedence: flag > env > yaml > stills.
- `local` requirements (verified from official READMEs, 2026-11-07): WanGP — "8 GB of VRAM is enough to get started", select models from 4 GB, 14B best at 12 GB+; FramePack — minimum 6 GB VRAM. FramePack headless CLI invocation UNVERIFIED (ships as a Gradio app).
- `api` example: Muapi (pay-per-call; Sora 2 standard $0.80, Pro $2.40 — docs say check the live Playground before shipping). Generic adapter accepts any provider with a submit → poll → download shape. Runway/Kling/Luma/Veo direct APIs NOT verified — left out, not guessed.
- Keys live ONLY in environment variables (`VIDEO_API_KEY`, `VIDEO_API_URL`, `VIDEO_MODEL`, `LOCAL_VIDEO_CMD`) — never in files, never committed.
- Honest failure: a missing binary/GPU/key stops the stage with the exact missing item in `04-video.md` and builds no video. No silent fallback unless the user sets one in config.
- Default `stills` path: Pollinations.ai image generation (free, no key) → stills → Ken Burns motion. That is **AI stills + motion, NOT true AI video motion and NOT real footage** — labelled as such everywhere.

## 5. How to run it

```bash
python3 -m pytest tests/ -q            # tests (39 passed, 2026-11-10)
python3 scripts/creator_os_run.py --topic "AI receptionist for plumbers" --format "short video"
python3 scripts/creator_os_run.py --topic "..." --format "short video" --footage clips.mp4
python3 scripts/creator_os_run.py --topic "..." --format "short video" --video-provider local
python3 scripts/creator_os_run.py --topic "..." --format "short video" --video-provider api
python3 scripts/creator_os_run.py --find-niche --format "short video"   # no topic: finder picks one
python3 scripts/creator_os_run.py --topic "..." --auto-upload --upload-dry-run  # what WOULD upload
```

Output: `out/<slug>-<date>/` — 13 stage files + `next-brief.json` (+ `video.mp4` when built).

## 6. Gates and hard rules

- `ok` = plan/asset approval. `post it` = publish. `upload it` = video upload. Nothing publishes, sends, uploads, schedules, or spends without the owner's exact word.
- **Upload is off by default and needs two switches** (`--auto-upload` + `YOUTUBE_UPLOAD_ENABLED=1`) plus the owner's own YouTube OAuth credentials (env/file only, never in the repo). `--upload-dry-run` never touches the network.
- Mock mode is the DEFAULT for the writing workers (offline, deterministic, $0). Live writing needs the brain (see §8).
- No invented clients, testimonials, statistics, prices, or guarantees. No dental/medical targeting.
- Brand facts used: "You run the jobs. We run the phone." Booking link https://calendar.app.google/WLoxBfnLGTdjK3LB8. Demo phone +17738970113 (Sophia). Logo is pasted flat from the exact file, never redrawn.

## 7. What it CAN and CANNOT do (honest)

CAN: find a niche for a fresher (scored 1-10) or work from a given niche; plan, research structure, score video concepts 1-10 and feed the picked one into the script; script drafts, hook/title scoring with real numbers, edit decision lists, chapters, retention analysis, caption/SEO drafts, publish checklists, and real mp4 assembly from footage or generated stills; upload to the owner's YouTube channel when the owner enables it twice with their own credentials (privacy defaults to private); read the last video's numbers and write the next video's brief, which the next run's Plan stage reads automatically.

CANNOT (today): write with a live model (mock only — see §8); generate true AI video motion (region-blocked here, no GPU on the build machine, no video endpoint on the Meta $150 credit); publish anything except the owner's own enabled YouTube upload; do word-level karaoke captions (helper absent on this machine); guarantee TTS voice on every run (TTS service times out sometimes — silent fallback with an honest note; re-run when responsive); make a real YouTube upload without the owner's OAuth credentials (never verified end to end — tested dry-run only).

Verified evidence: pytest 42/42 pass (2026-11-10); mock end-to-end run writes all 13 stage files + next-brief.json, with and without a topic (niche finder path); no-footage end-to-end video built real (18.0s, 1080×1920, H.264, decode OK); frame-checked stills (scene 2 phone still verified by eye); local-provider run fails honestly (no CUDA GPU); bad provider/flag rejected with clear errors; upload dry-run prints the exact plan with no network; loop with a real retention CSV produces hook-leak/cliff adjustments and a next-brief.json the next run reads.

## 8. What is next (not yet built)

DONE 2026-11-10 (pushed in `4abfa906`): **niche finder** (yt-niche + tools/niche_score.py), **viral concept score** (tools/concept_score.py, weights adapted from the viral-clips skill), **auto-upload** (scripts/upload_youtube.py, default off, dry-run tested only — no real upload made or verified), **closed loop** (scripts/loop_next.py + next-brief.json auto-read by Plan).

Still to do:

1. **Live brain (LLM):** wire `LiveLLMProvider` (hook exists in `src/workers/base.py`, key from env only) to Muse Spark — the same live provider already proven in CEO-OS. Then workers write for real instead of mock. Add a `--live` flag; mock stays the default.
2. **VOICE.md:** still a DRAFT — the owner must correct it before the first real script ships, or the writing won't sound like them.
3. **True video:** needs the user's own GPU (local path) or paid key (api path) — code is ready, real runs are the user's.
4. **Artifact page:** the `creator-os-combined` art page still shows 8 stages — update when asked (pipeline is 13 now).
5. **Real upload verification:** first real upload with the owner's credentials, on their word, to confirm the resumable-upload path end to end.

## 9. Agent vs skill — how Creator Studio itself is built (appendix)

- **Agent** = a worker that decides and acts: it sees a task, thinks, uses tools, checks the result, and repeats until done. The 6 Creator Studio workers are small agents; Elora and Sophia are full agents.
- **Skill** = a recipe/playbook: the written knowledge of HOW to do one job well (steps, rules, which tools, what good looks like). It does nothing by itself. The 12 yt-* SKILL.md files are skills.
- **Tool** = one capability that does one thing: hookscore.py scores, title.py lints, FFmpeg cuts. A tool does not decide.
- How they fit: the agent reads the skill, then runs the tools step by step. A skill without an agent is a dead manual. An agent without skills improvises and makes beginner mistakes. A tool + a skill, without a decision loop, is automation (a fixed script) — not an agent. An agent needs a goal, perception, decisions, actions, and memory.
- Which is "best" to build? If an agent already exists (Elora, Claude, Muse), **build skills** — cheapest, fastest, and one skill works across agents. Build a whole new agent only when you need a new autonomous worker with its own loop, memory, and identity (a 24/7 worker, a voice receptionist). Creator Studio uses both: workers (agents) + skills + tools, orchestrated by a fixed pipeline (automation) with agent-like workers inside.

## 10. Files and links

- GitHub (PRIVATE): https://github.com/msredc5-bit/Creator-Studio
- Local: `~/workspace/creator-os-combined/` (README.md, video_providers.yaml, scripts/, src/, tests/, tools/, youtube-skills/)
- Visual art: artifact `creator-os-combined` (stale — 8 stages; pipeline is 13 now; update on request)
- Upstream YouTube pack: https://github.com/Jakeschincariol/youtube-agent-skill (MIT)
- Boss's adapted YouTube repo: https://github.com/msredc5-bit/youtube-agent-multi (PRIVATE)
