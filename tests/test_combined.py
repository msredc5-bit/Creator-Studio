"""Creator OS combined tests — offline, mock mode only, except the one
generation test (which calls the free Pollinations image service once
and passes honestly either way if the network fails).

Run with pytest (preferred):
  python3 -m pytest tests/ -q

Or directly (stdlib fallback, same checks):
  python3 tests/test_combined.py

$0 spend. No network except the generation test, no keys, nothing
publishes.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.creator_workers import PublishPrep, ROSTER  # noqa: E402
from src.workers.base import MockLLM, Task  # noqa: E402
from scripts import video_providers as vp  # noqa: E402
from scripts.creator_os_run import main as run_pipeline  # noqa: E402

ALLOWED_GATES = {"ok", "post it", "upload it", "send", "go", None}
STAGE_FILES = [
    "00-niche.md",
    "00-plan.md",
    "01-research.md",
    "02-concept-score.md",
    "02-script.md",
    "03-visual-package.md",
    "04-video.md",
    "05-edit.md",
    "06-caption-seo.md",
    "07-publish-prep.md",
    "08-report.md",
    "09-upload.md",
    "10-next-plan.md",
]


def test_roster_is_6_with_gates():
    assert len(ROSTER) == 6, f"workers: {len(ROSTER)}"
    for cls in ROSTER:
        assert getattr(cls, "task_kind", None), cls.__name__
        assert getattr(cls, "requires_gate", "MISSING") in ALLOWED_GATES, (
            cls.__name__)


def test_publish_prep_never_marks_ready():
    llm = MockLLM()
    worker = PublishPrep("CRT-PublishPrep", "b1", "CRT", "PublishPrep", llm)
    result = worker.execute(Task(task_id="t1", business_id="b1",
                                division_id="CRT", kind="publish_prep",
                                payload={"topic": "x"}))
    assert result.status == "ok"
    assert result.output.get("ready_to_publish") is False
    assert result.output.get("gate") == "post it"
    assert "MOCK DRAFT" in result.notes


def test_mock_llm_is_labelled_and_offline():
    llm = MockLLM()
    text = llm.complete("draft something")
    assert "[MOCK DRAFT" in text
    assert llm.health()["spend_usd"] == 0.0


def _run_mock_pipeline(tmp_path: Path) -> Path:
    # --no-gen-visuals keeps the shared mock helper offline and fast:
    # generation is tested separately, once, in its own test.
    out_dir = tmp_path / "out"
    code = run_pipeline([
        "--topic", "AI receptionist for plumbers",
        "--format", "short video",
        "--niche", "US home-service owners",
        "--audience", "plumbers who miss calls on the job",
        "--no-gen-visuals",
        "--out", str(out_dir),
    ])
    assert code == 0
    return out_dir


def test_runner_mock_end_to_end(tmp_path):
    out_dir = _run_mock_pipeline(tmp_path)
    for name in STAGE_FILES:
        path = out_dir / name
        assert path.exists(), f"missing stage file: {name}"
        assert path.stat().st_size > 200, f"stage file too small: {name}"


def test_no_stage_claims_a_publish_or_send(tmp_path):
    out_dir = _run_mock_pipeline(tmp_path)
    banned = ["status: published", "sent successfully", "uploaded to",
              "published to YouTube", "posted to"]
    for name in STAGE_FILES:
        text = (out_dir / name).read_text(encoding="utf-8").lower()
        for phrase in banned:
            assert phrase not in text, f"{name} claims: {phrase}"
    prep = (out_dir / "07-publish-prep.md").read_text(encoding="utf-8")
    assert "ready_to_publish: false" in prep
    assert "post it" in prep or "upload it" in prep


def test_hookscore_actually_ran(tmp_path):
    out_dir = _run_mock_pipeline(tmp_path)
    text = (out_dir / "02-script.md").read_text(encoding="utf-8")
    assert "hookscore" in text.lower()
    assert "Verdict" in text
    assert "Formula" in text


def test_title_lint_actually_ran(tmp_path):
    out_dir = _run_mock_pipeline(tmp_path)
    text = (out_dir / "03-visual-package.md").read_text(encoding="utf-8")
    assert "title.py" in text.lower()
    assert "Score:" in text
    assert "characters" in text


def test_edit_stage_skipped_honestly_without_transcript(tmp_path):
    out_dir = _run_mock_pipeline(tmp_path)
    text = (out_dir / "05-edit.md").read_text(encoding="utf-8")
    assert "No transcript supplied" in text
    assert "skipped honestly" in text


def test_retention_stage_skipped_honestly_without_export(tmp_path):
    out_dir = _run_mock_pipeline(tmp_path)
    text = (out_dir / "08-report.md").read_text(encoding="utf-8")
    assert "No retention export supplied" in text
    assert "never estimated" in text


def test_video_stage_without_footage_states_missing_inputs(tmp_path):
    out_dir = _run_mock_pipeline(tmp_path)
    text = (out_dir / "04-video.md").read_text(encoding="utf-8")
    assert "No video was built" in text
    assert "Missing inputs" in text
    assert "--footage" in text
    assert "a real worker working" in text
    assert "no-gen-visuals" in text
    assert not (out_dir / "video.mp4").exists()


def test_video_stage_builds_real_mp4_with_footage(tmp_path):
    import json as _json

    clip = tmp_path / "test-footage.mp4"
    proc = subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i",
         "testsrc=duration=12:size=640x360:rate=30",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", str(clip)],
        capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0, proc.stderr
    assert clip.exists()
    out_dir = tmp_path / "out"
    code = run_pipeline([
        "--topic", "AI receptionist for plumbers",
        "--format", "short video",
        "--niche", "US home-service owners",
        "--audience", "plumbers who miss calls on the job",
        "--footage", str(clip),
        "--out", str(out_dir),
    ])
    assert code == 0
    video = out_dir / "video.mp4"
    assert video.exists(), "video.mp4 was not built"
    assert video.stat().st_size > 10000, "video.mp4 suspiciously small"
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries",
         "stream=codec_type,width,height",
         "-show_entries", "format=duration",
         "-of", "json", str(video)],
        capture_output=True, text=True, timeout=60)
    assert probe.returncode == 0, probe.stderr
    data = _json.loads(probe.stdout)
    kinds = [s.get("codec_type") for s in data.get("streams", [])]
    assert "video" in kinds, f"no video stream: {data}"
    assert float(data["format"]["duration"]) > 0
    vstream = next(s for s in data["streams"]
                   if s.get("codec_type") == "video")
    assert (vstream.get("width"), vstream.get("height")) == (1080, 1920)
    text = (out_dir / "04-video.md").read_text(encoding="utf-8")
    assert "Built" in text
    assert "video.mp4" in text
    assert "No video was built" not in text
    assert "Scene 1" in text
    assert "You run the jobs. We run the phone." in text


def test_video_stage_generates_stills_and_builds_video_without_footage(tmp_path):
    """Topic in, video out, no footage: generation is attempted once.

    Network-dependent by design: if Pollinations answers, a real
    video.mp4 must exist and the stage file must say AI stills +
    motion. If the network fails, the suite must still pass — the
    stage file must then record the honest per-scene failure and no
    video may exist. Either outcome is asserted, never faked.
    """
    import os as _os

    old_timeout = _os.environ.get("CREATOR_OS_GEN_TIMEOUT")
    old_retry = _os.environ.get("CREATOR_OS_GEN_RETRY_TIMEOUT")
    _os.environ["CREATOR_OS_GEN_TIMEOUT"] = "45"
    _os.environ["CREATOR_OS_GEN_RETRY_TIMEOUT"] = "30"
    try:
        out_dir = tmp_path / "out"
        code = run_pipeline([
            "--topic", "AI receptionist for plumbers",
            "--format", "short video",
            "--niche", "US home-service owners",
            "--audience", "plumbers who miss calls on the job",
            "--out", str(out_dir),
        ])
    finally:
        if old_timeout is None:
            _os.environ.pop("CREATOR_OS_GEN_TIMEOUT", None)
        else:
            _os.environ["CREATOR_OS_GEN_TIMEOUT"] = old_timeout
        if old_retry is None:
            _os.environ.pop("CREATOR_OS_GEN_RETRY_TIMEOUT", None)
        else:
            _os.environ["CREATOR_OS_GEN_RETRY_TIMEOUT"] = old_retry
    assert code == 0
    text = (out_dir / "04-video.md").read_text(encoding="utf-8")
    assert "Pollinations" in text, "stage file must name the image source"
    assert "AI-generated stills + motion" in text
    assert "Provider: `stills`" in text, (
        "stage file must record the resolved video provider")
    video = out_dir / "video.mp4"
    if "## Built" in text:
        assert video.exists(), "stage file claims Built but no video.mp4"
        assert video.stat().st_size > 10000, "video.mp4 suspiciously small"
        probe = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries",
             "stream=codec_type,width,height",
             "-show_entries", "format=duration",
             "-of", "json", str(video)],
            capture_output=True, text=True, timeout=60)
        assert probe.returncode == 0, probe.stderr
        import json as _json
        data = _json.loads(probe.stdout)
        kinds = [s.get("codec_type") for s in data.get("streams", [])]
        assert "video" in kinds, f"no video stream: {data}"
        assert float(data["format"]["duration"]) > 0
        vstream = next(s for s in data["streams"]
                       if s.get("codec_type") == "video")
        assert (vstream.get("width"), vstream.get("height")) == (1080, 1920)
        stills = list((out_dir / "video_work" / "stills").glob("*.jpg"))
        assert len(stills) >= 1, "no generated stills on disk"
        assert "No video was built" not in text
    else:
        assert "No video was built" in text
        assert not video.exists(), "no video may exist on a failed build"
        assert "generation failed" in text.lower(), (
            "a failed build must record the generation failure")


def test_no_network_code_in_src_and_scripts():
    banned = ["urllib", "requests", "http.client", "socket", "httpx",
              "aiohttp"]
    # The three documented exceptions: scripts/gen_visuals.py calls the
    # free Pollinations image service (no key), scripts/video_providers.py
    # calls a paid video API only when the user configures the api
    # provider with their own key, and scripts/upload_youtube.py calls
    # the YouTube Data API only when the owner enables the upload stage
    # twice (flag + env var) with their own credentials. Everything
    # else in src/, scripts/, and tests/ makes no network calls.
    allowed = {ROOT / "scripts" / "gen_visuals.py",
               ROOT / "scripts" / "video_providers.py",
               ROOT / "scripts" / "upload_youtube.py"}
    for base in (ROOT / "src", ROOT / "scripts", ROOT / "tests"):
        for path in base.rglob("*.py"):
            if path.name == Path(__file__).name:
                continue  # this test file names the banned words itself
            if path in allowed:
                continue  # the one documented network module
            text = path.read_text(encoding="utf-8")
            for word in banned:
                assert word not in text, f"{path}: network token '{word}'"


def test_network_calls_only_in_documented_modules():
    """No .py file may call the network except the three documented
    ones: gen_visuals.py (free Pollinations images, no key),
    video_providers.py (paid video API, only when the user configures
    the api provider with their own key), and upload_youtube.py
    (YouTube Data API, only when the owner enables the upload stage
    twice with their own credentials). (Naming the services in
    labels/docstrings is fine — the call itself lives only in those
    three files.)"""
    allowed = {ROOT / "scripts" / "gen_visuals.py",
               ROOT / "scripts" / "video_providers.py",
               ROOT / "scripts" / "upload_youtube.py"}
    for base in (ROOT / "src", ROOT / "scripts", ROOT / "tests"):
        for path in base.rglob("*.py"):
            if path.name == Path(__file__).name:
                continue  # this test file names them itself
            if path in allowed:
                continue
            text = path.read_text(encoding="utf-8")
            assert "pollinations.ai" not in text.lower(), (
                f"{path} calls the Pollinations endpoint")
            assert '"curl"' not in text and "'curl'" not in text, (
                f"{path} invokes curl")
            assert "api.muapi.ai" not in text.lower(), (
                f"{path} calls the Muapi endpoint")


def test_youtube_tools_still_run_standalone():
    tool = ROOT / "youtube-skills" / "yt-script" / "hookscore.py"
    proc = subprocess.run(
        [sys.executable, str(tool), "--hook",
         "Every missed call is a lost job", "--json"],
        capture_output=True, text=True, timeout=60, cwd=str(ROOT))
    assert proc.returncode == 0, proc.stderr
    import json
    rows = json.loads(proc.stdout)
    assert rows and "verdict" in rows[0]


# ---------------------------------------------------------------------------
# video providers (scripts/video_providers.py)
# ---------------------------------------------------------------------------
def _provider_args(**overrides):
    import argparse
    args = argparse.Namespace(
        footage="", gen_visuals=True, video_provider=None,
        video_config="", format="short video",
        voice="avocado_v2:MAI_01")
    for key, value in overrides.items():
        setattr(args, key, value)
    return args


def _provider_ctx(tmp_path, fmt="short video"):
    work = tmp_path / "work"
    work.mkdir(parents=True, exist_ok=True)
    width, height = (1080, 1920) if fmt == "short video" else (1920, 1080)
    return {
        "args": _provider_args(format=fmt), "work": work,
        "width": width, "height": height,
        "scene_count": 3, "cap": 30.0 if fmt == "short video" else 90.0,
        "scenes": vp.scene_prompts(), "format": fmt,
    }


def test_provider_config_defaults():
    cfg, errors = vp.resolve(_provider_args())
    assert errors == [], errors
    assert cfg.provider == "auto"
    assert cfg.fallback is None
    assert cfg.local_engine == "wangp"
    assert cfg.api_url.startswith("https://api.muapi.ai/")
    assert cfg.api_key_env == "VIDEO_API_KEY"


def test_provider_config_bad_name():
    import pytest
    with pytest.raises(ValueError, match="unknown video provider"):
        vp.parse_config_text("provider: bogus\n")
    with pytest.raises(ValueError, match="unknown local engine"):
        vp.parse_config_text("local:\n  engine: nope\n")
    with pytest.raises(ValueError, match="unknown key"):
        vp.parse_config_text("provider: auto\ntypo_key: 1\n")
    with pytest.raises(ValueError, match="unknown fallback"):
        vp.parse_config_text("provider: stills\nfallback: bogus\n")


# ---------------------------------------------------------------------------
# video stage brand-awareness: the Talvenor template (missed-call
# lines, Talvenor logo, plumber/receptionist scenes) applies ONLY
# to Talvenor runs. Any other topic gets neutral topic-derived
# lines and a text-only end card.
# ---------------------------------------------------------------------------
def test_video_plan_generic_topic_has_no_talvenor():
    import json
    from scripts.video_build import _plan
    args = _provider_args(topic="Nano Banana 2 free test: 5 photo edits",
                          format="long video", brand="auto")
    plan = _plan(args)
    blob = json.dumps(plan)
    assert "Talvenor" not in blob
    assert "missed call" not in blob
    assert "Nano Banana 2" in plan["scenes"][0]["vo_line"]
    assert plan["endcard"]["logo"] == ""
    assert plan["endcard"]["cta"] == "Subscribe for the next test."


def test_video_plan_talvenor_topic_keeps_brand():
    from scripts.video_build import _plan
    args = _provider_args(topic="Talvenor AI receptionist for plumbers",
                          format="short video", brand="auto")
    plan = _plan(args)
    assert plan["scenes"][0]["vo_line"] == "Every missed call is a lost job."
    assert plan["scenes"][2]["shows"] == "Talvenor answering and booking"
    assert plan["endcard"]["logo"].endswith("talvenor-logo.png")
    assert plan["endcard"]["headline"] == "You run the jobs. We run the phone."


def test_video_plan_brand_flag_overrides_topic():
    import json
    from scripts.video_build import _plan
    args = _provider_args(topic="Nano Banana 2 free test",
                          format="short video", brand="talvenor")
    assert _plan(args)["scenes"][0]["vo_line"] == \
        "Every missed call is a lost job."
    args2 = _provider_args(topic="Talvenor AI receptionist",
                           format="short video", brand="generic")
    blob = json.dumps(_plan(args2))
    # The topic name itself may appear, but no brand lines or logo.
    assert "missed call" not in blob
    assert "talvenor-logo.png" not in blob
    assert "You run the jobs" not in blob


def test_scene_prompts_follow_topic():
    import json
    generic = vp.scene_prompts(topic="Nano Banana 2 test")
    blob = json.dumps(generic)
    assert "Talvenor" not in blob
    assert "plumber" not in blob.lower()
    assert "receptionist" not in blob.lower()
    # No topic given: no brand is assumed either — the neutral set.
    assert "Talvenor" not in json.dumps(vp.scene_prompts())


# ---------------------------------------------------------------------------
# agent-is-the-brain upgrade: --script voiceover lines, real thumbnail,
# working voice (tts stdin fix)
# ---------------------------------------------------------------------------
def test_tts_line_feeds_stdin_and_synthesises(tmp_path):
    """Regression: tts_line once passed --text-stdin without feeding
    stdin, so the binary waited for input until the 60s timeout on
    every line and all videos came out silent.
    """
    from scripts.video_build import tts_line
    from scripts.video_providers import probe_duration
    out = tmp_path / "vo.mp3"
    ok, note = tts_line("Testing the free AI tool today.",
                        "avocado_v2:MAI_01", out)
    if ok:
        assert out.exists() and out.stat().st_size > 0
        assert probe_duration(out) > 0
    else:
        # The tts service itself may be briefly down — but the old
        # bug (waiting on stdin) must not be the reason.
        assert "timed out after 60s" not in note, note


def test_script_lines_flow_into_plan(tmp_path):
    from scripts.video_build import _plan, resolve_vo_lines
    script = tmp_path / "vo-lines.txt"
    script.write_text(
        "Nano Banana turns a photo into a figurine.\n"
        "It changed only the background here.\n"
        "And the verdict: free is enough for this edit.\n"
        "One extra line, ignored.\n", encoding="utf-8")
    args = _provider_args(topic="Nano Banana 2 free test",
                          format="short video", brand="generic",
                          script=str(script))
    vo = resolve_vo_lines(args, tmp_path)
    assert vo["error"] is None
    assert vo["source"].startswith("--script")
    assert vo["lines"][0].startswith("Nano Banana turns")
    plan = _plan(args, vo["lines"])
    assert plan["scenes"][0]["vo_line"] == \
        "Nano Banana turns a photo into a figurine."
    assert plan["scenes"][2]["vo_line"] == \
        "And the verdict: free is enough for this edit."
    assert "only the first 3" in " ".join(plan.get("vo_notes", []))


def test_missing_script_file_fails_honestly(tmp_path):
    from scripts.video_build import build_video
    args = _provider_args(topic="Nano Banana 2 free test",
                          format="short video", brand="generic",
                          script=str(tmp_path / "nope.txt"))
    out_dir = tmp_path / "out"
    out_dir.mkdir(parents=True, exist_ok=True)
    result = build_video(args, out_dir, out_dir / "video_work")
    assert result["built"] is False
    assert "script" in result["reason"].lower()
    assert not (out_dir / "video.mp4").exists()


def test_script_with_apostrophe_builds_video(tmp_path):
    """Regression: a VO line with an apostrophe (Google's) broke the
    ffmpeg drawtext filter (No such filter: '0.30') and no video
    was built. Captions now go through textfile, so punctuation
    in script lines is safe.
    """
    import subprocess
    clip = tmp_path / "test-footage.mp4"
    proc = subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i",
         "testsrc=duration=12:size=640x360:rate=30",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", str(clip)],
        capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0, proc.stderr
    script = tmp_path / "vo-lines.txt"
    script.write_text("Google's free tool: test it yourself.\n"
                      "Don't guess — watch what changes.\n"
                      "It's free, and here's the verdict.\n",
                      encoding="utf-8")
    out_dir = tmp_path / "out"
    code = run_pipeline([
        "--topic", "Nano Banana 2 free test",
        "--format", "short video",
        "--footage", str(clip),
        "--script", str(script),
        "--out", str(out_dir),
    ])
    assert code == 0
    text = (out_dir / "04-video.md").read_text(encoding="utf-8")
    assert "## Built" in text, text
    assert "Google's free tool" in text
    assert (out_dir / "video.mp4").exists()


def test_vo_lines_txt_auto_pickup(tmp_path):
    from scripts.video_build import resolve_vo_lines
    out_dir = tmp_path / "out"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "vo-lines.txt").write_text(
        "Line one here.\nLine two here.\nLine three here.\n",
        encoding="utf-8")
    args = _provider_args(topic="Nano Banana 2 free test",
                          format="short video", brand="generic")
    vo = resolve_vo_lines(args, out_dir)
    assert vo["error"] is None
    assert vo["source"] == "vo-lines.txt"
    assert vo["lines"] == ["Line one here.", "Line two here.",
                           "Line three here."]


def test_make_thumbnail_creates_1280x720(tmp_path):
    from PIL import Image
    from scripts.make_thumbnail import build_thumbnail
    src = tmp_path / "src.jpg"
    Image.new("RGB", (800, 600), (30, 120, 90)).save(src)
    out = tmp_path / "thumbnail.jpg"
    res = build_thumbnail(src, "5 EDITS TESTED", out)
    assert res["ok"], res
    assert res["text"] == "5 EDITS TESTED"
    im = Image.open(out)
    assert im.size == (1280, 720) and im.format == "JPEG"


def test_make_thumbnail_truncates_text_to_3_words(tmp_path):
    from PIL import Image
    from scripts.make_thumbnail import build_thumbnail
    src = tmp_path / "src.jpg"
    Image.new("RGB", (640, 360), (10, 10, 10)).save(src)
    out = tmp_path / "thumbnail.jpg"
    res = build_thumbnail(src, "one two three four five", out)
    assert res["ok"], res
    assert res["text"] == "ONE TWO THREE"
    assert "first 3" in res["note"]


def test_stage_visual_records_thumbnail_when_still_exists(tmp_path):
    from PIL import Image
    from src.workers.base import MockLLM
    from scripts.creator_os_run import stage_visual
    import argparse
    out_dir = tmp_path / "out"
    stills = out_dir / "video_work" / "stills"
    stills.mkdir(parents=True)
    Image.new("RGB", (1080, 1920), (40, 90, 140)).save(stills / "scene1.jpg")
    args = argparse.Namespace(topic="Nano Banana 2 free test",
                              format="short video", title="", thumb="",
                              brand="generic", footage="")
    stage_visual(args, out_dir, MockLLM())
    text = (out_dir / "03-visual-package.md").read_text(encoding="utf-8")
    assert "thumbnail.jpg" in text
    assert "NANO BANANA 2" in text  # thumb = first 3 words of the title
    thumb = Image.open(out_dir / "thumbnail.jpg")
    assert thumb.size == (1280, 720)


def test_stage_visual_no_visual_records_honest_note(tmp_path):
    from src.workers.base import MockLLM
    from scripts.creator_os_run import stage_visual
    import argparse
    out_dir = tmp_path / "out"
    out_dir.mkdir(parents=True, exist_ok=True)
    args = argparse.Namespace(topic="Nano Banana 2 free test",
                              format="short video", title="", thumb="",
                              brand="generic", footage="")
    stage_visual(args, out_dir, MockLLM())
    text = (out_dir / "03-visual-package.md").read_text(encoding="utf-8")
    assert "Not built" in text
    assert "no thumbnail built" in text
    assert not (out_dir / "thumbnail.jpg").exists()


def test_provider_routing_flags_and_env(monkeypatch):
    cfg, errors = vp.resolve(_provider_args(video_provider="local"))
    assert errors == []
    assert cfg.provider == "local"
    monkeypatch.setenv("VIDEO_PROVIDER", "api")
    cfg_env, errors = vp.resolve(_provider_args())
    assert errors == []
    assert cfg_env.provider == "api"
    # flag wins over env
    cfg, errors = vp.resolve(_provider_args(video_provider="stills"))
    assert cfg.provider == "stills"
    # footage wins when given, whatever the config says
    assert vp.resolve_provider(_provider_args(footage="clip.mp4"),
                               cfg) == "footage"
    assert vp.resolve_provider(_provider_args(), cfg_env) == "api"
    # with no env var and no flag, the repo config (auto) resolves
    # to the stills default
    monkeypatch.delenv("VIDEO_PROVIDER")
    cfg2, _ = vp.resolve(_provider_args())
    assert vp.resolve_provider(_provider_args(), cfg2) == "stills"


def test_provider_config_file_loads(tmp_path):
    cfg_file = tmp_path / "video_providers.yaml"
    cfg_file.write_text(
        "provider: local\n"
        "fallback: stills\n"
        "local:\n"
        "  engine: custom\n"
        "  command: python3 gen.py --out \"{output}\"\n"
        "  timeout: 300\n"
        "api:\n"
        "  model: openai-sora-2-pro-text-to-video\n",
        encoding="utf-8")
    cfg = vp.load_config(cfg_file)
    assert cfg.provider == "local"
    assert cfg.fallback == "stills"
    assert cfg.local_engine == "custom"
    assert "{output}" in cfg.local_cmd
    assert cfg.local_timeout == 300
    assert cfg.api_model == "openai-sora-2-pro-text-to-video"


def test_local_provider_mock_command(tmp_path):
    # Fake local generator: a tiny script that writes a real testsrc
    # clip to {output}. Exercises the adapter wiring, no GPU needed.
    script = tmp_path / "fake_gen.py"
    script.write_text(
        "import argparse, subprocess, sys\n"
        "ap = argparse.ArgumentParser()\n"
        "ap.add_argument('--out', required=True)\n"
        "ap.add_argument('--prompt', default='')\n"
        "a = ap.parse_args()\n"
        "p = subprocess.run(['ffmpeg', '-y', '-f', 'lavfi', '-i',\n"
        "    'testsrc=duration=6:size=640x360:rate=30', '-c:v',\n"
        "    'libx264', '-pix_fmt', 'yuv420p', a.out],\n"
        "    capture_output=True, text=True, timeout=120)\n"
        "sys.exit(p.returncode)\n",
        encoding="utf-8")
    cfg = vp.ProviderConfig(
        provider="local", local_engine="custom",
        local_cmd=f"{sys.executable} {script} --prompt \"{{prompt}}\" "
                  f"--out \"{{output}}\"",
        local_timeout=120)
    provider = vp.LocalProvider(cfg,
                                gpu_probe=lambda: (True, "fake GPU"))
    result = provider.generate(_provider_ctx(tmp_path))
    assert result["cut_path"] is not None, result
    assert Path(result["cut_path"]).exists()
    assert all(r["ok"] for r in result["provider_scenes"])
    assert result["scene_dur"] == 5.0
    assert result["used"] == 15.0
    assert "local video" in result["source"]


def test_local_provider_no_gpu_fails_honestly(tmp_path):
    cfg = vp.ProviderConfig(provider="local", local_engine="wangp",
                            local_wangp_dir=str(tmp_path))
    provider = vp.LocalProvider(
        cfg, gpu_probe=lambda: (False, "nvidia-smi not found"))
    result = provider.generate(_provider_ctx(tmp_path))
    assert result["cut_path"] is None
    assert "GPU" in result["reason"]
    assert any("GPU" in m for m in result["missing"])


def test_local_provider_no_command_fails_honestly(tmp_path):
    cfg = vp.ProviderConfig(provider="local", local_engine="framepack")
    provider = vp.LocalProvider(
        cfg, gpu_probe=lambda: (True, "fake GPU"))
    result = provider.generate(_provider_ctx(tmp_path))
    assert result["cut_path"] is None
    assert "no command configured" in result["reason"]
    assert "UNVERIFIED" in " ".join(result["missing"])


def test_local_command_template_braces_fail_honestly(tmp_path):
    # A literal {brace} in the user's command (e.g. a JSON body)
    # used to crash str.format and break the "never raises" rule.
    # Now it is recorded per scene instead.
    cfg = vp.ProviderConfig(
        provider="local", local_engine="custom",
        local_cmd="python3 -c \"print({\\\"a\\\": 1})\" "
                  "--out \"{output}\"",
        local_timeout=60)
    provider = vp.LocalProvider(
        cfg, gpu_probe=lambda: (True, "fake GPU"))
    result = provider.generate(_provider_ctx(tmp_path))
    assert result["cut_path"] is None
    assert result["provider_scenes"], result
    assert all(not r["ok"] for r in result["provider_scenes"])
    assert all("did not parse" in r["note"]
               for r in result["provider_scenes"])


def test_video_dry_run_describes_without_executing(tmp_path):
    # A command that would write a marker file if executed: the
    # dry run must print it and never run it.
    marker = tmp_path / "SHOULD_NOT_EXIST.txt"
    cfg = vp.ProviderConfig(
        provider="local", local_engine="custom",
        local_cmd=f"{sys.executable} -c "
                  f"\"open('{marker}', 'w').write('x')\" "
                  f"--out \"{{output}}\"",
        local_timeout=60)
    args = _provider_args(video_provider="local")
    lines = vp.describe_plan(args, cfg, _provider_ctx(tmp_path))
    blob = "\n".join(lines)
    assert "provider: local" in blob
    assert "local_scene1.mp4" in blob
    assert not marker.exists()
    # Wangp with nothing configured: dry run names the missing
    # setup instead of running anything.
    cfg2 = vp.ProviderConfig(provider="local", local_engine="wangp")
    lines2 = vp.describe_plan(args, cfg2, _provider_ctx(tmp_path))
    blob2 = "\n".join(lines2)
    assert "GPU: NOT FOUND" in blob2
    assert "MISSING:" in blob2


def test_video_dry_run_runner_builds_no_video(tmp_path):
    out_dir = tmp_path / "out"
    code = run_pipeline([
        "--topic", "Nano Banana 2 free test",
        "--format", "short video",
        "--video-provider", "local",
        "--video-dry-run",
        "--out", str(out_dir),
    ])
    assert code == 0
    assert not (out_dir / "video.mp4").exists()
    text = (out_dir / "04-video.md").read_text(encoding="utf-8")
    assert "Dry run" in text
    assert "nothing was executed" in text


def test_resolve_provider_selection():
    cfg_local, errors = vp.resolve(
        _provider_args(video_provider="local"))
    assert errors == []
    assert vp.resolve_provider(
        _provider_args(video_provider="local"), cfg_local) == "local"
    cfg_api, errors = vp.resolve(_provider_args(video_provider="api"))
    assert errors == []
    assert vp.resolve_provider(
        _provider_args(video_provider="api"), cfg_api) == "api"
    cfg_auto, _ = vp.resolve(_provider_args())
    assert vp.resolve_provider(_provider_args(), cfg_auto) == "stills"


def test_api_provider_missing_key_fails_honestly(tmp_path, monkeypatch):
    monkeypatch.delenv("VIDEO_API_KEY", raising=False)
    cfg = vp.ProviderConfig(provider="api")
    result = vp.ApiProvider(cfg).generate(_provider_ctx(tmp_path))
    assert result["cut_path"] is None
    assert "VIDEO_API_KEY" in result["reason"] or any(
        "VIDEO_API_KEY" in m for m in result["missing"])


def test_api_provider_mock_server(tmp_path, monkeypatch):
    # Fake Muapi-like server: submit -> request_id, poll -> completed
    # with a clip URL, clip served from disk. No real API, no key.
    import http.server
    import json as _json
    import threading

    clip = tmp_path / "server-clip.mp4"
    proc = subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i",
         "testsrc=duration=6:size=640x360:rate=30",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", str(clip)],
        capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0, proc.stderr
    clip_bytes = clip.read_bytes()
    seen = {"bodies": [], "keys": [], "polls": 0}

    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _send_json(self, obj):
            data = _json.dumps(obj).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_POST(self):
            length = int(self.headers.get("Content-Length", 0))
            seen["bodies"].append(self.rfile.read(length))
            seen["keys"].append(self.headers.get("x-api-key"))
            self._send_json({"request_id": "req-123"})

        def do_GET(self):
            if self.path.endswith("/result"):
                seen["polls"] += 1
                if seen["polls"] % 2 == 1:
                    self._send_json({"status": "processing"})
                else:
                    port = self.server.server_address[1]
                    self._send_json({
                        "status": "completed",
                        "outputs": [{"url":
                                     f"http://127.0.0.1:{port}/clip.mp4"}]})
            elif self.path.endswith("/clip.mp4"):
                self.send_response(200)
                self.send_header("Content-Type", "video/mp4")
                self.send_header("Content-Length", str(len(clip_bytes)))
                self.end_headers()
                self.wfile.write(clip_bytes)
            else:
                self.send_response(404)
                self.end_headers()

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        port = server.server_address[1]
        monkeypatch.setenv("VIDEO_API_KEY", "fake-key-123")
        cfg = vp.ProviderConfig(
            provider="api",
            api_url=f"http://127.0.0.1:{port}/submit",
            api_poll_url=f"http://127.0.0.1:{port}/predictions/"
                         "{request_id}/result",
            api_poll_interval=1, api_timeout=60)
        result = vp.ApiProvider(cfg).generate(_provider_ctx(tmp_path))
    finally:
        server.shutdown()
        server.server_close()
    assert result["cut_path"] is not None, result
    assert all(r["ok"] for r in result["provider_scenes"])
    assert seen["keys"] == ["fake-key-123"] * 3
    bodies = [_json.loads(b) for b in seen["bodies"]]
    assert len(bodies) == 3
    assert all("prompt" in b for b in bodies)
    assert all(b.get("aspect_ratio") == "9:16" for b in bodies)


def test_pipeline_local_provider_fails_honestly(tmp_path):
    out_dir = tmp_path / "out"
    code = run_pipeline([
        "--topic", "AI receptionist for plumbers",
        "--format", "short video",
        "--video-provider", "local",
        "--out", str(out_dir),
    ])
    assert code == 0
    text = (out_dir / "04-video.md").read_text(encoding="utf-8")
    assert "No video was built" in text
    assert "GPU" in text
    assert "local" in text.lower()
    assert not (out_dir / "video.mp4").exists()


def test_pipeline_bad_provider_in_config(tmp_path):
    cfg_file = tmp_path / "video_providers.yaml"
    cfg_file.write_text("provider: bogus\n", encoding="utf-8")
    out_dir = tmp_path / "out"
    code = run_pipeline([
        "--topic", "AI receptionist for plumbers",
        "--format", "short video",
        "--video-config", str(cfg_file),
        "--no-gen-visuals",
        "--out", str(out_dir),
    ])
    assert code == 0
    text = (out_dir / "04-video.md").read_text(encoding="utf-8")
    assert "No video was built" in text
    assert "unknown video provider 'bogus'" in text
    assert "configuration error" in text
    assert not (out_dir / "video.mp4").exists()


# ---------------------------------------------------------------------------
# The 4 new pieces (2026-11-10): niche finder, concept score,
# auto-upload, closed loop. Mock/dry-run only - no network, no
# real upload, no keys.
# ---------------------------------------------------------------------------
def _run_tool(tool: Path, args: list[str], **kw):
    return subprocess.run(
        [sys.executable, str(tool), *args],
        capture_output=True, text=True, timeout=60, cwd=str(ROOT), **kw)


def test_niche_score_mock_samples():
    import json
    proc = _run_tool(ROOT / "tools" / "niche_score.py", ["--json"])
    assert proc.returncode == 0, proc.stderr
    data = json.loads(proc.stdout)
    assert data["sample"] is True
    assert data["weights"] == {"demand": 0.3, "competition_gap": 0.3,
                               "monetization": 0.25, "fresher_fit": 0.15}
    rows = data["ranked"]
    assert len(rows) == 5
    totals = [r["total"] for r in rows]
    assert totals == sorted(totals, reverse=True)
    assert all(1 <= t <= 10 for t in totals)
    assert data["picked"] == rows[0]["name"]
    # competition gap is 100 - competition (lower competition wins)
    first = rows[0]
    assert first["parts"]["competition_gap"] == (
        100 - {"AI tools tutorials for beginners": 62,
               "Small business bookkeeping basics": 40,
               "Plumbing how-to for homeowners": 55,
               "Budget home cooking": 80,
               "Beginner guitar in 30 days": 74}[first["name"]])


def test_niche_score_with_input_file(tmp_path):
    import json
    niches = tmp_path / "niches.json"
    niches.write_text(json.dumps([
        {"name": "Perfect", "demand": 100, "competition": 0,
         "monetization": 100, "fresher_fit": 100},
        {"name": "Average", "demand": 50, "competition": 50,
         "monetization": 50, "fresher_fit": 50},
    ]), encoding="utf-8")
    proc = _run_tool(ROOT / "tools" / "niche_score.py",
                     ["--niches", str(niches), "--json"])
    assert proc.returncode == 0, proc.stderr
    data = json.loads(proc.stdout)
    assert data["sample"] is False
    assert data["ranked"][0]["name"] == "Perfect"
    assert data["ranked"][0]["total"] == 10.0
    assert data["ranked"][1]["total"] == 5.0
    assert data["picked"] == "Perfect"


def test_niche_score_rejects_bad_signals(tmp_path):
    import json
    niches = tmp_path / "niches.json"
    niches.write_text(json.dumps([
        {"name": "Bad", "demand": 50, "competition": 150,
         "monetization": 50, "fresher_fit": 50},
    ]), encoding="utf-8")
    proc = _run_tool(ROOT / "tools" / "niche_score.py",
                     ["--niches", str(niches), "--json"])
    assert proc.returncode == 2
    assert "outside 0-100" in proc.stderr


def test_concept_score_mock_templates():
    import json
    proc = _run_tool(ROOT / "tools" / "concept_score.py",
                     ["--topic", "AI receptionist for plumbers", "--json"])
    assert proc.returncode == 0, proc.stderr
    data = json.loads(proc.stdout)
    assert data["sample"] is True
    assert data["weights"] == {"hook_strength": 0.4, "trend_fit": 0.25,
                               "competition_gap": 0.2,
                               "fresher_fit": 0.15}
    rows = data["ranked"]
    assert len(rows) == 5
    assert rows[0]["total"] >= 7, "picked concept must be STRONG (7+)"
    assert data["picked"] == rows[0]["concept"]
    assert rows[0]["band"] == "STRONG"
    assert all("hook" in r for r in rows)


def test_concept_score_with_input_file(tmp_path):
    import json
    concepts = tmp_path / "concepts.json"
    concepts.write_text(json.dumps([
        {"concept": "Perfect", "hook": "Watch this.",
         "hook_strength": 100, "trend_fit": 100,
         "competition_gap": 100, "fresher_fit": 100},
        {"concept": "Weak", "hook": "Hello.",
         "hook_strength": 10, "trend_fit": 10,
         "competition_gap": 10, "fresher_fit": 10},
    ]), encoding="utf-8")
    proc = _run_tool(ROOT / "tools" / "concept_score.py",
                     ["--concepts", str(concepts), "--json"])
    assert proc.returncode == 0, proc.stderr
    data = json.loads(proc.stdout)
    assert data["ranked"][0]["total"] == 10.0
    assert data["ranked"][1]["total"] == 1.0
    assert data["picked"] == "Perfect"


def test_upload_dry_run_writes_plan_no_network(tmp_path):
    import json
    video = tmp_path / "video.mp4"
    video.write_bytes(b"fake-video-bytes")
    proc = _run_tool(ROOT / "scripts" / "upload_youtube.py",
                     ["--video", str(video), "--title", "Test title",
                      "--description", "d", "--tags", "a", "b",
                      "--dry-run", "--json"])
    assert proc.returncode == 0, proc.stderr
    plan = json.loads(proc.stdout)
    assert plan["dry_run"] is True
    assert plan["title"] == "Test title"
    assert plan["privacy"] == "private"
    assert plan["size_bytes"] == len(b"fake-video-bytes")
    assert "nothing was sent" in plan["note"].lower()


def test_upload_missing_credentials_fails_honestly(tmp_path, monkeypatch):
    from scripts.upload_youtube import UploadError, resolve_credentials
    for var in ("YOUTUBE_CLIENT_SECRETS_FILE", "YOUTUBE_TOKEN_FILE"):
        monkeypatch.delenv(var, raising=False)
    try:
        resolve_credentials(None, None)
    except UploadError as exc:
        assert "YOUTUBE_CLIENT_SECRETS_FILE" in str(exc)
        assert "YOUTUBE_TOKEN_FILE" in str(exc)
    else:
        raise AssertionError("expected UploadError for missing credentials")
    # CLI path: enabled but no credentials -> exit 1, names the gap.
    video = tmp_path / "video.mp4"
    video.write_bytes(b"x")
    env = {"YOUTUBE_UPLOAD_ENABLED": "1",
           "PATH": "/usr/bin:/bin", "HOME": str(tmp_path)}
    proc = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "upload_youtube.py"),
         "--video", str(video), "--title", "t"],
        capture_output=True, text=True, timeout=60, cwd=str(ROOT),
        env=env)
    assert proc.returncode == 1
    assert "missing upload credentials" in proc.stderr


def test_upload_stage_off_by_default(tmp_path, monkeypatch):
    monkeypatch.delenv("YOUTUBE_UPLOAD_ENABLED", raising=False)
    out_dir = _run_mock_pipeline(tmp_path)
    text = (out_dir / "09-upload.md").read_text(encoding="utf-8")
    assert "NOT ENABLED" in text
    assert "nothing was uploaded" in text
    assert "YOUTUBE_UPLOAD_ENABLED=1" in text


def test_upload_stage_flag_without_env_stays_off(tmp_path, monkeypatch):
    monkeypatch.delenv("YOUTUBE_UPLOAD_ENABLED", raising=False)
    out_dir = tmp_path / "out"
    code = run_pipeline([
        "--topic", "AI receptionist for plumbers",
        "--format", "short video",
        "--niche", "US home-service owners",
        "--no-gen-visuals",
        "--auto-upload",
        "--out", str(out_dir),
    ])
    assert code == 0
    text = (out_dir / "09-upload.md").read_text(encoding="utf-8")
    assert "NOT ENABLED" in text
    assert "nothing was uploaded" in text


def test_loop_next_no_data_honest(tmp_path):
    from scripts.loop_next import build_plan
    out_dir = tmp_path / "run"
    out_dir.mkdir()
    brief = build_plan(out_dir, None, None)
    assert brief["status"] == "no-data"
    text = (out_dir / "10-next-plan.md").read_text(encoding="utf-8")
    assert "No performance data yet" in text
    assert "nothing was invented" in text.lower()
    assert (out_dir / "next-brief.json").exists()


def test_loop_next_with_report(tmp_path):
    import json
    from scripts.loop_next import build_plan
    prev = tmp_path / "prev-run"
    prev.mkdir()
    (prev / "08-report.md").write_text(
        "# Stage 8 — Report\n\n- Points read: 40\n"
        "- Start → end: 100% → 32%\n"
        "- Hook leak: 35% lost in the opening\n"
        "- Cliff: -12% at 0:42\n",
        encoding="utf-8")
    out_dir = tmp_path / "new-run"
    out_dir.mkdir()
    brief = build_plan(out_dir, prev, None)
    assert brief["status"] == "ok"
    assert any("Hook leaks 35" in c for c in brief["change"])
    assert any("0:42" in c for c in brief["change"])
    assert brief["numbers_used"]["hook_leak"] == 35.0
    text = (out_dir / "10-next-plan.md").read_text(encoding="utf-8")
    assert "Hook leaks 35%" in text
    saved = json.loads((out_dir / "next-brief.json").read_text())
    assert saved["status"] == "ok"
    assert saved["source_run"] == str(prev)


def test_pipeline_find_niche_end_to_end(tmp_path):
    out_dir = tmp_path / "out"
    code = run_pipeline([
        "--find-niche",
        "--format", "short video",
        "--no-gen-visuals",
        "--out", str(out_dir),
    ])
    assert code == 0
    for name in STAGE_FILES:
        path = out_dir / name
        assert path.exists(), f"missing stage file: {name}"
        assert path.stat().st_size > 200, f"stage file too small: {name}"
    niche = (out_dir / "00-niche.md").read_text(encoding="utf-8")
    assert "Picked niche" in niche
    assert "AI tools tutorials for beginners" in niche
    plan = (out_dir / "00-plan.md").read_text(encoding="utf-8")
    assert "AI tools tutorials for beginners" in plan
    concept = (out_dir / "02-concept-score.md").read_text(encoding="utf-8")
    assert "Picked concept" in concept
    script = (out_dir / "02-script.md").read_text(encoding="utf-8")
    assert "Concept picked" in script
    assert "Verdict" in script
    upload = (out_dir / "09-upload.md").read_text(encoding="utf-8")
    assert "NOT ENABLED" in upload
    loop = (out_dir / "10-next-plan.md").read_text(encoding="utf-8")
    assert "No performance data yet" in loop
    import json
    brief = json.loads((out_dir / "next-brief.json").read_text())
    assert brief["status"] == "no-data"
    assert not (out_dir / "video.mp4").exists()


def test_plan_reads_next_brief(tmp_path):
    import json
    runs = tmp_path / "runs"
    prev = runs / "prev-run"
    prev.mkdir(parents=True)
    (prev / "next-brief.json").write_text(json.dumps({
        "status": "ok", "date": "2026-11-10",
        "source_run": str(prev),
        "keep": ["Ending holds at 55% retention"],
        "change": ["Hook leaks 35% - rewrite the hook"],
        "next_topic_angle": "Open on the payoff.",
    }), encoding="utf-8")
    out_dir = runs / "new-run"
    code = run_pipeline([
        "--topic", "AI receptionist for plumbers",
        "--format", "short video",
        "--no-gen-visuals",
        "--out", str(out_dir),
    ])
    assert code == 0
    plan = (out_dir / "00-plan.md").read_text(encoding="utf-8")
    assert "Carried over from the last video" in plan
    assert "Hook leaks 35%" in plan
    assert "Ending holds at 55%" in plan


def _main() -> int:
    tests = [(n, f) for n, f in sorted(globals().items())
             if n.startswith("test_") and callable(f)]
    import tempfile
    passed = 0
    for name, fn in tests:
        try:
            if "tmp_path" in fn.__code__.co_varnames:
                with tempfile.TemporaryDirectory() as td:
                    fn(Path(td))
            else:
                fn()
            passed += 1
            print("PASS", name)
        except Exception as exc:  # noqa: BLE001
            print("FAIL", name, type(exc).__name__, str(exc)[:200])
    print(f"{passed}/{len(tests)} combined tests passed")
    return 0 if passed == len(tests) else 1


if __name__ == "__main__":
    raise SystemExit(_main())
