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
video, 30fps) + TTS voiceover of the templated voiceover lines +
burned-in line captions + the exact-logo end card (3s) ->
<out-dir>/video.mp4 (+faststart, H.264 + AAC).

Without a usable visual source it builds nothing and writes the
production plan plus the exact missing inputs instead. It never
claims a video it did not build. Captions are line-level, burned
from the known voiceover text (not word-level karaoke — the
faster-whisper caption helper is not present on this machine).
"""

from __future__ import annotations

import shutil
from pathlib import Path

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


def derive_vo_lines() -> list[str]:
    """The templated voiceover lines for this video stage."""
    return list(VO_LINES)


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


def make_endcard(path: Path, width: int, height: int) -> tuple[bool, str]:
    """Build the end-card still with PIL.

    Solid black background with the exact logo lockup pasted flat
    (the lockup file itself has a black box, so it blends — never
    alpha-keyed, never redrawn). Brand line + CTA in white below.
    Returns (logo_used, note).
    """
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        return False, "PIL not available — end card could not be drawn"
    logo_used = False
    bg = (0, 0, 0)
    if LOGO_LOCKUP.exists():
        try:
            logo_probe = Image.open(LOGO_LOCKUP).convert("RGB")
            bg = logo_probe.getpixel((0, 0))
        except Exception:
            bg = (0, 0, 0)
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

    if LOGO_LOCKUP.exists():
        try:
            logo = Image.open(LOGO_LOCKUP).convert("RGB")
            target_w = int(width * 0.72)
            target_h = int(logo.height * target_w / logo.width)
            logo = logo.resize((target_w, target_h), Image.LANCZOS)
            img.paste(logo, ((width - target_w) // 2,
                             int(height * 0.30) - target_h // 2))
            logo_used = True
        except Exception as exc:  # noqa: BLE001 - record, don't crash
            return False, f"logo file could not be read ({exc}) — text-only end card"
    else:
        return False, "logo file missing — text-only end card"
    y = int(height * 0.52)
    for line in [BRAND_LINE, CTA_LINE]:
        start = max(28, width // 15) if line == BRAND_LINE else max(22, width // 24)
        font = fit_font(FONT_BOLD if line == BRAND_LINE else FONT_REG,
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
    return logo_used, "exact logo lockup pasted flat on its own background colour"


def tts_line(text: str, voice: str, out_path: Path) -> tuple[bool, str]:
    """Synthesise one voiceover line with the local tts binary."""
    if not Path(TTS_BIN).exists():
        return False, "tts binary not found at /opt/hatch/bin/tts"
    ok, detail = _run([TTS_BIN, "speak", "--text-stdin", "--voice", voice,
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
    result: dict = {
        "built": False, "reason": "", "video_path": None, "duration": 0.0,
        "size_bytes": 0, "width": 0, "height": 0, "fps": 30,
        "scenes": [], "vo": [], "endcard": {}, "fallbacks": [],
        "missing": [], "plan": _plan(args), "audio": "",
        "source": "none",
        "gen": {"attempted": False, "per_scene": []},
        "provider": "none",
        "provider_scenes": [],
    }
    if getattr(args, "no_video", False):
        result["reason"] = "skipped — --no-video was passed"
        result["plan"] = _plan(args)
        return result
    if "video" not in args.format:
        result["reason"] = (f"format is '{args.format}' — a video stage "
                            "applies to video formats only; no video was "
                            "built for this format")
        result["plan"] = _plan(args)
        return result
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        result["reason"] = "FFmpeg not available on this machine — no video was built"
        result["missing"] = ["FFmpeg/ffprobe on the machine running the pipeline"]
        result["plan"] = _plan(args)
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
        result["plan"] = _plan(args)
        return result
    # --no-gen-visuals disables the stills provider (the $0 default);
    # it does not touch footage, local, or api.
    provider_name = video_providers.resolve_provider(args, cfg)
    if provider_name == "stills" and not getattr(args, "gen_visuals", True):
        result["reason"] = "no footage supplied — no video was built"
        result["missing"] = _missing_inputs()
        result["plan"] = _plan(args)
        return result
    scene_count = 3
    ctx = {
        "args": args, "work": work, "width": width, "height": height,
        "scene_count": scene_count, "cap": cap,
        "scenes": video_providers.scene_prompts(),
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
        result["plan"] = _plan(args)
        return result
    cut_path = vis["cut_path"]
    used = vis["used"]
    scene_dur = vis["scene_dur"]
    scene_sources = vis["scene_sources"]

    vo_lines = derive_vo_lines()
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
                c0 = vo_start + span * k / len(chunks)
                c1 = vo_start + span * (k + 1) / len(chunks)
                filters.append(
                    f"drawtext=fontfile={FONT_BOLD}:"
                    f"text='{drawtext_escape(chunk)}':"
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
            result["plan"] = _plan(args)
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
    endcard_png = work / "endcard.png"
    logo_used, end_note = make_endcard(endcard_png, width, height)
    end_seg = work / "endcard.mp4"
    ok, detail = _run(["ffmpeg", "-y", "-loop", "1", "-i", str(endcard_png),
                       "-vf", "fps=30,format=yuv420p", "-t",
                       f"{ENDCARD_SECS}", "-c:v", "libx264",
                       "-crf", "20", "-preset", "veryfast", "-an",
                       str(end_seg)], timeout=120)
    if not ok or not end_seg.exists():
        result["reason"] = f"end card render failed ({detail}) — no video was built"
        result["plan"] = _plan(args)
        return result
    result["endcard"] = {"duration": ENDCARD_SECS, "logo_used": logo_used,
                         "note": end_note, "headline": BRAND_LINE,
                         "cta": CTA_LINE,
                         "logo_file": str(LOGO_LOCKUP)}

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
        result["plan"] = _plan(args)
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
        result["plan"] = _plan(args)
        return result

    # --- verify ---------------------------------------------------------
    dur = probe_duration(video_path)
    ok, detail = _run(["ffmpeg", "-v", "error", "-i", str(video_path),
                       "-f", "null", "-"], timeout=300)
    if not ok:
        result["reason"] = (f"built file failed the decode check ({detail}) "
                            "— it is not delivered as a video")
        result["plan"] = _plan(args)
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


def _plan(args) -> dict:
    """The production plan, written whether or not a video was built."""
    return {
        "format": args.format,
        "scenes": [
            {"scene": 1, "seconds": "0-5", "shows": "a real worker working",
             "vo_line": VO_LINES[0]},
            {"scene": 2, "seconds": "5-10", "shows": "a phone ringing and missed",
             "vo_line": VO_LINES[1]},
            {"scene": 3, "seconds": "10-15", "shows": "Talvenor answering and booking",
             "vo_line": VO_LINES[2]},
        ],
        "captions": "line-level, burned in from the voiceover text verbatim",
        "endcard": {"duration_s": ENDCARD_SECS, "logo": str(LOGO_LOCKUP),
                    "headline": BRAND_LINE, "cta": CTA_LINE},
        "voice": getattr(args, "voice", DEFAULT_VOICE),
    }


def _missing_inputs(gen_failed: bool = False,
                    stills: list | None = None) -> list[str]:
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

