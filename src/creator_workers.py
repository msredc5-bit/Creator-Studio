"""Creator Studio workers — Content Creation, Media & Entertainment.

Built on the vendored worker base in this repo
(src/workers/base.py): same CEO + gate pattern as Talvenor, new
workers for creators. Flow, exactly as Boss described:

  CEO decision -> topic research -> script -> visual plan
  -> caption/hashtags -> publish prep (GATE) -> performance report

Mock mode: workers plan and draft through the model. Nothing publishes,
sends, or spends from here. PublishPrep output always carries
gate='post it' (video: 'upload it') and waits for the owner's word.
Rules baked into every brief: no invented stats, clients, or results;
no copyrighted music, characters, or copied work; no real person's
face/voice imitation.
"""
from __future__ import annotations

from src.workers.base import WorkerBase

RULES = (
    "Rules: never invent statistics, clients, results, or quotes. "
    "No copyrighted music, characters, or copied work. "
    "Never imitate a real person's face or voice. "
    "If a fact is missing, say what input is needed."
)


class TopicResearcher(WorkerBase):
    """Decides WITH the CEO what to make, then researches it."""

    task_kind = "topic_research"
    requires_gate = "ok"
    default_payload = {"niche": "", "audience": ""}

    def do_work(self, task):
        text = self.llm.complete(
            f"[TopicResearcher] CEO decision first: pick 3 content topics for "
            f"niche '{task.payload.get('niche', '')}' and audience "
            f"'{task.payload.get('audience', '')}'. For each: angle, why it "
            f"fits, and what to research next. {RULES}"
        )
        return text, {"topics": 3, "gate": "ok"}


class ScriptWriter(WorkerBase):
    """Turns the chosen topic into a script for any format."""

    task_kind = "script_write"
    requires_gate = "ok"
    default_payload = {"topic": "", "format": "short video"}

    def do_work(self, task):
        text = self.llm.complete(
            f"[ScriptWriter] Write a script for format "
            f"'{task.payload.get('format', '')}' on topic "
            f"'{task.payload.get('topic', '')}'. Structure: hook in first "
            f"2 seconds, one clear idea, simple CTA. {RULES}"
        )
        return text, {"script": True, "gate": "ok"}


class VisualProducer(WorkerBase):
    """Visual plan: shots, thumbnail idea, on-screen text."""

    task_kind = "visual_produce"
    requires_gate = "ok"
    default_payload = {"topic": "", "format": "short video"}

    def do_work(self, task):
        text = self.llm.complete(
            f"[VisualProducer] Visual plan for '{task.payload.get('format', '')}' "
            f"on '{task.payload.get('topic', '')}': shot list, thumbnail idea, "
            f"on-screen text (verbatim, short, readable). Real footage first; "
            f"if a shot cannot be filmed, say so instead of faking it. {RULES}"
        )
        return text, {"visual_plan": True, "gate": "ok"}


class CaptionWriter(WorkerBase):
    """Caption + hashtags adapted per platform."""

    task_kind = "caption_write"
    requires_gate = "ok"
    default_payload = {"topic": ""}

    def do_work(self, task):
        text = self.llm.complete(
            f"[CaptionWriter] Caption pack for topic "
            f"'{task.payload.get('topic', '')}': hook first line, one CTA, "
            f"hashtags (Instagram 5-8, LinkedIn 3, Facebook 0-2). {RULES}"
        )
        return text, {"caption_pack": True, "gate": "ok"}


class PublishPrep(WorkerBase):
    """Prepares the post. NEVER publishes — gate waits for the owner."""

    task_kind = "publish_prep"
    requires_gate = "post it"
    default_payload = {"topic": ""}

    def do_work(self, task):
        text = self.llm.complete(
            f"[PublishPrep] Prepare (do NOT publish) the post for topic "
            f"'{task.payload.get('topic', '')}': final checklist — hook, "
            f"readable text, no invented claims, platform, best time. {RULES}"
        )
        return text, {"ready_to_publish": False, "gate": "post it"}


class PerformanceTracker(WorkerBase):
    """Report template: what to measure, what to change next."""

    task_kind = "performance_track"
    requires_gate = "ok"
    default_payload = {"topic": ""}

    def do_work(self, task):
        text = self.llm.complete(
            f"[PerformanceTracker] Performance report template for topic "
            f"'{task.payload.get('topic', '')}': metrics to collect from each "
            f"platform, best/worst comparison, one change for next week. "
            f"Never estimate numbers — only platform numbers the owner pastes. {RULES}"
        )
        return text, {"report_template": True, "gate": "ok"}


ROSTER = [
    TopicResearcher,
    ScriptWriter,
    VisualProducer,
    CaptionWriter,
    PublishPrep,
    PerformanceTracker,
]
