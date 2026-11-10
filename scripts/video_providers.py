#!/usr/bin/env python3
"""Pluggable video providers for the Creator OS video stage.

One interface, swappable backends. The video stage (stage 4) asks a
provider for visuals; the provider returns a continuous cut file
plus an honest record of what it did. Whoever has the hardware or
the paid key uses it; whoever doesn't gets a clear missing-input
list instead of a fake video.

Providers (see README.md "Video providers" for the full table):
  footage — real footage supplied with --footage. Preferred whenever
            it is given; never replaced by generated visuals.
  stills  — AI-generated stills (Pollinations, free, no key) given
            slow Ken Burns motion. The DEFAULT when nothing else is
            configured. $0. This is AI stills + motion — NOT true AI
            video motion and NOT real footage.
  local   — open-source video models on the USER's own machine
            (WanGP, FramePack, or any command the user configures).
            Needs a CUDA GPU. NOT VERIFIED on this machine (no GPU
            here) — the adapter is written and mock-tested, but no
            real local generation is claimed.
  api     — paid cloud video generation through a generic HTTP
            adapter (Muapi is the documented example: Sora 2 and
            Runway endpoints, pay-per-generation). Key, URL, and
            model come ONLY from environment variables, never from
            files. NOT VERIFIED with a real paid call — tests use a
            local fake server only.

Config: video_providers.yaml at the repo root (documented, NO
secrets in it), plus environment variables VIDEO_PROVIDER,
VIDEO_API_KEY, VIDEO_API_URL, VIDEO_MODEL, LOCAL_VIDEO_CMD.
Precedence: CLI flag > environment > config file > built-in default.
A provider is never silently swapped: if the chosen provider fails
and no fallback is set in the config, the stage records the failure
honestly and builds no video.

Network: this module and scripts/gen_visuals.py are the ONLY
network-calling modules in this repo. The api provider uses urllib
(stdlib) to POST, poll, and download. No keys are ever logged.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

from scripts import gen_visuals

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_PATH = ROOT / "video_providers.yaml"

PROVIDERS = ("footage", "stills", "local", "api")
PROVIDER_CHOICES = PROVIDERS + ("auto",)
LOCAL_ENGINES = ("wangp", "framepack", "custom")

# Verified 2026-11-07 from Muapi's official docs (muapi.ai/sora and
# muapi.ai/docs/pricing): async REST, x-api-key header, submit returns
# {"request_id": ...}, poll GET /api/v1/predictions/{id}/result until
# status is completed, then read the video URL from outputs. Prices
# below are what the docs showed on that date — Muapi's own docs say
# to review the live Playground schema before shipping, because
# prices change.
DEFAULT_API_URL = ("https://api.muapi.ai/api/v1/"
                   "openai-sora-2-text-to-video")
DEFAULT_API_POLL_URL = ("https://api.muapi.ai/api/v1/predictions/"
                        "{request_id}/result")
# The adapter fills prompt, duration, resolution, and aspect_ratio
# per scene before sending — the values here are valid-JSON
# placeholders, not real requests.
DEFAULT_API_BODY_JSON = ('{"prompt": "", '
                         '"aspect_ratio": "16:9", '
                         '"duration": 8, '
                         '"resolution": "1080p"}')
# Verified from the same docs: Sora 2 standard text-to-video
# $0.80/request (720p), Pro $2.40/request (up to 1080p), original
# Sora $0.50/request, Runway text-to-video $0.09/request and
# image-to-video $0.15/request (via Muapi). Pay-per-generation,
# credits never expire. These are documentation figures, not a
# promise — check the live pricing page before spending.
MUAPI_PRICES = {
    "openai-sora-2-text-to-video": "$0.80/request (720p)",
    "openai-sora-2-pro-text-to-video": "$2.40/request (up to 1080p)",
    "openai-sora": "$0.50/request (720p)",
    "runway-text-to-video": "$0.09/request (via Muapi)",
    "runway-image-to-video": "$0.15/request (via Muapi)",
}

# Verified 2026-11-07 from the projects' own READMEs:
# - WanGP (deepbeepmeep/WanGP): "8 GB of VRAM is enough to get
#   started"; "run select models with as little as 4 GB of VRAM";
#   Wan 2.1 T2V 1.3B is the fastest/lowest-VRAM model (6 GB), the
#   14B is best quality (12 GB+). Headless batch mode is documented:
#   create a queue in the web UI, save it, then run
#   `python wgp.py --process my_queue.zip`.
# - FramePack (lllyasviel/FramePack): "the minimal required GPU
#   memory is 6GB. (Yes 6 GB, not a typo. Laptop GPUs are okay.)"
#   Needs an Nvidia RTX 30XX/40XX/50XX GPU with fp16/bf16, Linux or
#   Windows, Python 3.10; models are 30 GB+ from Hugging Face.
#   FramePack ships as a Gradio desktop app (demo_gradio.py) — NO
#   official headless CLI was found in its README, so the framepack
#   engine here takes a user-supplied command and that is labelled
#   UNVERIFIED in the docs.
WANGP_MIN_VRAM_GB = 4   # select models; 8 GB to get started
WANGP_START_VRAM_GB = 8
FRAMEPACK_MIN_VRAM_GB = 6

VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v"}


# ---------------------------------------------------------------------------
# small shared helpers (also used by scripts/video_build.py)
# ---------------------------------------------------------------------------
def _run(cmd: list[str], timeout: int = 180,
         input_text: str | None = None) -> tuple[bool, str]:
    """Run a local command; returns (ok, stderr-tail-or-output).

    `input_text`, when given, is fed to the command's stdin (and
    stdin is then closed). This matters: a command that reads its
    input from stdin waits forever when nothing is fed — see
    tts_line in video_build.py.
    """
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True,
                              timeout=timeout, input=input_text)
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


def _concat_clips(clips: list[Path], work: Path,
                  name: str) -> tuple[Path | None, str]:
    """Concatenate already-encoded clips into one file."""
    out_path = work / name
    concat_list = work / f"{name}.txt"
    concat_list.write_text(
        "".join(f"file '{p.resolve()}'\n" for p in clips),
        encoding="utf-8")
    ok, detail = _run(["ffmpeg", "-y", "-f", "concat", "-safe", "0",
                       "-i", str(concat_list), "-c:v", "libx264",
                       "-crf", "20", "-preset", "veryfast", "-an",
                       str(out_path)], timeout=600)
    if not ok or not out_path.exists():
        return None, detail
    return out_path, "ok"


def _scene_segment_from_clip(clip: Path, scene_dur: float, width: int,
                             height: int, work: Path,
                             idx: int) -> tuple[Path | None, str]:
    """One scene-length segment from a generated clip.

    Longer clips are trimmed to scene_dur; shorter clips loop to
    fill it. Returns (path|None, detail)."""
    seg = work / f"gen_scene{idx}.mp4"
    vf = (f"scale={width}:{height}:force_original_aspect_ratio=increase,"
          f"crop={width}:{height},fps=30,format=yuv420p")
    ok, detail = _run(["ffmpeg", "-y", "-stream_loop", "-1",
                       "-i", str(clip), "-t", f"{scene_dur:.2f}",
                       "-vf", vf, "-an", "-c:v", "libx264", "-crf", "20",
                       "-preset", "veryfast", str(seg)], timeout=300)
    if not ok or not seg.exists():
        return None, detail
    return seg, "ok"


def scene_prompts(topic: str | None = None,
                  brand: str | None = None) -> list[dict]:
    """One generation prompt per scene of the fixed 3-scene story.

    Reuses the same scene descriptions as the stills generator so
    the story stays consistent across providers. Prompts show
    workers from behind / hands / over-the-shoulder — never a
    recognizable face, never a named real person. The scene set is
    brand-aware (gen_visuals.scenes_for): Talvenor's story only
    for Talvenor topics, the neutral test-on-screen story otherwise.
    """
    out = []
    for spec in gen_visuals.scenes_for(topic, brand):
        out.append({
            "scene": spec["scene"],
            "shows": spec["shows"],
            "prompt": f"{spec['prompt']}, {gen_visuals.STYLE}",
        })
    return out


# ---------------------------------------------------------------------------
# config
# ---------------------------------------------------------------------------
@dataclass
class ProviderConfig:
    provider: str = "auto"          # auto | footage | stills | local | api
    fallback: str | None = None     # provider to try if the chosen one
                                    # fails; None = fail honestly, no
                                    # silent fallback
    # local provider
    local_engine: str = "wangp"     # wangp | framepack | custom
    local_cmd: str = ""             # command template (see README)
    local_wangp_dir: str = ""       # WanGP checkout dir (has wgp.py)
    local_queue: str = ""           # WanGP saved queue zip
    local_output_dir: str = ""      # where the engine writes clips
    local_timeout: int = 1800       # seconds per local generation run
    # api provider
    api_url: str = DEFAULT_API_URL
    api_poll_url: str = DEFAULT_API_POLL_URL
    api_key_env: str = "VIDEO_API_KEY"
    api_model: str = "openai-sora-2-text-to-video"
    api_body_json: str = DEFAULT_API_BODY_JSON
    api_timeout: int = 900          # seconds per scene, submit + poll
    api_poll_interval: int = 15     # seconds between polls
    retries: int = 1                # extra attempts per failed scene


# The config file is a small documented subset of YAML (see
# video_providers.yaml): top-level `key: value` lines plus `local:`
# and `api:` blocks with 2-space indented `key: value` lines.
# Comments (#) and blank lines are ignored. Unknown keys are an
# error — a typo in the config must fail loudly, not silently use a
# default the user did not ask for.
_CONFIG_KEYS = {
    "provider": ("provider", str),
    "fallback": ("fallback", str),
    "retries": ("retries", int),
}
_LOCAL_KEYS = {
    "engine": ("local_engine", str),
    "command": ("local_cmd", str),
    "wangp_dir": ("local_wangp_dir", str),
    "queue": ("local_queue", str),
    "output_dir": ("local_output_dir", str),
    "timeout": ("local_timeout", int),
}
_API_KEYS = {
    "url": ("api_url", str),
    "poll_url": ("api_poll_url", str),
    "key_env": ("api_key_env", str),
    "model": ("api_model", str),
    "body_json": ("api_body_json", str),
    "timeout": ("api_timeout", int),
    "poll_interval": ("api_poll_interval", int),
}
_SECTION_KEYS = {"local": _LOCAL_KEYS, "api": _API_KEYS}


def _parse_scalar(raw: str):
    raw = raw.strip()
    if raw in ("null", "~", ""):
        return None
    if raw in ("true", "True"):
        return True
    if raw in ("false", "False"):
        return False
    if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in ("'", '"'):
        return raw[1:-1]
    try:
        return int(raw)
    except ValueError:
        pass
    try:
        return float(raw)
    except ValueError:
        pass
    return raw


def parse_config_text(text: str) -> ProviderConfig:
    """Parse video_providers.yaml text. Raises ValueError on any bad
    key, bad value, or bad indentation — a config error must be
    loud, never silently defaulted."""
    cfg = ProviderConfig()
    section: str | None = None
    for lineno, line in enumerate(text.splitlines(), 1):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        indent = len(line) - len(line.lstrip(" "))
        stripped = line.strip()
        if indent == 0 and stripped.endswith(":") and " " not in stripped:
            section = stripped[:-1]
            if section not in _SECTION_KEYS:
                raise ValueError(
                    f"video_providers.yaml line {lineno}: unknown "
                    f"section '{section}' (valid sections: "
                    f"{', '.join(sorted(_SECTION_KEYS))})")
            continue
        if ":" not in stripped:
            raise ValueError(
                f"video_providers.yaml line {lineno}: expected "
                f"'key: value', got '{stripped}'")
        key, _, raw = stripped.partition(":")
        key, raw = key.strip(), raw.strip()
        if indent == 0:
            section = None
            table = _CONFIG_KEYS
        elif indent == 2 and section in _SECTION_KEYS:
            table = _SECTION_KEYS[section]
        else:
            raise ValueError(
                f"video_providers.yaml line {lineno}: bad indentation "
                f"— top-level keys have no indent, local:/api: keys "
                f"have exactly 2 spaces")
        if key not in table:
            valid = ", ".join(sorted(table))
            raise ValueError(
                f"video_providers.yaml line {lineno}: unknown key "
                f"'{key}' (valid keys here: {valid})")
        field, kind = table[key]
        value = _parse_scalar(raw)
        if value is not None and not isinstance(value, kind):
            raise ValueError(
                f"video_providers.yaml line {lineno}: key '{key}' "
                f"must be a {kind.__name__}, got '{raw}'")
        if field == "fallback" and value in ("", "null"):
            value = None
        setattr(cfg, field, value)
    validate_config(cfg)
    return cfg


def validate_config(cfg: ProviderConfig) -> None:
    """Raise ValueError with a clear message for any invalid config."""
    if cfg.provider not in PROVIDER_CHOICES:
        raise ValueError(
            f"unknown video provider '{cfg.provider}' in "
            f"video_providers.yaml — valid providers: "
            f"{', '.join(PROVIDER_CHOICES)} (or set --video-provider)")
    if cfg.fallback is not None and cfg.fallback not in PROVIDERS:
        raise ValueError(
            f"unknown fallback provider '{cfg.fallback}' in "
            f"video_providers.yaml — valid providers: "
            f"{', '.join(PROVIDERS)}")
    if cfg.local_engine not in LOCAL_ENGINES:
        raise ValueError(
            f"unknown local engine '{cfg.local_engine}' in "
            f"video_providers.yaml — valid engines: "
            f"{', '.join(LOCAL_ENGINES)}")
    if cfg.retries < 0:
        raise ValueError("retries must be 0 or more in "
                         "video_providers.yaml")


def load_config(path: Path | None) -> ProviderConfig:
    """Load the config file (default: repo-root video_providers.yaml).

    A missing file means defaults. A present-but-invalid file raises
    ValueError — never silently defaulted."""
    target = Path(path) if path else DEFAULT_CONFIG_PATH
    if not target.exists():
        return ProviderConfig()
    return parse_config_text(target.read_text(encoding="utf-8"))


def resolve(args) -> tuple[ProviderConfig, list[str]]:
    """Resolve the effective provider config for a run.

    Precedence: CLI flag > environment > config file > built-in
    default. Returns (config, errors): errors is empty on success;
    on any config problem it holds clear messages and the caller
    must fail honestly instead of building a video.
    """
    cfg_path = getattr(args, "video_config", None) or None
    try:
        cfg = load_config(Path(cfg_path) if cfg_path else None)
    except ValueError as exc:
        return ProviderConfig(), [str(exc)]
    except OSError as exc:
        return ProviderConfig(), [f"could not read video config: {exc}"]
    # Environment overrides (keys never live in the config file).
    flag = getattr(args, "video_provider", None)
    env_provider = os.environ.get("VIDEO_PROVIDER", "").strip()
    if flag:
        cfg.provider = flag
    elif env_provider:
        cfg.provider = env_provider
    env_url = os.environ.get("VIDEO_API_URL", "").strip()
    if env_url:
        cfg.api_url = env_url
    env_model = os.environ.get("VIDEO_MODEL", "").strip()
    if env_model:
        cfg.api_model = env_model
    env_cmd = os.environ.get("LOCAL_VIDEO_CMD", "").strip()
    if env_cmd:
        cfg.local_cmd = env_cmd
    try:
        validate_config(cfg)
    except ValueError as exc:
        return cfg, [str(exc)]
    return cfg, []


# ---------------------------------------------------------------------------
# providers
# ---------------------------------------------------------------------------
def _empty_result(provider: str) -> dict:
    return {
        "cut_path": None, "source": "none", "scene_sources": [],
        "gen": {"attempted": False, "per_scene": []},
        "provider": provider, "provider_scenes": [],
        "fallbacks": [], "missing": [], "reason": "",
    }


def _fail(provider: str, reason: str, missing: list[str]) -> dict:
    result = _empty_result(provider)
    result["reason"] = reason
    result["missing"] = missing
    return result


class VideoProvider:
    """One video backend. generate() returns the visuals dict above.

    It never raises: every failure is recorded honestly in the dict
    it returns, and the video stage writes that into 04-video.md.
    """

    name = "base"

    def generate(self, ctx: dict) -> dict:
        raise NotImplementedError


class FootageProvider(VideoProvider):
    """Real footage supplied with --footage. Preferred whenever given."""

    name = "footage"

    def generate(self, ctx: dict) -> dict:
        args = ctx["args"]
        work: Path = ctx["work"]
        width, height = ctx["width"], ctx["height"]
        cap = ctx["cap"]
        scene_count = ctx["scene_count"]
        footage_arg = getattr(args, "footage", "")
        if not footage_arg:
            return _fail(
                "footage",
                "the footage provider was selected but no --footage "
                "was given — no video was built",
                ["--footage <path> with a video file (or a folder of "
                 "video files)"])
        clips = collect_footage(footage_arg)
        if not clips:
            return _fail(
                "footage",
                f"no usable video files found at {footage_arg} — "
                "no video was built",
                [f"a video file (or a folder of video files) at "
                 f"{footage_arg}"])
        total = sum(c["duration"] for c in clips)
        used = min(total, cap)
        result = _empty_result("footage")
        result["source"] = "real footage"
        if total < cap:
            result["fallbacks"].append(
                f"footage totalled {total:.1f}s, under the {cap:.0f}s "
                f"target — the video uses all {used:.1f}s of it")
        scene_dur = used / scene_count
        result["scene_sources"] = ["real footage"] * scene_count
        result["provider_scenes"] = [
            {"scene": i + 1, "ok": True, "path": str(c["path"]),
             "note": f"real footage clip, {c['duration']:.1f}s"}
            for i, c in enumerate(clips)
        ]
        cut_path, detail = _footage_cut(clips, used, width, height, work)
        if cut_path is None:
            return _fail("footage",
                         f"footage cut failed ({detail}) — no video was built",
                         [f"readable video at {footage_arg}"])
        result["cut_path"] = cut_path
        result["used"] = used
        result["scene_dur"] = scene_dur
        return result


class StillsProvider(VideoProvider):
    """AI-generated stills (Pollinations, free, no key) + Ken Burns
    motion. The default when nothing else is configured."""

    name = "stills"

    def generate(self, ctx: dict) -> dict:
        work: Path = ctx["work"]
        width, height = ctx["width"], ctx["height"]
        scene_count = ctx["scene_count"]
        result = _empty_result("stills")
        result["gen"]["attempted"] = True
        stills = gen_visuals.generate_stills(work / "stills", width,
                                             height,
                                             scenes=ctx.get("scenes"))
        result["gen"]["per_scene"] = stills
        result["provider_scenes"] = [
            {"scene": s["scene"], "ok": s["ok"], "path": s.get("path"),
             "note": s["note"]}
            for s in stills
        ]
        if not any(s["ok"] for s in stills):
            reasons = "; ".join(
                f"scene {s['scene']}: {s['note']}" for s in stills)
            return _fail(
                "stills",
                "AI still generation failed for all 3 scenes "
                "(Pollinations, free) — no video was built",
                ["AI still generation was attempted (Pollinations, "
                 f"free) and failed for all 3 scenes — {reasons}. "
                 "The free image service is network-dependent; retry "
                 "the run, or supply real footage with "
                 "--footage <path> instead."])
        result["source"] = ("AI-generated stills + motion "
                            "(Pollinations, free)")
        result["fallbacks"].append(
            "visuals are AI-generated stills with slow Ken Burns "
            "motion (Pollinations, free) — not real footage and not "
            "true AI video motion")
        used = 15.0  # 3 stills x 5s each
        scene_dur = used / scene_count
        result["scene_sources"] = [
            (f"generated still scene{s['scene']}.jpg + Ken Burns motion"
             if s["ok"] else
             f"fallback slate — still generation failed ({s['note']})")
            for s in stills
        ]
        cut_path, detail = _motion_cut(stills, width, height, scene_dur,
                                       work)
        if cut_path is None:
            return _fail("stills",
                         f"motion cut failed ({detail}) — no video was built",
                         ["generated stills that FFmpeg can read"])
        result["cut_path"] = cut_path
        result["used"] = used
        result["scene_dur"] = scene_dur
        return result


def _default_gpu_probe() -> tuple[bool, str]:
    """Is there a CUDA GPU on this machine? (nvidia-smi check.)"""
    if not shutil.which("nvidia-smi"):
        return False, "nvidia-smi not found — no NVIDIA GPU detected"
    ok, out = _run(["nvidia-smi", "--query-gpu=name,memory.total",
                    "--format=csv,noheader"], timeout=30)
    if not ok or not out.strip():
        return False, f"nvidia-smi ran but reported no GPU ({out})"
    return True, out.strip()


class LocalProvider(VideoProvider):
    """Open-source video models on the USER's own machine.

    NOT VERIFIED on this machine (no GPU here): the adapter is
    written and mock-tested, but no real local generation is
    claimed. Engines:
      wangp     — WanGP headless batch: `python wgp.py --process
                  <queue.zip>` in the WanGP checkout (documented in
                  the WanGP README). The queue is created in the
                  WanGP web UI (Save Queue) and must contain one job
                  per scene; clips are collected from output_dir.
      framepack — FramePack is image-to-video: the scene stills are
                  generated first (gen_visuals) and passed as input
                  images. FramePack ships as a Gradio app — NO
                  official headless CLI was found in its README, so
                  the command is user-supplied and labelled
                  UNVERIFIED; without local.command it fails honestly.
      custom    — any command the user configures, with
                  {prompt} {image} {duration} {width} {height}
                  {output} placeholders, run once per scene.
    """

    name = "local"

    def __init__(self, cfg: ProviderConfig,
                 gpu_probe=_default_gpu_probe):
        self.cfg = cfg
        self.gpu_probe = gpu_probe

    def _scene_dur(self, ctx: dict) -> float:
        # Local clips are short (Sora-style 5-8s; WanGP varies), so
        # each scene gets a fixed 5s (short) / 10s (long) segment —
        # longer clips are trimmed, shorter ones loop to fill.
        return 5.0 if ctx["args"].format == "short video" else 10.0

    def generate(self, ctx: dict) -> dict:
        cfg = self.cfg
        work: Path = ctx["work"]
        width, height = ctx["width"], ctx["height"]
        scene_count = ctx["scene_count"]
        scenes = ctx.get("scenes") or scene_prompts()
        engine = cfg.local_engine
        result = _empty_result("local")
        result["source"] = f"local video ({engine})"
        if engine in ("wangp", "framepack"):
            has_gpu, gpu_note = self.gpu_probe()
            if not has_gpu:
                return _fail(
                    "local",
                    "no CUDA GPU on this machine — the local provider "
                    "cannot generate video here",
                    [f"an NVIDIA GPU on the machine running the "
                     f"pipeline ({gpu_note})",
                     f"WanGP needs {WANGP_START_VRAM_GB} GB VRAM to "
                     f"get started ({WANGP_MIN_VRAM_GB} GB for select "
                     f"low-VRAM models); FramePack needs "
                     f"{FRAMEPACK_MIN_VRAM_GB} GB VRAM minimum — see "
                     f"README.md 'Video providers'"])
        if engine == "wangp":
            return self._generate_wangp(ctx, result)
        if engine == "framepack":
            return self._generate_command(ctx, result, scenes,
                                          need_image=True)
        return self._generate_command(ctx, result, scenes,
                                      need_image=False)

    def _generate_wangp(self, ctx: dict, result: dict) -> dict:
        cfg = self.cfg
        work: Path = ctx["work"]
        scene_count = ctx["scene_count"]
        scene_dur = self._scene_dur(ctx)
        wangp_dir = Path(cfg.local_wangp_dir).expanduser() \
            if cfg.local_wangp_dir else None
        wgp = (wangp_dir / "wgp.py") if wangp_dir else None
        if not wgp or not wgp.exists():
            return _fail(
                "local",
                "WanGP checkout not found — the local provider cannot "
                "generate video",
                ["a WanGP checkout (github.com/deepbeepmeep/WanGP) — "
                 "set local.wangp_dir in video_providers.yaml to the "
                 "folder containing wgp.py",
                 "WanGP installed per its README (Python 3.10/3.11, "
                 "PyTorch + CUDA); 8 GB VRAM to get started"])
        queue = Path(cfg.local_queue).expanduser() \
            if cfg.local_queue else None
        if not queue or not queue.exists():
            return _fail(
                "local",
                "no WanGP queue file — the local provider cannot "
                "generate video",
                ["a saved WanGP queue (.zip) with one job per scene — "
                 "create it in the WanGP web UI (Save Queue) and set "
                 "local.queue in video_providers.yaml to its path"])
        out_dir = Path(cfg.local_output_dir).expanduser() \
            if cfg.local_output_dir else None
        if not out_dir or not out_dir.is_dir():
            return _fail(
                "local",
                "no WanGP output folder — the local provider cannot "
                "collect clips",
                ["local.output_dir in video_providers.yaml pointing at "
                 "the folder WanGP writes finished clips to"])
        # Documented headless invocation (WanGP README): process a
        # saved queue without launching the web UI.
        ok, detail = _run([sys.executable, str(wgp), "--process",
                           str(queue)], timeout=cfg.local_timeout,
                          )
        if not ok:
            return _fail(
                "local",
                f"WanGP headless run failed ({detail}) — no video "
                "was built",
                [f"a working WanGP install (the queue run above "
                 f"failed: {detail})"])
        clips = [p for p in sorted(
            out_dir.iterdir(),
            key=lambda p: p.stat().st_mtime)
            if p.is_file() and p.suffix.lower() in VIDEO_EXTS]
        if len(clips) < scene_count:
            return _fail(
                "local",
                f"WanGP produced {len(clips)} clip(s), needed "
                f"{scene_count} (one per scene) — no video was built",
                [f"{scene_count} clips in {out_dir} — the saved queue "
                 "must contain one job per scene"])
        return self._assemble(ctx, result, clips[-scene_count:],
                              scene_dur, "WanGP queue")

    def _generate_command(self, ctx: dict, result: dict,
                          scenes: list[dict], need_image: bool) -> dict:
        cfg = self.cfg
        work: Path = ctx["work"]
        width, height = ctx["width"], ctx["height"]
        scene_count = ctx["scene_count"]
        scene_dur = self._scene_dur(ctx)
        engine = cfg.local_engine
        if not cfg.local_cmd.strip():
            if engine == "framepack":
                return _fail(
                    "local",
                    "no command configured for the framepack engine — "
                    "the local provider cannot generate video",
                    ["local.command in video_providers.yaml — a batch "
                     "command that turns an input image + prompt into "
                     "a video clip. UNVERIFIED: FramePack ships as a "
                     "Gradio desktop app (demo_gradio.py); no official "
                     "headless CLI was found in its README, so no "
                     "default command is assumed here. A community "
                     "batch wrapper (e.g. FramePack-Batch) or your own "
                     "script goes here, with {prompt} {image} "
                     "{duration} {width} {height} {output} "
                     "placeholders.",
                     f"an NVIDIA RTX 30XX/40XX/50XX GPU with "
                     f"{FRAMEPACK_MIN_VRAM_GB} GB VRAM minimum "
                     "(FramePack README)"])
            return _fail(
                "local",
                "no command configured for the custom local engine — "
                "the local provider cannot generate video",
                ["local.command in video_providers.yaml — a command "
                 "with {prompt} {duration} {width} {height} {output} "
                 "placeholders that writes one video clip per scene"])
        stills: list[dict] = []
        if need_image:
            stills = gen_visuals.generate_stills(
                work / "stills", width, height,
                scenes=ctx.get("scenes"))
            result["gen"]["attempted"] = True
            result["gen"]["per_scene"] = stills
            if not any(s["ok"] for s in stills):
                return _fail(
                    "local",
                    "the framepack engine needs input stills and AI "
                    "still generation failed for all 3 scenes — no "
                    "video was built",
                    ["generated stills (Pollinations, free) — retry the "
                     "run, or supply real footage with --footage "
                     "<path> instead"])
        records: list[dict] = []
        for i, scene in enumerate(scenes):
            out_path = work / f"local_scene{i + 1}.mp4"
            image = ""
            if need_image:
                rec = stills[i] if i < len(stills) else {}
                image = rec.get("path") or ""
            try:
                cmd_text = cfg.local_cmd.format(
                    prompt=scene["prompt"],
                    image=image,
                    duration=int(scene_dur),
                    width=width,
                    height=height,
                    output=str(out_path),
                )
            except (KeyError, ValueError, IndexError) as exc:
                # A literal {brace} in the user's command (e.g. a JSON
                # body) breaks str.format — record it honestly per
                # scene instead of crashing the provider, which must
                # never raise.
                records.append({"scene": scene["scene"], "ok": False,
                                "path": None,
                                "note": f"command template did not parse "
                                        f"({exc}) — check for literal "
                                        "{braces} in local.command; double "
                                        "them ({{ }}) to keep them literal"})
                continue
            import shlex
            try:
                cmd = shlex.split(cmd_text)
            except ValueError as exc:
                records.append({"scene": scene["scene"], "ok": False,
                                "path": None,
                                "note": f"command did not parse ({exc})"})
                continue
            ok, detail = _run(cmd, timeout=cfg.local_timeout)
            dur = probe_duration(out_path) if ok else 0.0
            if ok and out_path.exists() and dur > 0:
                records.append({"scene": scene["scene"], "ok": True,
                                "path": str(out_path),
                                "note": f"{dur:.1f}s clip"})
            else:
                records.append({
                    "scene": scene["scene"], "ok": False, "path": None,
                    "note": detail if not ok else
                    "command ran but wrote no readable clip"})
        result["provider_scenes"] = records
        return self._assemble_from_records(ctx, result, records,
                                           scene_dur, engine)

    def _assemble(self, ctx: dict, result: dict, clips: list[Path],
                  scene_dur: float, label: str) -> dict:
        work: Path = ctx["work"]
        width, height = ctx["width"], ctx["height"]
        scene_count = ctx["scene_count"]
        segments: list[Path] = []
        for i, clip in enumerate(clips[:scene_count]):
            seg, detail = _scene_segment_from_clip(
                clip, scene_dur, width, height, work, i)
            if seg is None:
                return _fail("local",
                             f"{label} clip {i + 1} could not be cut "
                             f"to a scene ({detail}) — no video was built",
                             [f"readable {label} clips"])
            segments.append(seg)
        cut_path, detail = _concat_clips(segments, work, "local_cut.mp4")
        if cut_path is None:
            return _fail("local",
                         f"local clips could not be joined ({detail}) — "
                         "no video was built",
                         ["readable local clips"])
        used = scene_dur * scene_count
        result["cut_path"] = cut_path
        result["used"] = used
        result["scene_dur"] = scene_dur
        result["scene_sources"] = [
            f"local video ({label}) — scene {i + 1}"
            for i in range(scene_count)]
        result["fallbacks"].append(
            "visuals are true AI video motion from a local model — "
            "NOT real footage; quality depends on the local model "
            "and GPU")
        return result

    def _assemble_from_records(self, ctx: dict, result: dict,
                               records: list[dict], scene_dur: float,
                               engine: str) -> dict:
        work: Path = ctx["work"]
        width, height = ctx["width"], ctx["height"]
        scene_count = ctx["scene_count"]
        if not any(r["ok"] for r in records):
            reasons = "; ".join(
                f"scene {r['scene']}: {r['note']}" for r in records)
            failed = _fail(
                "local",
                f"local generation failed for all {scene_count} scenes "
                f"({engine}) — no video was built",
                [f"a working local setup — every scene failed: "
                 f"{reasons}"])
            # Keep the per-scene records (and any stills info) on
            # the failure — the stage file shows each scene's reason,
            # not just the summary above.
            failed["provider_scenes"] = records
            failed["gen"] = result.get("gen", failed["gen"])
            failed["fallbacks"] = (result.get("fallbacks", [])
                                   + failed["fallbacks"])
            return failed
        segments: list[Path] = []
        sources: list[str] = []
        for i, rec in enumerate(records):
            if rec["ok"]:
                seg, detail = _scene_segment_from_clip(
                    Path(rec["path"]), scene_dur, width, height, work, i)
                if seg is None:
                    segments.append(None)
                    sources.append(
                        f"fallback slate — clip cut failed ({detail})")
                    result["fallbacks"].append(
                        f"scene {rec['scene']}: clip could not be cut "
                        f"({detail}) — dark slate used instead")
                    continue
                segments.append(seg)
                sources.append(f"local video ({engine}) — scene "
                               f"{rec['scene']}")
            else:
                seg, detail = _motion_segment(
                    None, width, height, scene_dur,
                    ZOOM_MOVES[i % len(ZOOM_MOVES)],
                    work / f"local_slate{i}.mp4")
                if seg is None:
                    return _fail(
                        "local",
                        f"fallback slate failed ({detail}) — no video "
                        "was built",
                        ["FFmpeg working on this machine"])
                segments.append(seg)
                sources.append(
                    f"fallback slate — generation failed ({rec['note']})")
                result["fallbacks"].append(
                    f"scene {rec['scene']}: generation failed "
                    f"({rec['note']}) — dark slate used instead")
        cut_path, detail = _concat_clips(segments, work, "local_cut.mp4")
        if cut_path is None:
            return _fail("local",
                         f"local scenes could not be joined ({detail}) — "
                         "no video was built",
                         ["readable local clips"])
        used = scene_dur * scene_count
        result["cut_path"] = cut_path
        result["used"] = used
        result["scene_dur"] = scene_dur
        result["scene_sources"] = sources
        result["fallbacks"].append(
            "visuals are true AI video motion from a local model — "
            "NOT real footage; quality depends on the local model "
            "and GPU")
        return result


# ---------------------------------------------------------------------------
# api provider (paid cloud video, generic HTTP adapter)
# ---------------------------------------------------------------------------
def _http_json(method: str, url: str, headers: dict,
               body: dict | None, timeout: int) -> tuple[bool, dict | str]:
    """One HTTP JSON call. Returns (ok, parsed-json-or-error-text).

    The API key is passed in through `headers` by the caller and is
    never logged here."""
    data = None
    req_headers = dict(headers)
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        req_headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=req_headers,
                                 method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        try:
            raw = exc.read().decode("utf-8", "replace")
        except Exception:
            raw = ""
        return False, (f"HTTP {exc.code}: {raw[:300]}")
    except Exception as exc:  # noqa: BLE001 - record, don't crash
        return False, f"request failed: {exc}"
    try:
        return True, json.loads(raw)
    except json.JSONDecodeError:
        return False, f"response was not JSON: {raw[:300]}"


def _find_video_url(node, depth: int = 0) -> str | None:
    """Find a video URL anywhere in a parsed JSON response.

    Prefers .mp4/.webm/.mov links; falls back to any http(s) URL.
    The exact response shape differs per provider, so this searches
    instead of assuming one — nothing is invented about it."""
    found_any: str | None = None

    def walk(n, d: int):
        nonlocal found_any
        if d > 6:
            return None
        if isinstance(n, str) and n.startswith("http"):
            if found_any is None:
                found_any = n
            if n.lower().split("?")[0].endswith(
                    (".mp4", ".webm", ".mov")):
                return n
            return None
        if isinstance(n, dict):
            for key in ("video_url", "url", "video", "result_url",
                        "download_url", "output_url"):
                v = n.get(key)
                if isinstance(v, str) and v.startswith("http"):
                    if found_any is None:
                        found_any = v
                    if v.lower().split("?")[0].endswith(
                            (".mp4", ".webm", ".mov")):
                        return v
            for v in n.values():
                hit = walk(v, d + 1)
                if hit:
                    return hit
            return None
        if isinstance(n, list):
            for item in n:
                hit = walk(item, d + 1)
                if hit:
                    return hit
        return None

    hit = walk(node, depth)
    return hit or found_any


class ApiProvider(VideoProvider):
    """Paid cloud video generation through a generic HTTP adapter.

    Muapi is the documented example (verified 2026-11-07 from
    muapi.ai/sora): POST {api_url} with x-api-key + a JSON body,
    response {"request_id": ...}, then poll GET
    {api_poll_url with {request_id}} until status is completed and
    read the video URL from outputs. Key, URL, and model come ONLY
    from environment variables (VIDEO_API_KEY, VIDEO_API_URL,
    VIDEO_MODEL) or the config file — never from the repo, never
    logged. NOT VERIFIED with a real paid call: tests use a local
    fake server only, and no real call is ever made here without the
    user's own key and billing."""

    name = "api"

    def __init__(self, cfg: ProviderConfig):
        self.cfg = cfg

    def generate(self, ctx: dict) -> dict:
        cfg = self.cfg
        work: Path = ctx["work"]
        width, height = ctx["width"], ctx["height"]
        scene_count = ctx["scene_count"]
        scenes = ctx.get("scenes") or scene_prompts()
        scene_dur = 5.0 if ctx["args"].format == "short video" else 10.0
        result = _empty_result("api")
        result["source"] = f"paid cloud video ({cfg.api_model})"
        key_env = cfg.api_key_env or "VIDEO_API_KEY"
        api_key = os.environ.get(key_env, "")
        if not api_key:
            return _fail(
                "api",
                "no API key — the api provider cannot generate video",
                [f"environment variable {key_env} set to your API key "
                 f"(Muapi: create one at muapi.ai/access-keys, top up "
                 f"credits, then export {key_env}=<key> before running)"])
        headers = {"x-api-key": api_key}
        aspect = "9:16" if width < height else "16:9"
        resolution = "720p" if "sora-2-text" in cfg.api_url \
            and "pro" not in cfg.api_url else "1080p"
        try:
            body_template = json.loads(cfg.api_body_json)
        except json.JSONDecodeError as exc:
            return _fail(
                "api",
                f"api.body_json in video_providers.yaml is not valid "
                f"JSON ({exc}) — no video was built",
                ["a valid api.body_json — see the documented Muapi "
                 "shape in video_providers.yaml"])
        records: list[dict] = []
        for i, scene in enumerate(scenes):
            clip_path = work / f"api_scene{i + 1}.mp4"
            rec = self._generate_scene(
                scene, clip_path, headers, body_template, aspect,
                resolution, int(scene_dur), cfg)
            records.append(rec)
        result["provider_scenes"] = records
        return self._assemble(ctx, result, records, scene_dur)

    def _generate_scene(self, scene: dict, clip_path: Path,
                        headers: dict, body_template: dict,
                        aspect: str, resolution: str, duration: int,
                        cfg: ProviderConfig) -> dict:
        scene_no = scene["scene"]
        body: dict = {}
        for key, value in body_template.items():
            if isinstance(value, str):
                body[key] = value.format(
                    prompt=scene["prompt"], aspect_ratio=aspect,
                    duration=duration, resolution=resolution,
                    model=cfg.api_model)
            else:
                body[key] = value
        # The four standard fields are always set from the scene, with
        # the right types — the template values are placeholders only.
        # (Other string values in the template may still use the
        # {prompt}/{model}/... format placeholders above.)
        body["prompt"] = scene["prompt"]
        body["aspect_ratio"] = aspect
        body["duration"] = duration
        body["resolution"] = resolution
        attempts = 1 + max(0, cfg.retries)
        last_note = ""
        for attempt in range(attempts):
            ok, resp = _http_json("POST", cfg.api_url, headers, body,
                                  timeout=60)
            if not ok:
                last_note = f"submit failed ({resp})"
                continue
            if not isinstance(resp, dict) or not resp.get("request_id"):
                last_note = (f"submit returned no request_id "
                             f"({str(resp)[:200]})")
                continue
            request_id = resp["request_id"]
            poll_url = cfg.api_poll_url.format(request_id=request_id)
            import time as _time
            deadline = _time.monotonic() + cfg.api_timeout
            while _time.monotonic() < deadline:
                ok, poll = _http_json("GET", poll_url, headers, None,
                                      timeout=60)
                if not ok:
                    last_note = f"poll failed ({poll})"
                    break
                if not isinstance(poll, dict):
                    last_note = "poll returned no JSON object"
                    break
                status = str(poll.get("status") or
                             poll.get("state") or "").lower()
                if status in ("completed", "complete", "succeeded",
                              "success"):
                    video_url = _find_video_url(poll)
                    if not video_url:
                        last_note = ("completed but no video URL in the "
                                     "response")
                        break
                    return self._download(clip_path, video_url,
                                          scene_no)
                if status in ("failed", "error", "cancelled"):
                    err = poll.get("error") or poll.get("message") or ""
                    last_note = (f"provider reported failure "
                                 f"({str(err)[:200]})")
                    break
                _time.sleep(cfg.api_poll_interval)
            else:
                last_note = (f"timed out after {cfg.api_timeout}s "
                             "waiting for the provider")
            if "poll failed" in last_note or "timed out" in last_note:
                break
        return {"scene": scene_no, "ok": False, "path": None,
                "note": last_note or "unknown API failure"}

    def _download(self, clip_path: Path, video_url: str,
                  scene_no: int) -> dict:
        try:
            req = urllib.request.Request(video_url, method="GET")
            with urllib.request.urlopen(req, timeout=300) as resp:
                clip_path.write_bytes(resp.read())
        except Exception as exc:  # noqa: BLE001 - record, don't crash
            return {"scene": scene_no, "ok": False, "path": None,
                    "note": f"download failed ({exc})"}
        dur = probe_duration(clip_path)
        if dur <= 0:
            return {"scene": scene_no, "ok": False, "path": None,
                    "note": "downloaded file has no readable video "
                            "duration"}
        return {"scene": scene_no, "ok": True,
                "path": str(clip_path), "note": f"{dur:.1f}s clip"}

    def _assemble(self, ctx: dict, result: dict, records: list[dict],
                  scene_dur: float) -> dict:
        work: Path = ctx["work"]
        width, height = ctx["width"], ctx["height"]
        scene_count = ctx["scene_count"]
        if not any(r["ok"] for r in records):
            reasons = "; ".join(
                f"scene {r['scene']}: {r['note']}" for r in records)
            return _fail(
                "api",
                "paid video generation failed for all "
                f"{scene_count} scenes — no video was built",
                [f"a working paid setup — every scene failed: {reasons}",
                 "check the key, credits, and the endpoint in "
                 "video_providers.yaml / VIDEO_API_URL"])
        segments: list[Path] = []
        sources: list[str] = []
        for i, rec in enumerate(records):
            if rec["ok"]:
                seg, detail = _scene_segment_from_clip(
                    Path(rec["path"]), scene_dur, width, height, work, i)
                if seg is None:
                    segments.append(None)
                    sources.append(
                        f"fallback slate — clip cut failed ({detail})")
                    result["fallbacks"].append(
                        f"scene {rec['scene']}: clip could not be cut "
                        f"({detail}) — dark slate used instead")
                    continue
                segments.append(seg)
                sources.append(f"paid cloud video — scene {rec['scene']}")
            else:
                seg, detail = _motion_segment(
                    None, width, height, scene_dur,
                    ZOOM_MOVES[i % len(ZOOM_MOVES)],
                    work / f"api_slate{i}.mp4")
                if seg is None:
                    return _fail(
                        "api",
                        f"fallback slate failed ({detail}) — no video "
                        "was built",
                        ["FFmpeg working on this machine"])
                segments.append(seg)
                sources.append(
                    f"fallback slate — generation failed ({rec['note']})")
                result["fallbacks"].append(
                    f"scene {rec['scene']}: generation failed "
                    f"({rec['note']}) — dark slate used instead")
        cut_path, detail = _concat_clips(segments, work, "api_cut.mp4")
        if cut_path is None:
            return _fail("api",
                         f"paid scenes could not be joined ({detail}) — "
                         "no video was built",
                         ["readable downloaded clips"])
        used = scene_dur * scene_count
        result["cut_path"] = cut_path
        result["used"] = used
        result["scene_dur"] = scene_dur
        result["scene_sources"] = sources
        model = self.cfg.api_model
        price = MUAPI_PRICES.get(model, "")
        result["fallbacks"].append(
            "visuals are true AI video motion from a paid cloud model "
            f"({model}" + (f", {price}" if price else "") + ") — NOT "
            "real footage; each request is billed to the user's key")
        return result


