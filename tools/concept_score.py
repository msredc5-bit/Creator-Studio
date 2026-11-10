#!/usr/bin/env python3
"""concept_score.py - score video concepts BEFORE filming, 1-10.

Four axes, each 0-100 from the signals the user supplies, then
combined into one 1-10 total:

    hook strength    40%  - does it open on a payoff in the first
                          seconds? (signal: hook_strength)
    trend-fit        25%  - does the idea stand on its own inside
                          what is working right now?
                          (signal: trend_fit)
    competition gap  20%  - is there room this idea fills that the
                          outliers do not? (signal: competition_gap)
    fresher-fit      15%  - can a beginner make it with $0 + a
                          phone/PC and end on a clear next step?
                          (signal: fresher_fit)

    total = 0.40*hook_strength + 0.25*trend_fit
          + 0.20*competition_gap + 0.15*fresher_fit, / 10, 1 decimal.

    python3 tools/concept_score.py --topic "AI receptionist"
    python3 tools/concept_score.py --concepts concepts.json
    python3 tools/concept_score.py --topic "..." --json

The --concepts file is a JSON list:
    [{"concept": "...", "hook": "first line, spoken",
      "hook_strength": 0-100, "trend_fit": 0-100,
      "competition_gap": 0-100, "fresher_fit": 0-100}]

With --topic and no file, five deterministic template concepts are
scored from the topic (mock mode, labelled SAMPLE - they are angles
to research, not findings).

WEIGHTS, ADAPTED FROM THE VIRAL-CLIPS SKILL. The viral-clips skill
(~/workspace/custom-skills/local-viral-clips/SKILL.md) scores
FINISHED clips 1-10 as hook 40% + standalone value 30% +
emotional energy 20% + CTA fit 10%, and only produces clips
scoring 7+. Concepts are scored BEFORE filming, so the four clip
axes map like this: hook stays hook (40%); standalone value
becomes trend-fit + competition gap (a concept must stand alone
inside the trend AND fill a gap the outliers leave, 25% + 20%);
emotional energy folds into hook strength (the hook is where the
feeling lands); CTA fit folds into fresher-fit (a beginner must be
able to end on one clear next step, 15%). Same spirit, different
moment in the pipeline - the clip scorer still judges the finished
cut afterwards.

WHAT THIS CAN AND CANNOT TELL YOU. This tool scores the signals
you feed it - it does not fetch the web or measure real trends.
A high score is a reason to write that script first, never a
promise it will go viral. Only clips scoring 7+ should be treated
as strong; below 5, rework the hook before anything else.
"""
from __future__ import annotations

import json
import sys

WEIGHTS = {
    "hook_strength": 0.40,
    "trend_fit": 0.25,
    "competition_gap": 0.20,
    "fresher_fit": 0.15,
}

REQUIRED_SIGNALS = ("hook_strength", "trend_fit", "competition_gap",
                    "fresher_fit")

# Fixed template angles, deterministic, $0, no network. Labelled
# SAMPLE everywhere they appear - angles to research, not findings.
TEMPLATE_ANGLES = [
    ("The #1 mistake", "You are making this mistake every day - "
     "and it costs you a customer each time.", 82, 70, 65, 80),
    ("The myth", "Everyone says this works. It does not - here is "
     "what actually happens.", 78, 74, 72, 76),
    ("What it costs", "This one missed call cost a business more "
     "than a month of software. Here is the maths.", 74, 62, 68, 84),
    ("Before / after", "Same business, same week - one change, and "
     "the phone stopped being a problem.", 70, 68, 60, 72),
    ("The first 24 hours", "Your first day with this set up - "
     "exactly what happens, hour by hour.", 66, 58, 74, 88),
]


def validate(concept: dict) -> list[str]:
    """Return a list of problems with one concept, empty if fine."""
    problems = []
    if not str(concept.get("concept", "")).strip():
        problems.append("missing concept")
    for key in REQUIRED_SIGNALS:
        value = concept.get(key)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            problems.append(f"{key}: not a number (got {value!r})")
        elif not 0 <= value <= 100:
            problems.append(f"{key}: {value} is outside 0-100")
    return problems


