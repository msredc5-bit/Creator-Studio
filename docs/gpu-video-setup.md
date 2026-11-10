# GPU video setup — true AI video motion on your own PC (free)

Creator Studio's `$0` default video is AI stills + slow motion
(Pollinations, free). That is **not** true AI video motion — the
pictures don't really move. For real motion, free, you run an
open video model on your own PC's graphics card (GPU). This guide
is for a Windows PC user doing it with their agent's help.

If you have no GPU, skip this guide: the stills default already
works, and the paid path is `api` (see "Video providers" in
README.md). If anything below disagrees with the project's own
README, the project's README wins — video models change fast.

## Step 0 — Do you have a GPU that can do this?

**Check in 30 seconds:** press `Ctrl + Shift + Esc` (Task
Manager) → Performance tab → GPU. It shows the card name and its
memory (e.g. "RTX 3060, 6 GB"). Or open a terminal and run:

```text
nvidia-smi
```

If that command is not found, or the card is not NVIDIA, the
local path does not work on this PC.

**Minimum memory (verified from the projects' own READMEs,
2026-11-10):**

| Engine | Minimum VRAM | Notes |
|---|---|---|
| **FramePack** | **6 GB** | NVIDIA RTX 30XX / 40XX / 50XX, Windows or Linux, Python 3.10. Models are 30 GB+ on disk. The README says: "the minimal required GPU memory is 6GB. (Yes 6 GB, not a typo. Laptop GPUs are okay.)" |
| **WanGP** (Wan 2.1 1.3B) | **8 GB to get started** | The Wan 2.1 1.3B model's makers list 8.19 GB VRAM. WanGP also runs select smaller/quantized models on 6 GB, and some on as little as 4 GB (per the WanGP README). 14B models need 12 GB+ and are not for small cards. |

Rule of thumb: **6 GB card → FramePack. 8 GB+ card → WanGP or
FramePack.** Below 6 GB, use the stills default or the paid `api`
path instead — a local run will fail honestly and say so.

You also need: **Python 3.10 or 3.11**, **40 GB+ free disk**
(models are big), and a stable connection for the one-time model
download.

## Step 1 — Install the engine (pick ONE)

### Option A — FramePack (easiest, 6 GB cards)

1. Go to the official repo: `github.com/lllyasviel/FramePack`
   (only that repo — the project warns that look-alike sites
   like framepack.co are fake).
2. Download the **one-click Windows package** linked in its
   README, extract it to a short path (e.g.
   `C:\FramePack`), run `update.bat`, then `run.bat`.
   The models download automatically on first run (30 GB+).
3. Open the app once and generate any short clip, so you know
   it works before Creator Studio uses it.

FramePack is a desktop app with no official headless command, so
Creator Studio cannot call it directly. You give it a command
(see Step 3, `custom` engine) — a community batch wrapper such
as FramePack-Batch, or your own small script that takes an image
+ prompt and writes a clip.

### Option B — WanGP (headless batch, 8 GB+ cards)

1. Install Python 3.10/3.11 and a CUDA PyTorch (follow the
   WanGP README's install steps).
2. Clone the repo and install it:

```text
git clone https://github.com/deepbeepmeep/WanGP.git
cd WanGP
```

3. Open the WanGP web UI once, load a model, and generate one
   short clip, so you know it works.
4. In the web UI, build the jobs for your scenes and click
   **Save Queue** — this creates the `.zip` queue file Creator
   Studio will run headlessly. One job per scene (3 jobs).

## Step 2 — Point Creator Studio at it

Edit `video_providers.yaml` at the repo root (no secrets in
this file, ever):

**WanGP:**

```yaml
provider: local
local:
  engine: wangp
  wangp_dir: "C:/WanGP"          # folder containing wgp.py
  queue: "C:/WanGP/my_queue.zip" # the Save Queue file, 1 job/scene
  output_dir: "C:/WanGP/output"  # where WanGP writes finished clips
```

**FramePack / any other local tool (custom command):**

```yaml
provider: local
local:
  engine: custom
  command: 'python3 my-gen.py --prompt "{prompt}" --image "{image}" --seconds {duration} --width {width} --height {height} --out "{output}"'
```

Placeholders the runner fills in per scene: `{prompt}` (the scene
prompt), `{image}` (the input still, for image-to-video tools),
`{duration}` (seconds, 5 or 10), `{width}`, `{height}`,
`{output}` (where the clip must be written). For FramePack set
`engine: framepack` instead of `custom` — same command field;
the only difference is that `framepack` first generates input
stills for it. Or set the same command with the `LOCAL_VIDEO_CMD`
environment variable instead of editing the file.

## Step 3 — Dry-run first (no generation, no cost)

```bash
python3 scripts/creator_os_run.py --topic "AI tools for beginners" --format "short video" \
    --video-provider local --video-dry-run
```

This prints exactly what would happen — the GPU found, the exact
command, and any `MISSING:` setup step — and builds nothing.
Fix every `MISSING:` line, then run for real:

```bash
python3 scripts/creator_os_run.py --topic "AI tools for beginners" --format "short video" \
    --video-provider local
```

## Step 4 — What a real run looks like

- WanGP: the runner executes `python wgp.py --process
  my_queue.zip`, then collects the newest 3 clips from
  `output_dir` and cuts them to scenes. Keep `output_dir`
  clean between runs, or old clips can be picked up.
- FramePack/custom: the runner calls your command once per
  scene (3 calls), each writing one clip.
- The finished `video.mp4` is a local file. Nothing uploads
  without your exact word (`upload it`).

## If it fails

The stage file `04-video.md` says exactly what is missing —
read it first. Common causes:

- **"no CUDA GPU on this machine"** — `nvidia-smi` finds no
  card. The local path cannot run here; use stills or `api`.
- **"WanGP checkout not found"** — `local.wangp_dir` is wrong;
  it must be the folder containing `wgp.py`.
- **"no WanGP queue file"** — create the queue in the WanGP web
  UI (Save Queue) and set `local.queue`.
- **"no command configured"** — `local.command` is empty (the
  FramePack/custom path always needs one).
- **A clip is missing or unreadable** — the engine ran but wrote
  nothing usable; run the printed command by hand once to see
  its error.

## What is NOT proven yet

The local adapter is written and unit-tested with mocks, but no
real GPU generation has been run by this project — this machine
has no GPU. The first real run on a GPU PC is the proof. If it
works there, the run's `04-video.md` will say so; if it does
not, it will say exactly which step stopped it.
