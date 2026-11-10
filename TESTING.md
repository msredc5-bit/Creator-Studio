# Testing Creator Studio (first-time tester)

You are testing this repo for the first time. Nothing here publishes,
uploads, or spends money. Upload stays OFF unless you turn it on
yourself (see step 5).

## What you need

- A computer (Windows, Mac, or Linux)
- **Python 3.10 or newer** — check with `python3 --version`
- **git** — check with `git --version`
- An AI agent (Claude, Muse, or any agent that can run commands) —
  or just a terminal

## Steps

### 1. Get the code

```bash
git clone https://github.com/msredc5-bit/Creator-Studio
cd Creator-Studio
```

### 2. Install the skills (dry run first, then real)

```bash
python3 setup.py --check   # shows what it WOULD do, changes nothing
python3 setup.py           # installs the skills into your agent
```

If it says "no agent skills directory found", pass a folder
yourself: `python3 setup.py --target /path/to/your/skills`

### 3. Run the tests

```bash
python3 -m pytest tests/ -q
```

Success looks like: `42 passed` (or more, if tests were added).
If any test fails, stop here and report it (see step 6).

### 4. First real run — find a niche, make a plan

```bash
python3 scripts/creator_os_run.py --find-niche --format "short video"
```

Success looks like:

- A new folder appears: `out/<something>-<today's date>/`
- It has **13 stage files** (`00-niche.md` … `10-next-plan.md`)
  plus `next-brief.json`
- The run ends by printing: **"ship it, or change it?"**

Try a second run with your own topic:

```bash
python3 scripts/creator_os_run.py --topic "AI tools for beginners" --format "short video"
```

### 5. What does NOT happen (by design)

- Nothing is uploaded to YouTube. The upload stage is OFF by
  default — it needs `--auto-upload` AND `YOUTUBE_UPLOAD_ENABLED=1`
  AND your own YouTube credentials. Do not turn it on for this test.
- Nothing is published, sent, or charged. The default run costs $0.
- The video stage builds a real `video.mp4` from free AI stills
  (or skips video honestly with `--no-gen-visuals` if you pass it).

## 6. If something fails, report this

Copy-paste all of these to the repo owner:

1. The **exact command** you ran
2. The **exact error** (the last 20 lines of output)
3. Your **Python version**: `python3 --version`
4. Your **operating system** (Windows / Mac / Linux + version)
5. What step you were on (2, 3, or 4 above)

That is enough to fix it. Thank you for testing!
