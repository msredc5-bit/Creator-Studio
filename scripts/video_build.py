#!/usr/bin/env python3
"""Reel Factory video stage for Creator OS — pluggable providers.

Local tools only: FFmpeg + PIL + the `tts` binary, plus the visual
source chosen by the video-provider layer (scripts/video_providers.py).
$0 spend by default. Nothing publishes, sends, uploads, or
schedules.

Visual sources, in order of preference:
  1. Real footage (--footage) — used whenever supplied, never
     replaced by generated visuals.
  2. The configured provider (--video-provider, VIDEO_PROVIDER,
     video_providers.yaml, else the $0 default): AI-generated stills
     (Pollinations, free) + slow Ken Burns motion, OR true AI video
     motion from a local model (WanGP/FramePack/custom command), OR
     paid cloud video (Muapi Sora/Runway). Whoever has the hardware
     or the paid key uses it; whoever doesn't gets a clear
     missing-input list instead of a fake video. A provider is never
     silently swapped unless a fallback is set in the config.

What it builds (video formats only): the chosen visuals (scaled/
cropped to 9:16 1080x1920 for short video, 16:9 1920x1080 for long
video, 30fps) + TTS voiceover of the voiceover lines — the agent's
real script lines when --script (or vo-lines.txt in the out dir)
is given, else the templated lines — + burned-in line captions +
the end card (3s, exact logo for Talvenor runs, text-only
otherwise) -> <out-dir>/video.mp4 (+faststart, H.264 + AAC).

Without a usable visual source it builds nothing and writes the
production plan plus the exact missing inputs instead. It never
claims a video it did not build. Captions are line-level, burned
from the known voiceover text (not word-level karaoke — the
faster-whisper caption helper is not present on this machine).
"""

from __future__ import annotations

import shutil
from pathlib import Path

from scripts import gen_visuals
from scripts import video_providers
from scripts.video_providers import _run, probe_duration

ROOT = Path(__file__).resolve().parent.parent
LOGO_LOCKUP = Path.home() / "workspace" / "talvenor-brand" / "logos" / "talvenor-logo.png"
TTS_BIN = "/opt/hatch/bin/tts"
DEFAULT_VOICE = "avocado_v2:MAI_01"  # Sophia / Aria — Talvenor front desk
FONT_BOLD = "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf"
FONT_REG = "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf"
BRAND_LINE = "You run the jobs. We run the phone."
CTA_LINE = "Book a call with Talvenor. Link in bio."
ENDCARD_SECS = 3.0

# Templated voiceover lines (rewrite before shipping — same rule as the
# templated hook in the script stage). No invented stats or clients.
VO_LINES = [
    "Every missed call is a lost job.",
    "Talvenor answers every call, day and night, and books the job.",
    "Book a call with Talvenor. Link in bio.",
]


def _short_topic(topic: str) -> str:
    """The topic, shortened to a line that fits a caption/end card."""
    t = " ".join((topic or "").split())
    if not t:
        return "this tool"
    if len(t) <= 60:
        return t
    cut = t[:60].rsplit(" ", 1)[0]
    return cut or t[:60]


def _is_talvenor(args) -> bool:
    """True only when this run is a Talvenor run (see gen_visuals)."""
    return gen_visuals.is_talvenor(getattr(args, "topic", ""),
                                   getattr(args, "brand", "auto"))


def read_script_lines(path: Path) -> tuple[list[str], str | None]:
    """Read one voiceover line per non-empty line of a script file.

    Returns (lines, error). Error is a short human-readable reason
    when the file cannot be read or holds no lines at all.
    """
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError as exc:
        return [], f"script file could not be read ({exc})"
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if not lines:
        return [], "script file has no voiceover lines"
    return lines, None


