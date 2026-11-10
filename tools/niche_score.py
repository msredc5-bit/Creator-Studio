#!/usr/bin/env python3
"""niche_score.py - score candidate YouTube niches for a fresher, 1-10.

Four axes, each scored 0-100 from the signals the user supplies, then
combined into one 1-10 total:

    demand         30%  - do people search/watch this? (signal: demand)
    competition gap 30% - room to enter = 100 - competition
                        (signal: competition; LOWER competition scores
                        HIGHER, because a fresher cannot out-shout an
                        entrenched niche)
    monetization   25%  - can it pay? (signal: monetization)
    fresher-fit    15%  - can a beginner start with $0 + a phone/PC?
                        (signal: fresher_fit)

    total = 0.30*demand + 0.30*(100-competition)
          + 0.25*monetization + 0.15*fresher_fit, / 10, 1 decimal.

    python3 tools/niche_score.py                      # mock samples
    python3 tools/niche_score.py --niches niches.json # your own research
    python3 tools/niche_score.py --json               # machine-readable

The --niches file is a JSON list:
    [{"name": "...", "demand": 0-100, "competition": 0-100,
      "monetization": 0-100, "fresher_fit": 0-100, "notes": "..."}]

WHAT THIS CAN AND CANNOT TELL YOU. This tool scores the signals you
feed it - it does NOT fetch the web, search YouTube, or measure real
demand. The built-in mock samples are fixed, labelled SAMPLES, and
exist only so the pipeline runs end to end offline. A high score is
a reason to research that niche for real, never proof the niche is
good. Collect real signals first (search interest, how many channels
already serve it, what they earn, what gear it needs) and re-run
with --niches. Scores are never a promise of views or income.
"""
from __future__ import annotations

import json
import sys

WEIGHTS = {
    "demand": 0.30,
    "competition_gap": 0.30,
    "monetization": 0.25,
    "fresher_fit": 0.15,
}

# Fixed mock samples, deterministic, $0, no network. Labelled SAMPLE
# everywhere they appear - they are placeholders for real research,
# not findings.
SAMPLE_NICHES = [
    {"name": "AI tools tutorials for beginners",
     "demand": 78, "competition": 62, "monetization": 74,
     "fresher_fit": 88,
     "notes": "SAMPLE - screen recordings, no face needed, free tools."},
    {"name": "Plumbing how-to for homeowners",
     "demand": 70, "competition": 55, "monetization": 68,
     "fresher_fit": 82,
     "notes": "SAMPLE - film real jobs with a phone; needs a trade to show."},
    {"name": "Budget home cooking",
     "demand": 84, "competition": 80, "monetization": 60,
     "fresher_fit": 90,
     "notes": "SAMPLE - huge demand, crowded; needs a sharp angle."},
    {"name": "Beginner guitar in 30 days",
     "demand": 66, "competition": 74, "monetization": 58,
     "fresher_fit": 76,
     "notes": "SAMPLE - needs the creator to actually play."},
    {"name": "Small business bookkeeping basics",
     "demand": 58, "competition": 40, "monetization": 80,
     "fresher_fit": 64,
     "notes": "SAMPLE - quiet niche, strong monetization, slower growth."},
]

REQUIRED_SIGNALS = ("demand", "competition", "monetization", "fresher_fit")


def validate(niche: dict) -> list[str]:
    """Return a list of problems with one candidate, empty if fine."""
    problems = []
    if not str(niche.get("name", "")).strip():
        problems.append("missing name")
    for key in REQUIRED_SIGNALS:
        value = niche.get(key)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            problems.append(f"{key}: not a number (got {value!r})")
        elif not 0 <= value <= 100:
            problems.append(f"{key}: {value} is outside 0-100")
    return problems


def score(niche: dict) -> dict:
    """Score one candidate. Raises ValueError on bad signals."""
    problems = validate(niche)
    if problems:
        raise ValueError(
            f"niche {niche.get('name', '?')!r}: " + "; ".join(problems))
    gap = 100 - niche["competition"]
    parts = {
        "demand": niche["demand"],
        "competition_gap": gap,
        "monetization": niche["monetization"],
        "fresher_fit": niche["fresher_fit"],
    }
    total = round(sum(parts[k] * w for k, w in WEIGHTS.items()) / 10, 1)
    return {
        "name": niche["name"],
        "parts": parts,
        "total": total,
        "band": band(total),
        "notes": niche.get("notes", ""),
    }


def band(total: float) -> str:
    return "STRONG" if total >= 7 else "WORKABLE" if total >= 5 else "WEAK"


def rank(niches: list[dict]) -> list[dict]:
    """Score every candidate, highest total first. Raises on bad input."""
    if not niches:
        raise ValueError("no candidate niches supplied")
    scored = [score(n) for n in niches]
    scored.sort(key=lambda r: (-r["total"], r["name"]))
    return scored


def report(rows: list[dict], sample: bool) -> None:
    if sample:
        print("SAMPLE niches (mock mode - replace with real research):")
    for i, row in enumerate(rows, 1):
        parts = row["parts"]
        print(f"\n  {i}. {row['name']}  -  {row['total']}/10  {row['band']}")
        print(f"     demand {parts['demand']:3d}  competition-gap "
              f"{parts['competition_gap']:3d}  monetization "
              f"{parts['monetization']:3d}  fresher-fit "
              f"{parts['fresher_fit']:3d}")
        if row["notes"]:
            print(f"     {row['notes']}")
    print(f"\n  picked: {rows[0]['name']}  ({rows[0]['total']}/10, "
          f"{rows[0]['band']})")
    print("  A high score is a reason to research it for real, "
          "never proof it will work.")


def load_niches(path: str) -> list[dict]:
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except FileNotFoundError:
        print(f"niches file not found: {path}", file=sys.stderr)
        sys.exit(2)
    except json.JSONDecodeError as exc:
        print(f"niches file is not valid JSON: {path}: {exc}",
              file=sys.stderr)
        sys.exit(2)
    if not isinstance(data, list):
        print(f"niches file must hold a JSON list, got "
              f"{type(data).__name__}: {path}", file=sys.stderr)
        sys.exit(2)
    return data


def main(argv=None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    as_json = "--json" in args
    args = [a for a in args if a != "--json"]
    sample = True
    niches = SAMPLE_NICHES
    if "--niches" in args:
        idx = args.index("--niches")
        if idx + 1 >= len(args):
            print("--niches needs a file path", file=sys.stderr)
            return 2
        niches = load_niches(args[idx + 1])
        sample = False
    try:
        rows = rank(niches)
    except ValueError as exc:
        print(f"niche_score: {exc}", file=sys.stderr)
        return 2
    if as_json:
        print(json.dumps(
            {"sample": sample, "weights": WEIGHTS, "ranked": rows,
             "picked": rows[0]["name"]}, indent=1))
        return 0
    report(rows, sample)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
