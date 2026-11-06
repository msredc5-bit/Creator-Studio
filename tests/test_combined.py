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
    "00-plan.md",
    "01-research.md",
    "02-script.md",
    "03-visual-package.md",
    "04-video.md",
    "05-edit.md",
    "06-caption-seo.md",
    "07-publish-prep.md",
    "08-report.md",
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
    # The two documented exceptions: scripts/gen_visuals.py calls the
    # free Pollinations image service (no key), and
    # scripts/video_providers.py calls a paid video API only when the
    # user configures the api provider with their own key. Everything
    # else in src/, scripts/, and tests/ makes no network calls.
    allowed = {ROOT / "scripts" / "gen_visuals.py",
               ROOT / "scripts" / "video_providers.py"}
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
    """No .py file may call the network except the two documented
    ones: gen_visuals.py (free Pollinations images, no key) and
    video_providers.py (paid video API, only when the user configures
    the api provider with their own key). (Naming the services in
    labels/docstrings is fine — the call itself lives only in those
    two files.)"""
    allowed = {ROOT / "scripts" / "gen_visuals.py",
               ROOT / "scripts" / "video_providers.py"}
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
