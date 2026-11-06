#!/usr/bin/env python3
"""Reel Factory video stage for Creator OS — footage OR generated stills.

Local tools only: FFmpeg + PIL + the `tts` binary, plus
scripts/gen_visuals.py (the single network-calling module in this
repo: free Pollinations image generation, no API key, $0). This
module itself makes no network calls. $0 spend. Nothing publishes,
sends, uploads, or schedules.

Two visual sources, in order of preference:
  1. Real footage (--footage) — used whenever supplied, never
     replaced by generated stills.
  2. AI-generated stills (default when no footage is given, unless
     --no-gen-visuals): one Pollinations still per scene, given slow
     Ken Burns motion (FFmpeg zoompan). That is AI stills + motion —
     NOT true AI video motion and NOT real footage — and it is
     labelled exactly that way in the stage file.

What it builds (video formats only): the chosen visuals (scaled/
cropped to 9:16 1080x1920 for short video, 16:9 1920x1080 for long
video, 30fps) + TTS voiceover of the templated voiceover lines +
burned-in line captions + the exact-logo end card (3s) ->
<out-dir>/video.mp4 (+faststart, H.264 + AAC).

Without footage AND without generation (or when generation fails for
all 3 scenes) it builds nothing and writes the production plan plus
the exact missing inputs instead. It never claims a video it did not
build. There is no true AI text-to-video generation here
(region-blocked). Captions are line-level, burned from the known
voiceover text (not word-level karaoke — the faster-whisper caption
helper is not present on this machine).
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

from scripts import gen_visuals

ROOT = Path(__file__).resolve().parent.parent
LOGO_LOCKUP = Path.home() / "workspace" / "talvenor-brand" / "logos" / "talvenor-logo.png"
TTS_BIN = "/opt/hatch/bin/tts"
DEFAULT_VOICE = "avocado_v2:MAI_01"  # Sophia / Aria — Talvenor front desk
FONT_BOLD = "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf"
FONT_REG = "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf"
BRAND_LINE = "You run the jobs. We run the phone."
CTA_LINE = "Book a call with Talvenor. Link in bio."
ENDCARD_SECS = 3.0
VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v"}

# Templated voiceover lines (rewrite before shipping — same rule as the
# templated hook in the script stage). No invented stats or clients.
VO_LINES = [
    "Every missed call is a lost job.",
    "Talvenor answers every call, day and night, and books the job.",
    "Book a call with Talvenor. Link in bio.",
]


# ---------------------------------------------------------------------------
# small helpers
# ---------------------------------------------------------------------------
def _run(cmd: list[str], timeout: int = 180) -> tuple[bool, str]:
    """Run a local command; returns (ok, stderr-tail-or-output)."""
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True,
                              timeout=timeout)
    except subprocess.TimeoutExpired:
        return False, f"timed out after {timeout}s: {cmd[0]}"
    except Exception as exc:  # noqa: BLE001 - record, don't crash
        return False, f"could not start {cmd[0]}: {exc}"
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "no output").strip()
        return False, f"{Path(cmd[0]).name} exited {proc.returncode}: {detail[-500:]}"
    return True, (proc.stdout or "").strip()


def probe_duration(path: Path) -> float:
    """Media duration in seconds via ffprobe; 0.0 when unreadable."""
    ok, out = _run(["ffprobe", "-v", "error", "-show_entries",
                    "format=duration", "-of", "json", str(path)], timeout=60)
    if not ok:
        return 0.0
    try:
        return float(json.loads(out)["format"]["duration"])
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        return 0.0


def collect_footage(arg: str) -> list[dict]:
    """Resolve --footage (one file, or a directory of clips).

    Returns a list of {path, duration} in order, skipping files that
    are not video or have no readable duration.
    """
    p = Path(arg).expanduser()
    clips: list[dict] = []
    if p.is_file():
        if p.suffix.lower() in VIDEO_EXTS:
            dur = probe_duration(p)
            if dur > 0:
                clips.append({"path": p, "duration": dur})
        return clips
    if p.is_dir():
        for f in sorted(p.iterdir()):
            if f.is_file() and f.suffix.lower() in VIDEO_EXTS:
                dur = probe_duration(f)
                if dur > 0:
                    clips.append({"path": f, "duration": dur})
    return clips


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


def _footage_cut(clips: list[dict], used: float, width: int,
                 height: int, work: Path) -> tuple[Path | None, str]:
    """Cut the footage clips into one continuous file.

    Returns (path|None, detail)."""
    take: list[tuple[dict, float]] = []
    remaining = used
    for clip in clips:
        if remaining <= 0:
            break
        take.append((clip, min(clip["duration"], remaining)))
        remaining -= take[-1][1]
    filter_parts = []
    for i, (clip, t) in enumerate(take):
        filter_parts.append(
            f"[{i}:v]trim=0:{t:.3f},setpts=PTS-STARTPTS,"
            f"scale={width}:{height}:force_original_aspect_ratio=increase,"
            f"crop={width}:{height},fps=30,format=yuv420p[v{i}]")
    filter_parts.append("".join(f"[v{i}]" for i in range(len(take))) +
                        f"concat=n={len(take)}:v=1:a=0[vout]")
    cut_path = work / "footage_cut.mp4"
    ok, detail = _run(["ffmpeg", "-y", *sum([["-i", str(c["path"])]
                                             for c, _ in take], []),
                       "-filter_complex", ";".join(filter_parts),
                       "-map", "[vout]", "-c:v", "libx264", "-crf", "20",
                       "-preset", "veryfast", "-an", str(cut_path)],
                      timeout=600)
    if not ok or not cut_path.exists():
        return None, detail
    return cut_path, "ok"


# One Ken Burns move per scene, so the three scenes do not all drift
# the same way. {frames} is the segment length in frames (150 = 5s).
ZOOM_MOVES = [
    # zoom in, centred
    "zoompan=z='min(1+0.0009*on,1.12)':x='iw/2-(iw/zoom/2)'"
    ":y='ih/2-(ih/zoom/2)'",
    # zoom out, centred
    "zoompan=z='max(1.12-0.0009*on,1.0)':x='iw/2-(iw/zoom/2)'"
    ":y='ih/2-(ih/zoom/2)'",
    # slow pan right at a fixed zoom
    "zoompan=z='1.1':x='(iw-iw/zoom)*on/{frames}':y='(ih-ih/zoom)/2'",
]


def _motion_segment(still: Path | None, width: int, height: int,
                    scene_dur: float, move: str,
                    out_path: Path) -> tuple[bool, str]:
    """One scene-length segment from a still (Ken Burns) or a slate.

    A failed scene gets a plain dark slate — recorded honestly in the
    scene record, never a fake image."""
    frames = int(round(scene_dur * 30))
    if still is not None and still.exists():
        vf = (f"scale={width}:{height}:force_original_aspect_ratio=increase,"
              f"crop={width}:{height},"
              f"{move.format(frames=frames)}:d={frames}:s={width}x{height}"
              ":fps=30,format=yuv420p")
        ok, detail = _run(["ffmpeg", "-y", "-i", str(still),
                           "-vf", vf, "-frames:v", str(frames),
                           "-an", "-c:v", "libx264", "-crf", "20",
                           "-preset", "veryfast", str(out_path)],
                          timeout=300)
    else:
        ok, detail = _run(["ffmpeg", "-y", "-f", "lavfi", "-i",
                           f"color=c=0x0b1d33:s={width}x{height}:r=30"
                           f":d={scene_dur:.2f}",
                           "-vf", "format=yuv420p", "-frames:v",
                           str(frames), "-an", "-c:v", "libx264",
                           "-crf", "20", "-preset", "veryfast",
                           str(out_path)], timeout=120)
    if not ok or not out_path.exists():
        return False, detail
    return True, "ok"


def _motion_cut(stills: list[dict], width: int, height: int,
                scene_dur: float, work: Path) -> tuple[Path | None, str]:
    """Motion cut from generated stills. Returns (path|None, detail)."""
    segments: list[Path] = []
    for i, rec in enumerate(stills):
        seg = work / f"motion_scene{i}.mp4"
        still = Path(rec["path"]) if rec["ok"] and rec.get("path") else None
        ok, detail = _motion_segment(
            still, width, height, scene_dur,
            ZOOM_MOVES[i % len(ZOOM_MOVES)], seg)
        if not ok:
            return None, f"scene {i + 1} motion render failed ({detail})"
        segments.append(seg)
    cut_path = work / "motion_cut.mp4"
    concat_list = work / "motion_concat.txt"
    concat_list.write_text(
        "".join(f"file '{p.resolve()}'\n" for p in segments),
        encoding="utf-8")
    ok, detail = _run(["ffmpeg", "-y", "-f", "concat", "-safe", "0",
                       "-i", str(concat_list), "-c:v", "libx264",
                       "-crf", "20", "-preset", "veryfast", "-an",
                       str(cut_path)], timeout=300)
    if not ok or not cut_path.exists():
        return None, detail
    return cut_path, "ok"


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

    # --- visual source: real footage first, generated stills second ---
    scene_count = 3
    scene_sources: list[str] = []
    cut_path: Path | None = None
    if getattr(args, "footage", ""):
        clips = collect_footage(args.footage)
        if not clips:
            result["reason"] = (f"no usable video files found at "
                                f"{args.footage} — no video was built")
            result["missing"] = [f"a video file (or a folder of video files) at {args.footage}"]
            result["plan"] = _plan(args)
            return result
        result["source"] = "real footage"
        total = sum(c["duration"] for c in clips)
        used = min(total, cap)
        if total < cap:
            result["fallbacks"].append(
                f"footage totalled {total:.1f}s, under the {cap:.0f}s target — "
                f"the video uses all {used:.1f}s of it")
        scene_dur = used / scene_count
        scene_sources = ["real footage"] * scene_count
        cut_path, detail = _footage_cut(clips, used, width, height, work)
        if cut_path is None:
            result["reason"] = f"footage cut failed ({detail}) — no video was built"
            result["plan"] = _plan(args)
            return result
    elif getattr(args, "gen_visuals", True):
        # No footage: generate AI stills. This is the default — topic
        # in, video out, with no footage input.
        result["gen"]["attempted"] = True
        stills = gen_visuals.generate_stills(work / "stills", width, height)
        result["gen"]["per_scene"] = stills
        if not any(s["ok"] for s in stills):
            result["reason"] = (
                "AI still generation failed for all 3 scenes "
                "(Pollinations, free) — no video was built")
            result["missing"] = _missing_inputs(gen_failed=True,
                                               stills=stills)
            result["plan"] = _plan(args)
            return result
        result["source"] = "AI-generated stills + motion (Pollinations, free)"
        result["fallbacks"].append(
            "visuals are AI-generated stills with slow Ken Burns motion "
            "(Pollinations, free) — not real footage and not true AI "
            "video motion")
        used = 15.0  # 3 stills x 5s each
        scene_dur = used / scene_count
        scene_sources = [
            (f"generated still scene{s['scene']}.jpg + Ken Burns motion"
             if s["ok"] else
             f"fallback slate — still generation failed ({s['note']})")
            for s in stills
        ]
        cut_path, detail = _motion_cut(stills, width, height, scene_dur,
                                       work)
        if cut_path is None:
            result["reason"] = f"motion cut failed ({detail}) — no video was built"
            result["plan"] = _plan(args)
            return result
    else:
        result["reason"] = "no footage supplied — no video was built"
        result["missing"] = _missing_inputs()
        result["plan"] = _plan(args)
        return result

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
    # cut_path is already built (footage cut or motion cut from stills);
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
