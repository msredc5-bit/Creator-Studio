#!/usr/bin/env python3
"""AI still generation for the Creator OS video stage (Pollinations.ai).

This is the ONLY module in this repo that makes network calls: it
fetches free text-to-image stills from Pollinations.ai (no API key,
no signup, $0). Everything else in src/, scripts/, and tests/ is
offline by design — see test_no_network_code_in_src_and_scripts,
which allowlists this one file.

What it does: given the 3 scene descriptions from the video stage,
it builds one image prompt per scene and downloads one still per
scene into <out-dir>/video_work/stills/. The video stage then gives
each still slow Ken Burns motion (FFmpeg zoompan). That is AI stills
+ motion — NOT true AI video motion and NOT real footage — and it is
labelled exactly that way wherever it is used.

Rules:
- No real person's face/voice; no copyrighted characters. Prompts
  show workers from behind / hands / over-the-shoulder, phones and
  shops — never a recognizable face, never a named real person.
- On any generation failure (network error, bad response, timeout),
  that scene fails honestly: the failure and its reason are recorded
  per scene, the other scenes still build, and if ALL scenes fail no
  video is built at all.
- A small bottom crop removes the Pollinations watermark corner when
  present; the crop is recorded in the per-scene record.
- Timeouts are overridable for tests via CREATOR_OS_GEN_TIMEOUT and
  CREATOR_OS_GEN_RETRY_TIMEOUT (seconds).
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from urllib.parse import quote

POLLINATIONS_BASE = "https://image.pollinations.ai/prompt"
DEFAULT_SEED = 42
GEN_TIMEOUT = 60        # seconds per still, first attempt
RETRY_TIMEOUT = 30      # seconds per still, retry with simpler prompt
MIN_BYTES = 5000        # a real JPEG still is far larger than this
WATERMARK_CROP = 0.08   # crop this fraction off the bottom (watermark corner)

STYLE = ("photorealistic, cinematic lighting, camera behind the "
         "subject, face not visible, no readable text, no watermark, "
         "no logo")
STYLE_SIMPLE = "photorealistic, face not visible, no text"

# One prompt per scene of the fixed 3-scene story. Workers are shown
# from behind, hands, or over-the-shoulder — never a recognizable
# face, never a named real person.
SCENES = [
    {
        "scene": 1,
        "shows": "a real worker working",
        "prompt": ("plumber in work clothes fixing a kitchen sink, "
                   "seen from behind, toolbox and work van nearby, "
                   "warm indoor light"),
        "simple": "plumber fixing a sink, seen from behind",
    },
    {
        "scene": 2,
        "shows": "a phone ringing and missed",
        "prompt": ("close-up of a smartphone lying on a workbench "
                   "displaying a large incoming call screen, a gloved "
                   "hand reaching toward the phone, plumbing tools "
                   "blurred in the background"),
        "simple": "smartphone on a workbench showing an incoming call",
    },
    {
        "scene": 3,
        "shows": "Talvenor answering and booking",
        "prompt": ("view from directly behind a receptionist wearing a "
                   "headset, back of the head and shoulders only, desk "
                   "with a phone and notebook in front, warm office light"),
        "simple": "receptionist with headset seen from behind at a desk",
    },
]


def _timeout(env_name: str, default: int) -> int:
    try:
        return max(5, int(os.environ.get(env_name, default)))
    except (TypeError, ValueError):
        return default


def _fetch(url: str, out_path: Path, timeout: int) -> tuple[bool, str]:
    """Download one URL with curl. Returns (ok, note)."""
    try:
        proc = subprocess.run(
            ["curl", "-sSL", "--max-time", str(timeout), url,
             "-o", str(out_path)],
            capture_output=True, text=True, timeout=timeout + 15)
    except subprocess.TimeoutExpired:
        return False, f"curl timed out after {timeout}s"
    except Exception as exc:  # noqa: BLE001 - record, don't crash
        return False, f"curl could not start: {exc}"
    if proc.returncode != 0:
        detail = (proc.stderr or "").strip()
        return False, f"curl exited {proc.returncode}: {detail[-200:]}"
    if not out_path.exists():
        return False, "curl wrote no file"
    data = out_path.read_bytes()
    if len(data) < MIN_BYTES:
        return False, f"downloaded only {len(data)} bytes (not an image)"
    if data[:3] != b"\xff\xd8\xff":
        return False, "downloaded file is not a JPEG"
    return True, f"{len(data)} bytes"


def _crop_watermark(path: Path) -> str:
    """Crop the bottom WATERMARK_CROP off the still (watermark corner).

    Returns a short note describing what happened.
    """
    try:
        from PIL import Image
    except ImportError:
        return "watermark crop skipped (PIL unavailable)"
    try:
        img = Image.open(path).convert("RGB")
        w, h = img.size
        img.crop((0, 0, w, int(h * (1 - WATERMARK_CROP)))).save(
            path, "JPEG", quality=90)
        return (f"bottom {int(WATERMARK_CROP * 100)}% cropped "
                "(Pollinations watermark corner)")
    except Exception as exc:  # noqa: BLE001 - record, don't crash
        return f"watermark crop failed ({exc}) — still kept as downloaded"


def _build_url(prompt: str, width: int, height: int, seed: int) -> str:
    return (f"{POLLINATIONS_BASE}/{quote(prompt)}"
            f"?width={width}&height={height}&nologo=true&seed={seed}")


def generate_stills(stills_dir: Path, width: int, height: int,
                    seed: int = DEFAULT_SEED) -> list[dict]:
    """Generate one still per scene. Returns a per-scene record list.

    Each record: {scene, shows, ok, path (str|None), prompt,
    note}. Never raises; every failure is recorded in its record.
    """
    stills_dir.mkdir(parents=True, exist_ok=True)
    timeout = _timeout("CREATOR_OS_GEN_TIMEOUT", GEN_TIMEOUT)
    retry_timeout = _timeout("CREATOR_OS_GEN_RETRY_TIMEOUT", RETRY_TIMEOUT)
    records: list[dict] = []
    for spec in SCENES:
        out_path = stills_dir / f"scene{spec['scene']}.jpg"
        prompt = f"{spec['prompt']}, {STYLE}"
        url = _build_url(prompt, width, height, seed + spec["scene"])
        ok, note = _fetch(url, out_path, timeout)
        used_prompt = prompt
        if not ok:
            # One retry with a simpler prompt, per the skill's rule.
            simple = f"{spec['simple']}, {STYLE_SIMPLE}"
            url = _build_url(simple, width, height, seed + spec["scene"])
            ok2, note2 = _fetch(url, out_path, retry_timeout)
            if ok2:
                used_prompt = simple
                note = (f"first attempt failed ({note}); retry with "
                        f"simpler prompt succeeded — {note2}")
                ok = True
            else:
                note = (f"first attempt failed ({note}); retry with "
                        f"simpler prompt also failed ({note2})")
        if ok:
            note = f"{note}; {_crop_watermark(out_path)}"
        records.append({
            "scene": spec["scene"],
            "shows": spec["shows"],
            "ok": ok,
            "path": str(out_path) if ok else None,
            "prompt": used_prompt,
            "note": note,
        })
    return records


if __name__ == "__main__":
    import json as _json
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "stills")
    w = int(sys.argv[2]) if len(sys.argv) > 2 else 1080
    h = int(sys.argv[3]) if len(sys.argv) > 3 else 1920
    print(_json.dumps(generate_stills(out, w, h), indent=2))
