"""Creator OS combined tests — offline, mock mode only.

Run with pytest (preferred):
  python3 -m pytest tests/ -q

Or directly (stdlib fallback, same checks):
  python3 tests/test_combined.py

$0 spend. No network, no keys, nothing publishes.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.creator_workers import PublishPrep, ROSTER  # noqa: E402
from src.workers.base import MockLLM, Task  # noqa: E402
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
    out_dir = tmp_path / "out"
    code = run_pipeline([
        "--topic", "AI receptionist for plumbers",
        "--format", "short video",
        "--niche", "US home-service owners",
        "--audience", "plumbers who miss calls on the job",
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


def test_no_network_code_in_src_and_scripts():
    banned = ["urllib", "requests", "http.client", "socket", "httpx",
              "aiohttp"]
    for base in (ROOT / "src", ROOT / "scripts", ROOT / "tests"):
        for path in base.rglob("*.py"):
            if path.name == Path(__file__).name:
                continue  # this test file names the banned words itself
            text = path.read_text(encoding="utf-8")
            for word in banned:
                assert word not in text, f"{path}: network token '{word}'"


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