def resolve_vo_lines(args, out_dir: Path) -> dict:
    """Pick the voiceover lines for this run.

    Returns {"lines", "source", "error", "note"}.
    - `--script <file>` (explicit): those lines, first 3 used for
      the 3 scenes. A missing/unreadable file is an ERROR — the
      caller must build no video and record it, never silently
      fall back to templates when the owner explicitly passed
      a script.
    - `<out_dir>/vo-lines.txt` (the agent's pass-2 file, picked up
      automatically): those lines. An unreadable/empty one is the
      agent's leftover, not the owner's input — templates are used
      instead and the note says so.
    - Neither: the templated lines (brand-aware derive_vo_lines).
    """
    script = getattr(args, "script", "") or ""
    if script:
        lines, err = read_script_lines(Path(script))
        if err is not None:
            return {"lines": [], "source": f"--script {script}",
                    "error": err, "note": ""}
        return {"lines": lines, "source": f"--script {script}",
                "error": None, "note": ""}
    auto = out_dir / "vo-lines.txt"
    if auto.exists():
        lines, err = read_script_lines(auto)
        if err is None:
            return {"lines": lines, "source": "vo-lines.txt",
                    "error": None, "note": ""}
        return {"lines": derive_vo_lines(args), "source": "templated lines",
                "error": None,
                "note": f"vo-lines.txt found but unusable ({err}) — "
                        "templated lines used instead"}
    return {"lines": derive_vo_lines(args), "source": "templated lines",
            "error": None, "note": ""}


def fit_vo_lines(lines: list[str], args) -> tuple[list[str], list[str]]:
    """Fit voiceover lines to exactly 3 scenes.

    Returns (fitted_lines, notes). Extra lines are ignored (noted);
    a short script is padded with templated lines (noted). The
    video always has 3 scenes, one line each.
    """
    notes: list[str] = []
    fitted = list(lines[:3])
    if len(lines) > 3:
        notes.append(f"script had {len(lines)} lines; only the first 3 "
                     "were used (one per scene)")
    if len(fitted) < 3:
        templated = derive_vo_lines(args)
        missing = 3 - len(fitted)
        fitted.extend(templated[len(fitted):3])
        notes.append(f"script had only {len(lines)} voiceover line(s); "
                     f"scene(s) {len(lines) + 1}–3 used templated lines")
    return fitted, notes


def derive_vo_lines(args=None) -> list[str]:
    """The templated voiceover lines for this video stage.

    Talvenor's missed-call lines ONLY for Talvenor runs. Any other
    topic gets neutral lines derived from the topic itself — no
    brand lines, no invented claims. (A real script's lines should
    replace these before shipping, whichever template was used.)
    """
    if args is not None and _is_talvenor(args):
        return list(VO_LINES)
    topic = _short_topic(getattr(args, "topic", "") if args is not None
                         else "")
    return [
        f"Today we test: {topic}.",
        "We run it on screen, step by step — no guessing.",
        "Watch the full test, and the verdict at the end.",
    ]


def wrap_caption(line: str, max_words: int = 6, max_chars: int = 32) -> list[str]:
    """Split one voiceover line into caption chunks that fit the frame.

    Chunks are at most max_words words AND max_chars characters — a
    long 8-word line overflows the 1080px frame at fontsize 64, so
    character length is the binding limit, not word count.
    """
    chunks: list[str] = []
    current = ""
    for word in line.split():
        candidate = f"{current} {word}".strip()
        if current and (len(candidate) > max_chars
                        or len(current.split()) >= max_words):
            chunks.append(current)
            current = word
        else:
            current = candidate
    if current:
        chunks.append(current)
    return chunks or [""]


def drawtext_escape(text: str) -> str:
    """Escape text for an FFmpeg drawtext filter value."""
    return (text.replace("\\", "\\\\").replace("'", "\\'")
            .replace(":", "\\:").replace("%", "\\%"))


