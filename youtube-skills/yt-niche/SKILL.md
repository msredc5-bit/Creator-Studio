---
name: yt-niche
description: >-
  Pick a YouTube niche a fresher can actually start in, and rank
  candidates by demand, competition gap, monetization, and
  fresher-fit. Use for "what niche should I pick", "is this niche
  too crowded", "find me a viral niche", or before planning any
  channel from zero.
---

# yt-niche

A niche is not a topic. It is a room with people in it, a door a
beginner can walk through, and a way to get paid. This skill scores
candidate niches 1-10 on four axes and picks the one to research
for real.

```bash
python3 tools/niche_score.py                    # mock samples
python3 tools/niche_score.py --niches niches.json
```

## The four axes

| Axis | Weight | What it means |
|---|---|---|
| Demand | 30% | Do people search and watch this? |
| Competition gap | 30% | Room to enter = 100 − competition. Lower competition scores higher — a fresher cannot out-shout an entrenched niche. |
| Monetization | 25% | Can it pay — products, services, sponsors, affiliates? |
| Fresher-fit | 15% | Can a beginner start with $0 + a phone/PC? |

Total is 1-10. 7+ is STRONG, 5-6.9 WORKABLE, below 5 WEAK.

## Collecting the input

The tool scores the signals you feed it — it does **not** fetch the
web or measure real demand. For each candidate, collect honestly
before scoring (0-100 each):

- **Demand:** search interest, how often the question is asked,
  views on the top videos in the niche.
- **Competition:** how many channels already serve it well, and how
  strong the top 5 are. Count channels, not videos.
- **Monetization:** what buyers already pay for in this niche
  (courses, tools, services, sponsors).
- **Fresher-fit:** gear needed, skill needed, face on camera or
  not, money needed to start.

```json
[{"name": "...", "demand": 78, "competition": 62,
  "monetization": 74, "fresher_fit": 88,
  "notes": "screen recordings, no face needed"}]
```

**Read, do not scrape.** Public listings only, never a logged-in
session, never anyone's account credentials.

## Reading the output

What to hand back: the top three with their totals and the one
reason each scored the way it did, then the picked niche — and the
honest line that a high score is a reason to research that niche
for real, never proof it will work. The picked niche becomes the
run's topic when no topic was given.

Mock samples (no `--niches` file) are fixed and labelled SAMPLE.
They exist only so the pipeline runs end to end offline.

## The gate

Nothing here publishes. This skill writes and you publish. Every
output ends in a block the user copies, and the last line of every
run is the question: **ship it, or change it?**
