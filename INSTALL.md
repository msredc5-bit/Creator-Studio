# Install Creator Studio

Creator Studio turns one idea — or no idea at all — into a finished
video: it finds a viral niche, scores concepts, writes the script,
builds and edits the video, and plans the next one from the last
one's numbers. 13 stages, one run, $0 by default.

## The one-line way (easiest)

Copy this line, paste it to your own AI agent (Claude, Muse, or any
agent), and it sets everything up for you:

```
Set up Creator Studio for me: clone https://github.com/msredc5-bit/Creator-Studio, run python3 setup.py to install its skills into my agent, then run the pipeline once with --find-niche --format "short video" and show me the plan.
```

That is the whole setup. Your agent reads
`skills/creator-studio/SKILL.md`, installs the skills, runs the
pipeline, and shows you the plan. Nothing publishes or uploads
without your exact word.

## Way B — one command (terminal)

```bash
git clone https://github.com/msredc5-bit/Creator-Studio && cd Creator-Studio && python3 setup.py
```

Then run it:

```bash
python3 scripts/creator_os_run.py --find-niche --format "short video"
```

## Way C — manual (if you want to see each step)

```bash
git clone https://github.com/msredc5-bit/Creator-Studio
cd Creator-Studio
python3 setup.py --check        # dry run: shows what it WOULD do
python3 setup.py                # installs the skills
```

`setup.py` finds your agent's skills folder itself (Muse:
`~/workspace/custom-skills`, Claude Code: `~/.claude/skills`). If it
cannot find one, it tells you to pass it yourself:

```bash
python3 setup.py --target /path/to/your/skills
```

It copies `skills/creator-studio` + all 12 `youtube-skills/*`
skills, never overwrites ones already there (use `--force` to
overwrite), and creates `video_providers.yaml` from the default
only if the file is missing. No network, no keys, no account.

## What you need

- **Python 3.10+** (`python3 --version` to check) and **git**.
  Nothing else to install.
- **Optional, only if you want it:** your own YouTube OAuth
  credentials for auto-upload (stage 9 is off by default — see
  `skills/creator-studio/SKILL.md`, "Upload setup"); your own CUDA
  GPU or paid video key for true AI video motion (otherwise the
  video stage uses free AI stills + motion, $0).

## What it costs

**$0 by default.** Mock writing (offline, labelled `[MOCK DRAFT]`),
free stills video, local scoring tools. You pay only if you choose
to: a paid video API key (e.g. Muapi Sora, from $0.09/request) or
your own GPU's electricity. Uploading to your own YouTube channel
costs nothing.

## First runs

```bash
# No idea yet — the niche finder picks one for you:
python3 scripts/creator_os_run.py --find-niche --format "short video"

# You know the topic:
python3 scripts/creator_os_run.py --topic "AI tools for beginners" --format "short video"

# Long video, with your own footage and files:
python3 scripts/creator_os_run.py --topic "..." --format "long video" \
    --footage clips.mp4 --transcript transcript.srt --retention retention.csv
```

Each run writes 13 stage files into `out/<slug>-<YYYY-MM-DD>/` and
ends with **"ship it, or change it?"** — you decide what ships.

## Troubleshooting

- **`python3: command not found`** — install Python 3.10+ from
  https://www.python.org/downloads/ and re-run.
- **"Python 3.10+ is required"** — your python3 is too old; install
  a newer one (same link) and re-run.
- **"no agent skills directory found"** — you have no Claude Code
  or Muse skills folder yet. Either install Claude Code, or pass a
  folder yourself: `python3 setup.py --target /path/to/skills`.
- **`git clone` asks for a password / 404** — the repo is private.
  Ask the owner for access, or use a checkout they shared with you.
- **"already installed, skipped"** — setup found the skills there
  already. That is fine. Re-run with `--force` to overwrite them.
- **Upload does nothing** — by design. Stage 9 needs `--auto-upload`
  AND `YOUTUBE_UPLOAD_ENABLED=1` AND your own OAuth credentials,
  plus your exact word (`upload it`). Try `--upload-dry-run` first:
  it prints exactly what WOULD upload, with no network.
- **Video has no voice / stills look drafty** — the $0 default is
  AI stills + motion with a free voice; it proves the pipeline end
  to end. Real footage (`--footage`) or your own GPU/paid key make
  it final quality. See README.md, "Video providers".
- **The script does not sound like you** — correct
  `youtube-skills/VOICE.md` from three of your own videos first
  (see `skills/creator-studio/SKILL.md`).

Full detail: `README.md`. The entry skill your agent reads:
`skills/creator-studio/SKILL.md`.