def make_endcard(path: Path, width: int, height: int,
                 headline: str = BRAND_LINE, cta: str = CTA_LINE,
                 logo_path: str | None = None) -> tuple[bool, str]:
    """Build the end-card still with PIL.

    With a logo file: the exact logo lockup pasted flat (the lockup
    file itself has a black box, so it blends — never alpha-keyed,
    never redrawn), headline + CTA in white below. Without one
    (logo_path None or missing): a text-only card on a dark
    background, headline + CTA centred — no brand logo is ever
    pasted for a non-brand run. Returns (logo_used, note).
    """
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        return False, "PIL not available — end card could not be drawn"
    logo_used = False
    bg = (7, 9, 13)
    logo = None
    if logo_path:
        lp = Path(logo_path)
        if lp.exists():
            try:
                logo = Image.open(lp).convert("RGB")
                bg = logo.getpixel((0, 0))
            except Exception:
                logo = None
    img = Image.new("RGB", (width, height), bg)
    draw = ImageDraw.Draw(img)

    def fit_font(path: str, text: str, start: int, max_w: int):
        """Largest font size at which the text fits inside max_w."""
        size = start
        while size > 10:
            font = ImageFont.truetype(path, size)
            bb = draw.textbbox((0, 0), text, font=font)
            if bb[2] - bb[0] <= max_w:
                return font
            size -= 2
        return ImageFont.truetype(path, 10)

    if logo is not None:
        try:
            target_w = int(width * 0.72)
            target_h = int(logo.height * target_w / logo.width)
            logo = logo.resize((target_w, target_h), Image.LANCZOS)
            img.paste(logo, ((width - target_w) // 2,
                             int(height * 0.30) - target_h // 2))
            logo_used = True
        except Exception as exc:  # noqa: BLE001 - record, don't crash
            logo = None
            logo_used = False
    y = int(height * 0.52) if logo_used else int(height * 0.42)
    for line in [headline, cta]:
        start = max(28, width // 15) if line == headline else max(22, width // 24)
        font = fit_font(FONT_BOLD if line == headline else FONT_REG,
                        line, start, int(width * 0.92))
        bb = draw.textbbox((0, 0), line, font=font)
        draw.text(((width - (bb[2] - bb[0])) / 2, y), line,
                  font=font, fill=(255, 255, 255))
        y += (bb[3] - bb[1]) + 30
    # Disclosure for hypothetical scenes, per the Reel Factory rules.
    small = ImageFont.truetype(FONT_REG, max(18, width // 40)) \
        if Path(FONT_REG).exists() else ImageFont.load_default()
    disc = "Illustrative example"
    bb = draw.textbbox((0, 0), disc, font=small)
    draw.text(((width - (bb[2] - bb[0])) / 2, height - (bb[3] - bb[1]) - 60),
              disc, font=small, fill=(180, 180, 180))
    img.save(path)
    if logo_used:
        return True, "exact logo lockup pasted flat on its own background colour"
    return False, "text-only end card (no brand logo)"


def tts_line(text: str, voice: str, out_path: Path) -> tuple[bool, str]:
    """Synthesise one voiceover line with the local tts binary.

    Diagnosis (2026-11-10): the binary reads its text from stdin
    (--text-stdin), but the old code never fed it any stdin, so the
    binary waited for input until the 60s timeout on every line —
    every video came out silent. Feeding the text via stdin fixed
    it (~2s per line, verified by hand). Fallback: the --text argv
    form, once. If both fail, the line plays silent and the stage
    file says so — never a fake voice claim.
    """
    if not Path(TTS_BIN).exists():
        return False, "tts binary not found at /opt/hatch/bin/tts"
    ok, detail = _run([TTS_BIN, "speak", "--text-stdin", "--voice", voice,
                       "--output", str(out_path)], timeout=60,
                      input_text=text)
    if not ok:
        ok, detail = _run([TTS_BIN, "speak", "--text", text,
                           "--voice", voice,
                           "--output", str(out_path)], timeout=60)
    if not ok:
        return False, detail
    if not out_path.exists() or out_path.stat().st_size == 0:
        return False, "tts wrote no audio file"
    dur = probe_duration(out_path)
    if dur <= 0:
        return False, "tts audio has no readable duration"
    return True, f"{dur:.1f}s"


# ---------------------------------------------------------------------------
# the build
# ---------------------------------------------------------------------------
def build_video(args, out_dir: Path, work: Path) -> dict:
    """Build the video stage. Returns a result dict for the stage file.

    Always returns a dict (never raises): every failure mode is recorded
    honestly in it, and the runner writes it into 04-video.md.
    """
    # A failed build must never leave a previous run's video behind
    # masquerading as this run's result.
    stale = out_dir / "video.mp4"
    if stale.exists():
        stale.unlink()
    # --- voiceover lines: the agent's real script wins over templates.
    # A missing/unreadable --script fails honestly here, before any
    # building — never a silent fall back to templates.
    vo = resolve_vo_lines(args, out_dir)
    plan_lines = vo["lines"] if vo["error"] is None else None
    result: dict = {
        "built": False, "reason": "", "video_path": None, "duration": 0.0,
        "size_bytes": 0, "width": 0, "height": 0, "fps": 30,
        "scenes": [], "vo": [], "endcard": {}, "fallbacks": [],
        "missing": [], "plan": _plan(args, plan_lines), "audio": "",
        "vo_source": vo["source"],
        "source": "none",
        "gen": {"attempted": False, "per_scene": []},
        "provider": "none",
        "provider_scenes": [],
    }
    if vo["note"]:
        result["fallbacks"].append(vo["note"])
    result["fallbacks"].extend(
        result["plan"].get("vo_notes", []))
    if vo["error"] is not None:
        result["reason"] = (f"no video built — voiceover script failed: "
                            f"{vo['error']}")
        return result
    if getattr(args, "no_video", False):
        result["reason"] = "skipped — --no-video was passed"
        result["plan"] = _plan(args, plan_lines)
        return result
    if "video" not in args.format:
        result["reason"] = (f"format is '{args.format}' — a video stage "
                            "applies to video formats only; no video was "
                            "built for this format")
        result["plan"] = _plan(args, plan_lines)
        return result
    if getattr(args, "video_dry_run", False):
        # Dry run: describe what the resolved provider WOULD do and
        # stop. No engine starts, no still is fetched, no key is
        # read, no video is built. Use it to check a GPU machine's
        # setup before a real run.
        cfg, cfg_errors = video_providers.resolve(args)
        if cfg_errors:
            result["reason"] = ("video provider configuration error — "
                                "dry run stopped: " + "; ".join(cfg_errors))
            result["missing"] = cfg_errors
            return result
        is_short = args.format == "short video"
        width, height = (1080, 1920) if is_short else (1920, 1080)
        result["width"], result["height"] = width, height
        work.mkdir(parents=True, exist_ok=True)
        ctx = {
            "args": args, "work": work, "width": width, "height": height,
            "scene_count": 3, "cap": 30.0 if is_short else 90.0,
            "scenes": video_providers.scene_prompts(
                getattr(args, "topic", ""), getattr(args, "brand", "auto")),
            "format": args.format,
        }
        result["provider"] = video_providers.resolve_provider(args, cfg)
        result["dry_run"] = video_providers.describe_plan(args, cfg, ctx)
        result["reason"] = ("dry run — nothing was executed, no video "
                            "was built")
        return result
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        result["reason"] = "FFmpeg not available on this machine — no video was built"
        result["missing"] = ["FFmpeg/ffprobe on the machine running the pipeline"]
        result["plan"] = _plan(args, plan_lines)
        return result

    is_short = args.format == "short video"
    width, height = (1080, 1920) if is_short else (1920, 1080)
    cap = 30.0 if is_short else 90.0
    result["width"], result["height"] = width, height
    work.mkdir(parents=True, exist_ok=True)

    # --- visual source: the resolved video provider ------------------
    cfg, cfg_errors = video_providers.resolve(args)
    if cfg_errors:
        result["reason"] = ("video provider configuration error — no "
                            "video was built: " + "; ".join(cfg_errors))
        result["missing"] = [
            f"a valid video provider setup ({err}) — see "
            "video_providers.yaml and README.md 'Video providers'"
            for err in cfg_errors
        ]
        result["plan"] = _plan(args, plan_lines)
        return result
    # --no-gen-visuals disables the stills provider (the $0 default);
    # it does not touch footage, local, or api.
    provider_name = video_providers.resolve_provider(args, cfg)
    if provider_name == "stills" and not getattr(args, "gen_visuals", True):
        result["reason"] = "no footage supplied — no video was built"
        result["missing"] = _missing_inputs(args=args)
        result["plan"] = _plan(args, plan_lines)
        return result
    scene_count = 3
    ctx = {
        "args": args, "work": work, "width": width, "height": height,
        "scene_count": scene_count, "cap": cap,
        "scenes": video_providers.scene_prompts(
            getattr(args, "topic", ""), getattr(args, "brand", "auto")),
        "format": args.format,
    }
    vis = video_providers.run_provider(args, cfg, ctx)
    result["provider"] = vis.get("provider", provider_name)
    result["provider_scenes"] = vis.get("provider_scenes", [])
    result["gen"] = vis.get("gen", {"attempted": False, "per_scene": []})
    result["source"] = vis.get("source", "none")
    result["fallbacks"].extend(vis.get("fallbacks", []))
    if vis.get("cut_path") is None:
        result["reason"] = vis.get("reason") or "no video was built"
        result["missing"] = vis.get("missing", [])
        result["plan"] = _plan(args, plan_lines)
        return result
    cut_path = vis["cut_path"]
    used = vis["used"]
    scene_dur = vis["scene_dur"]
    scene_sources = vis["scene_sources"]

    # One source of truth: the plan already fitted the lines to 3 scenes.
    vo_lines = [scene["vo_line"] for scene in result["plan"]["scenes"]]
    # --- voiceover ------------------------------------------------------
    vo_audio: list[dict] = []
    for i, line in enumerate(vo_lines):
        vo_path = work / f"vo{i}.mp3"
        ok, note = tts_line(line, args.voice, vo_path)
        dur = probe_duration(vo_path) if ok else 0.0
        vo_audio.append({"line": line, "ok": ok, "note": note,
                         "path": str(vo_path) if ok else None,
                         "duration": dur})
        if not ok:
            result["fallbacks"].append(
                f"voiceover line {i + 1} could not be synthesised ({note}) — "
                "that line plays silent; its caption still shows")
    result["vo"] = vo_audio
    if not any(v["ok"] for v in vo_audio):
        result["fallbacks"].append(
            "no voiceover audio at all — the video is silent; captions "
            "carry the words")

    # --- scene segments with burned-in captions -------------------------
    # cut_path is already built (by the resolved video provider);
    # scenes are sliced from it and captioned below.
    fontsize = 64 if is_short else 56
    cap_y = int(height * 0.62) if is_short else int(height * 0.70)
    scene_files: list[Path] = []
    for j in range(scene_count):
        start = j * scene_dur
        seg = work / f"scene{j}.mp4"
        vo = vo_audio[j] if j < len(vo_audio) else None
        filters = []
        if vo is not None:
            vo_start = 0.3
            vo_end = min(scene_dur, vo_start + vo["duration"]) \
                if vo["ok"] and vo["duration"] > 0 else scene_dur
            chunks = wrap_caption(vo["line"])
            span = max(0.1, vo_end - vo_start)
            for k, chunk in enumerate(chunks):
                # Captions go through textfile, not text='...': a
                # chunk with an apostrophe (Google's, don't) or a
                # colon breaks the filter-graph parser when inlined
                # (ffmpeg: "No such filter: '0.30'"), and a file
                # has no quoting problem at all.
                cap_file = work / f"cap{j}_{k}.txt"
                cap_file.write_text(chunk, encoding="utf-8")
                c0 = vo_start + span * k / len(chunks)
                c1 = vo_start + span * (k + 1) / len(chunks)
                filters.append(
                    f"drawtext=fontfile={FONT_BOLD}:"
                    f"textfile='{drawtext_escape(str(cap_file))}':"
                    f"fontsize={fontsize}:fontcolor=white:borderw=3:"
                    f"bordercolor=black:x=(w-text_w)/2:"
                    f"y={cap_y}:enable='between(t,{c0:.2f},{c1:.2f})'")
        vf = ",".join(filters) if filters else "null"
        ok, detail = _run(["ffmpeg", "-y", "-ss", f"{start:.3f}",
                           "-t", f"{scene_dur:.3f}", "-i", str(cut_path),
                           "-vf", vf, "-an", "-c:v", "libx264", "-crf", "20",
                           "-preset", "veryfast", str(seg)], timeout=300)
        if not ok or not seg.exists():
            result["reason"] = (f"scene {j + 1} render failed ({detail}) — "
                                "no video was built")
            result["plan"] = _plan(args, plan_lines)
            return result
        scene_files.append(seg)
        result["scenes"].append({
            "scene": j + 1, "start": round(start, 2),
            "duration": round(scene_dur, 2),
            "footage": scene_sources[j] if j < len(scene_sources)
                       else "real footage",
            "source": scene_sources[j] if j < len(scene_sources)
                      else "real footage",
            "vo_line": vo["line"] if vo else "",
            "vo_ok": bool(vo and vo["ok"]),
            "captions": wrap_caption(vo["line"]) if vo else [],
        })

    # --- end card -------------------------------------------------------
    # The plan's end card decides: Talvenor runs get the exact logo
    # lockup; any other topic gets a text-only card (no brand logo).
    ec = result["plan"]["endcard"]
    endcard_png = work / "endcard.png"
    logo_used, end_note = make_endcard(
        endcard_png, width, height,
        headline=ec.get("headline", BRAND_LINE),
        cta=ec.get("cta", CTA_LINE),
        logo_path=ec.get("logo") or None)
    end_seg = work / "endcard.mp4"
    ok, detail = _run(["ffmpeg", "-y", "-loop", "1", "-i", str(endcard_png),
                       "-vf", "fps=30,format=yuv420p", "-t",
                       f"{ENDCARD_SECS}", "-c:v", "libx264",
                       "-crf", "20", "-preset", "veryfast", "-an",
                       str(end_seg)], timeout=120)
    if not ok or not end_seg.exists():
        result["reason"] = f"end card render failed ({detail}) — no video was built"
        result["plan"] = _plan(args, plan_lines)
        return result
    result["endcard"] = {"duration": ENDCARD_SECS, "logo_used": logo_used,
                         "note": end_note,
                         "headline": ec.get("headline", BRAND_LINE),
                         "cta": ec.get("cta", CTA_LINE),
                         "logo_file": ec.get("logo", "")}

    # --- concat video, mix voiceover, mux -------------------------------
    concat_list = work / "concat.txt"
    concat_list.write_text(
        "".join(f"file '{p.resolve()}'\n"
                for p in [*scene_files, end_seg]), encoding="utf-8")
    video_only = work / "video_novoice.mp4"
    ok, detail = _run(["ffmpeg", "-y", "-f", "concat", "-safe", "0",
                       "-i", str(concat_list), "-c:v", "libx264",
                       "-crf", "20", "-preset", "veryfast", "-an",
                       str(video_only)], timeout=300)
    if not ok or not video_only.exists():
        result["reason"] = f"video concat failed ({detail}) — no video was built"
        result["plan"] = _plan(args, plan_lines)
        return result

    video_path = out_dir / "video.mp4"
    total_dur = used + ENDCARD_SECS
    audio_inputs: list[str] = []
    filter_parts = []
    ok_js: list[int] = []
    idx = 1
    for j, vo in enumerate(vo_audio):
        if not vo["ok"]:
            continue
        start_ms = int((j * scene_dur + 0.3) * 1000)
        audio_inputs += ["-i", str(vo["path"])]
        filter_parts.append(
            f"[{idx}:a]aresample=44100,aformat=channel_layouts=stereo,"
            f"adelay={start_ms}|{start_ms}[a{j}]")
        ok_js.append(j)
        idx += 1
    if audio_inputs:
        mix = "".join(f"[a{j}]" for j in ok_js)
        filter_parts.append(
            f"{mix}amix=inputs={len(ok_js)}:"
            f"normalize=0,apad=whole_dur={total_dur:.2f}[aout]")
        ok, detail = _run(
            ["ffmpeg", "-y", "-i", str(video_only), *audio_inputs,
             "-filter_complex", ";".join(filter_parts),
             "-map", "0:v", "-map", "[aout]", "-c:v", "copy",
             "-c:a", "aac", "-b:a", "128k", "-t", f"{total_dur:.2f}",
             "-movflags", "+faststart", str(video_path)], timeout=300)
    else:
        ok, detail = _run(
            ["ffmpeg", "-y", "-i", str(video_only), "-an",
             "-c:v", "copy", "-movflags", "+faststart",
             str(video_path)], timeout=300)
    if not ok or not video_path.exists():
        result["reason"] = f"final mux failed ({detail}) — no video was built"
        result["plan"] = _plan(args, plan_lines)
        return result

    # --- verify ---------------------------------------------------------
    dur = probe_duration(video_path)
    ok, detail = _run(["ffmpeg", "-v", "error", "-i", str(video_path),
                       "-f", "null", "-"], timeout=300)
    if not ok:
        result["reason"] = (f"built file failed the decode check ({detail}) "
                            "— it is not delivered as a video")
        result["plan"] = _plan(args, plan_lines)
        return result
    result["built"] = True
    result["video_path"] = str(video_path)
    result["duration"] = round(dur, 2)
    result["size_bytes"] = video_path.stat().st_size
    n_vo = len([v for v in vo_audio if v["ok"]])
    result["audio"] = (f"AAC voiceover ({n_vo} of {len(vo_audio)} lines)"
                       if audio_inputs else
                       "silent — no audio track (all voiceover failed)")
    result["reason"] = (f"built: {video_path.name}, {dur:.1f}s, "
                        f"{width}x{height} 30fps, H.264 + "
                        f"{result['audio']}, faststart")
    return result


def _plan(args, vo_lines: list[str] | None = None) -> dict:
    """The production plan, written whether or not a video was built.

    Brand-aware: Talvenor runs keep the missed-call story, the
    exact logo and the brand lines. Any other topic gets neutral
    topic-derived scenes and a text-only end card — never the
    brand's lines or logo. When `vo_lines` is given (the agent's
    real script, via --script or vo-lines.txt), those lines are
    the scenes' voiceover instead of the templates.
    """
    if vo_lines is not None:
        vo, vo_notes = fit_vo_lines(vo_lines, args)
    elif _is_talvenor(args):
        vo, vo_notes = list(VO_LINES), []
    else:
        vo, vo_notes = derive_vo_lines(args), []
    if _is_talvenor(args):
        scenes = [
            {"scene": 1, "seconds": "0-5", "shows": "a real worker working",
             "vo_line": vo[0]},
            {"scene": 2, "seconds": "5-10", "shows": "a phone ringing and missed",
             "vo_line": vo[1]},
            {"scene": 3, "seconds": "10-15", "shows": "Talvenor answering and booking",
             "vo_line": vo[2]},
        ]
        endcard = {"duration_s": ENDCARD_SECS, "logo": str(LOGO_LOCKUP),
                   "headline": BRAND_LINE, "cta": CTA_LINE}
    else:
        topic = _short_topic(getattr(args, "topic", ""))
        scenes = [
            {"scene": 1, "seconds": "0-5",
             "shows": "Opening: the topic on screen",
             "vo_line": vo[0]},
            {"scene": 2, "seconds": "5-10",
             "shows": "The test running on screen, step by step",
             "vo_line": vo[1]},
            {"scene": 3, "seconds": "10-15",
             "shows": "The verdict on screen",
             "vo_line": vo[2]},
        ]
        endcard = {"duration_s": ENDCARD_SECS, "logo": "",
                   "headline": topic,
                   "cta": "Subscribe for the next test."}
    return {
        "format": args.format,
        "scenes": scenes,
        "captions": "line-level, burned in from the voiceover text verbatim",
        "endcard": endcard,
        "voice": getattr(args, "voice", DEFAULT_VOICE),
        "vo_notes": vo_notes,
    }


def _missing_inputs(gen_failed: bool = False,
                    stills: list | None = None,
                    args=None) -> list[str]:
    if args is not None and not _is_talvenor(args):
        topic = _short_topic(getattr(args, "topic", ""))
        items = [
            "Footage: one video file (or a folder of clips) showing "
            f"the test in order — (1) opening on {topic}, (2) the "
            "test running on screen, (3) the verdict. Re-run with "
            "--footage <path to the file or folder>.",
            "Voiceover: the three templated lines in the plan below "
            "are used unless Boss rewrites them first.",
        ]
    else:
        items = [
            "Footage: one video file (or a folder of clips) showing, in order — "
            "(1) a real worker working, (2) a phone ringing and missed, "
            "(3) Talvenor answering and booking. Real footage only; no stills "
            "with motion. Re-run with --footage <path to the file or folder>.",
            "Voiceover: the three templated lines in the plan below are used "
            "unless Boss rewrites them first.",
        ]
    if gen_failed:
        reasons = "; ".join(
            f"scene {s['scene']}: {s['note']}" for s in (stills or []))
        items.append(
            "AI still generation was attempted (Pollinations, free) and "
            f"failed for all 3 scenes — {reasons}. The free image "
            "service is network-dependent; retry the run, or supply real "
            "footage with --footage <path> instead.")
    else:
        items.append(
            "Or: re-run WITHOUT --no-gen-visuals — the stage then "
            "generates AI stills itself (Pollinations, free) and builds "
            "the video from them with slow motion. Draft quality, not "
            "real footage.")
    return items