# ---------------------------------------------------------------------------
# resolution + dispatch
# ---------------------------------------------------------------------------
def get_provider(name: str, cfg: ProviderConfig) -> VideoProvider:
    if name == "footage":
        return FootageProvider()
    if name == "stills":
        return StillsProvider()
    if name == "local":
        return LocalProvider(cfg)
    if name == "api":
        return ApiProvider(cfg)
    raise ValueError(f"unknown video provider '{name}'")


def resolve_provider(args, cfg: ProviderConfig) -> str:
    """Pick the provider for this run: footage wins when given,
    otherwise the configured provider, otherwise stills (the $0
    default)."""
    if getattr(args, "footage", ""):
        return "footage"
    if cfg.provider and cfg.provider != "auto":
        return cfg.provider
    return "stills"


def describe_plan(args, cfg: ProviderConfig, ctx: dict) -> list[str]:
    """Dry-run description of what the resolved provider WOULD do.

    Pure description: no engine is started, no still is fetched, no
    network call is made, no key value is read or printed. Use it to
    check a GPU machine's setup before a real run
    (--video-dry-run). Lines starting with "MISSING:" name the exact
    setup step that would stop a real run.
    """
    name = resolve_provider(args, cfg)
    lines = [f"provider: {name}"]
    if name == "footage":
        clips = collect_footage(getattr(args, "footage", ""))
        lines.append(
            f"footage: {len(clips)} clip(s) from {args.footage} — "
            "cut to 3 scenes, voiceover + captions added")
        return lines
    if name == "stills":
        lines.append(
            "visuals: 3 AI stills (Pollinations, free, no key) + "
            "slow Ken Burns motion")
        lines.append(
            "note: AI stills + motion — NOT true AI video motion "
            "and NOT real footage")
        return lines
    if name == "local":
        engine = cfg.local_engine
        lines.append(f"engine: {engine}")
        if engine in ("wangp", "framepack"):
            has_gpu, gpu_note = get_provider("local", cfg).gpu_probe()
            lines.append(
                "GPU: " + (f"found — {gpu_note}" if has_gpu
                           else f"NOT FOUND — {gpu_note}"))
        if engine == "wangp":
            wangp_dir = Path(cfg.local_wangp_dir).expanduser() \
                if cfg.local_wangp_dir else None
            wgp = (wangp_dir / "wgp.py") if wangp_dir else None
            queue = Path(cfg.local_queue).expanduser() \
                if cfg.local_queue else None
            out_dir = Path(cfg.local_output_dir).expanduser() \
                if cfg.local_output_dir else None
            if not wgp or not wgp.exists():
                lines.append(
                    "MISSING: WanGP checkout not found — set "
                    "local.wangp_dir in video_providers.yaml to the "
                    "folder containing wgp.py "
                    "(github.com/deepbeepmeep/WanGP)")
            if not queue or not queue.exists():
                lines.append(
                    "MISSING: no WanGP queue file — create one in the "
                    "WanGP web UI (Save Queue) and set local.queue")
            if not out_dir or not out_dir.is_dir():
                lines.append(
                    "MISSING: no WanGP output folder — set "
                    "local.output_dir to the folder WanGP writes "
                    "finished clips to")
            if wgp and wgp.exists() and queue and queue.exists():
                lines.append(
                    f"command: {sys.executable} {wgp} --process {queue}")
                lines.append(
                    "then: the newest "
                    f"{ctx.get('scene_count', 3)} clip(s) in "
                    f"{out_dir or 'local.output_dir'} are cut to scenes")
            return lines
        # framepack / custom: the command is user-supplied.
        if not cfg.local_cmd.strip():
            lines.append(
                "MISSING: local.command is not set — set it in "
                "video_providers.yaml (or LOCAL_VIDEO_CMD) to a "
                "command with {prompt} {image} {duration} {width} "
                "{height} {output} placeholders")
            if engine == "framepack":
                lines.append(
                    "note: FramePack ships as a Gradio desktop app — "
                    "no official headless CLI exists, so the command "
                    "is yours to supply (see docs/gpu-video-setup.md)")
            return lines
        scenes = ctx.get("scenes") or scene_prompts()
        width, height = ctx["width"], ctx["height"]
        scene_dur = 5.0 if ctx.get("format") == "short video" else 10.0
        work = ctx["work"]
        for i, scene in enumerate(scenes):
            image = (str(work / "stills" / f"scene{scene['scene']}.jpg")
                     if engine == "framepack" else "")
            try:
                cmd_text = cfg.local_cmd.format(
                    prompt=scene["prompt"], image=image,
                    duration=int(scene_dur), width=width,
                    height=height,
                    output=str(work / f"local_scene{i + 1}.mp4"))
            except (KeyError, ValueError, IndexError) as exc:
                lines.append(
                    f"scene {scene['scene']}: command template did not "
                    f"parse ({exc}) — check for literal {{braces}} in "
                    "local.command")
                continue
            lines.append(f"scene {scene['scene']}: {cmd_text}")
        return lines
    if name == "api":
        key_env = cfg.api_key_env or "VIDEO_API_KEY"
        lines.append(f"endpoint: POST {cfg.api_url}")
        lines.append(f"model: {cfg.api_model}")
        lines.append(
            f"key: from environment variable {key_env} "
            f"({'set' if os.environ.get(key_env) else 'NOT SET'} — "
            "the value is never printed)")
        lines.append(f"poll: {cfg.api_poll_url}")
        lines.append(
            "note: one paid request per scene; the charge happens "
            "only on a real run, never on a dry run")
        return lines
    return lines


def run_provider(args, cfg: ProviderConfig, ctx: dict) -> dict:
    """Run the resolved provider, with the configured fallback if
    the first one fails. Never silently swaps: a fallback is only
    tried when the config sets one, and the swap is recorded."""
    name = resolve_provider(args, cfg)
    provider = get_provider(name, cfg)
    result = provider.generate(ctx)
    if result["cut_path"] is None and cfg.fallback:
        fallback = get_provider(cfg.fallback, cfg)
        result["fallbacks"].append(
            f"provider '{name}' failed ({result['reason']}); falling "
            f"back to '{cfg.fallback}' per video_providers.yaml")
        second = fallback.generate(ctx)
        second["fallbacks"] = (result["fallbacks"]
                               + second["fallbacks"])
        if second["cut_path"] is not None:
            second["provider"] = cfg.fallback
            return second
        second["missing"] = result["missing"] + second["missing"]
        return second
    result["provider"] = name
    return result
