"""setup.py tests — offline, temp dirs only, no network, $0.

Run with pytest (preferred):
  python3 -m pytest tests/test_setup.py -q

Or directly (stdlib fallback, same checks):
  python3 tests/test_setup.py
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SETUP = ROOT / "setup.py"

# creator-studio + the 12 yt-* skills in youtube-skills/.
EXPECTED_SKILLS = sorted(
    ["creator-studio"] +
    [p.name for p in (ROOT / "youtube-skills").iterdir()
     if p.is_dir() and (p / "SKILL.md").exists()])


def _run(*args) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SETUP), *args],
        capture_output=True, text=True, timeout=60, cwd=str(ROOT))


def test_check_dry_run_changes_nothing(tmp_path: Path):
    target = tmp_path / "skills"
    proc = _run("--check", "--target", str(target))
    assert proc.returncode == 0, proc.stderr
    assert "dry run" in proc.stdout.lower()
    assert not target.exists(), "a dry run must not create anything"
    for name in EXPECTED_SKILLS:
        assert name in proc.stdout, f"{name} missing from --check plan"


def test_install_into_temp_target(tmp_path: Path):
    target = tmp_path / "skills"
    proc = _run("--target", str(target))
    assert proc.returncode == 0, proc.stderr
    assert "Installed" in proc.stdout
    for name in EXPECTED_SKILLS:
        skill = target / name / "SKILL.md"
        assert skill.is_file(), f"{name}/SKILL.md did not land"
        assert skill.stat().st_size > 0
    # The entry skill is the one file an agent needs to run it all.
    entry = (target / "creator-studio" / "SKILL.md").read_text(
        encoding="utf-8")
    assert "creator_os_run.py" in entry
    assert "upload it" in entry


def test_second_install_skips_without_force(tmp_path: Path):
    target = tmp_path / "skills"
    assert _run("--target", str(target)).returncode == 0
    marker = target / "creator-studio" / "SKILL.md"
    marker.write_text(marker.read_text(encoding="utf-8") + "\n# MINE\n",
                      encoding="utf-8")
    proc = _run("--target", str(target))
    assert proc.returncode == 0, proc.stderr
    assert "Skipped" in proc.stdout
    assert "# MINE" in marker.read_text(encoding="utf-8"), (
        "a second install without --force must never overwrite")
    proc = _run("--target", str(target), "--force")
    assert proc.returncode == 0, proc.stderr
    assert "Overwrote" in proc.stdout
    assert "# MINE" not in marker.read_text(encoding="utf-8"), (
        "--force must overwrite")


if __name__ == "__main__":
    import tempfile

    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        test_check_dry_run_changes_nothing(tmp / "a")
        test_install_into_temp_target(tmp / "b")
        test_second_install_skips_without_force(tmp / "c")
    print("test_setup.py: all checks passed")