def score(concept: dict) -> dict:
    """Score one concept. Raises ValueError on bad signals."""
    problems = validate(concept)
    if problems:
        raise ValueError(
            f"concept {concept.get('concept', '?')!r}: "
            + "; ".join(problems))
    parts = {k: concept[k] for k in REQUIRED_SIGNALS}
    total = round(sum(parts[k] * w for k, w in WEIGHTS.items()) / 10, 1)
    return {
        "concept": concept["concept"],
        "hook": concept.get("hook", ""),
        "parts": parts,
        "total": total,
        "band": band(total),
    }


def band(total: float) -> str:
    return "STRONG" if total >= 7 else "WORKABLE" if total >= 5 else "WEAK"


def rank(concepts: list[dict]) -> list[dict]:
    """Score every concept, highest total first. Raises on bad input."""
    if not concepts:
        raise ValueError("no concepts supplied")
    scored = [score(c) for c in concepts]
    scored.sort(key=lambda r: (-r["total"], r["concept"]))
    return scored


def template_concepts(topic: str) -> list[dict]:
    """Five deterministic template concepts built from the topic."""
    out = []
    for name, hook, hook_s, trend, gap, fresh in TEMPLATE_ANGLES:
        out.append({
            "concept": f"{name}: {topic}",
            "hook": hook,
            "hook_strength": hook_s,
            "trend_fit": trend,
            "competition_gap": gap,
            "fresher_fit": fresh,
        })
    return out


def report(rows: list[dict], sample: bool) -> None:
    if sample:
        print("SAMPLE concepts (mock mode - research them for real "
              "before filming):")
    for i, row in enumerate(rows, 1):
        parts = row["parts"]
        print(f"\n  {i}. {row['concept']}  -  {row['total']}/10  "
              f"{row['band']}")
        if row["hook"]:
            print(f"     hook: \"{row['hook']}\"")
        print(f"     hook {parts['hook_strength']:3d}  trend-fit "
              f"{parts['trend_fit']:3d}  competition-gap "
              f"{parts['competition_gap']:3d}  fresher-fit "
              f"{parts['fresher_fit']:3d}")
    print(f"\n  picked: {rows[0]['concept']}  ({rows[0]['total']}/10, "
          f"{rows[0]['band']})")
    print("  Only 7+ counts as strong. Below 5, rework the hook "
          "before anything else.")


def load_concepts(path: str) -> list[dict]:
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except FileNotFoundError:
        print(f"concepts file not found: {path}", file=sys.stderr)
        sys.exit(2)
    except json.JSONDecodeError as exc:
        print(f"concepts file is not valid JSON: {path}: {exc}",
              file=sys.stderr)
        sys.exit(2)
    if not isinstance(data, list):
        print(f"concepts file must hold a JSON list, got "
              f"{type(data).__name__}: {path}", file=sys.stderr)
        sys.exit(2)
    return data


def main(argv=None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    as_json = "--json" in args
    args = [a for a in args if a != "--json"]
    sample = True
    concepts = None
    topic = ""
    if "--concepts" in args:
        idx = args.index("--concepts")
        if idx + 1 >= len(args):
            print("--concepts needs a file path", file=sys.stderr)
            return 2
        concepts = load_concepts(args[idx + 1])
        sample = False
    if "--topic" in args:
        idx = args.index("--topic")
        if idx + 1 >= len(args):
            print("--topic needs a value", file=sys.stderr)
            return 2
        topic = args[idx + 1]
    if concepts is None:
        if not topic:
            print("give --topic (mock template concepts) or "
                  "--concepts file.json", file=sys.stderr)
            return 2
        concepts = template_concepts(topic)
    try:
        rows = rank(concepts)
    except ValueError as exc:
        print(f"concept_score: {exc}", file=sys.stderr)
        return 2
    if as_json:
        print(json.dumps(
            {"sample": sample, "weights": WEIGHTS, "ranked": rows,
             "picked": rows[0]["concept"]}, indent=1))
        return 0
    report(rows, sample)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
