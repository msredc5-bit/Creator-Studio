"""Vendored worker base for Creator OS — standalone, no boss-ceo dependency.

This is a small, self-contained re-implementation of the WorkerBase
interface the Creator Studio workers were first built against
(`~/workspace/boss-ceo/src/workers/base.py`). It lives inside this repo
so the combined system runs on its own: no other checkout, no database,
no network, no keys.

Interface kept compatible on purpose:
  - Task(task_id, business_id, division_id, kind, payload)
  - WorkerResult(worker_id, task_id, status, output, notes,
                 mock_revenue_usd)
  - WorkerBase(worker_id, business_id, division_id, display_name, llm)
    with .do_work(task) -> (text, output_dict) and
    .execute(task) -> WorkerResult (never raises)
  - llm.complete(prompt) -> str, llm.health() -> dict

One deliberate difference from the boss-ceo base: execute() keeps the
worker's FULL text in WorkerResult.notes instead of truncating it to
280 characters, because here the note IS the draft the owner reads.
A failing worker still cannot crash a run: execute() catches everything
and returns status="failed".

MockLLM is the DEFAULT provider: deterministic, offline, $0. Its output
is always labelled [MOCK DRAFT] so mock text can never be mistaken for
a finished script.

LiveLLMProvider is a documented extension point only. It reads a key
from the environment variable CREATOR_OS_LLM_API_KEY (never from a
file) and its complete() deliberately raises: this repo makes NO
network calls by design, so the live path is unwired until someone
adds a provider here on purpose. Nothing in this repo will ever call
it on its own.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field


# ---------------------------------------------------------------------------
# Contracts
# ---------------------------------------------------------------------------
@dataclass
class Task:
    """One unit of work handed to a worker."""

    task_id: str
    business_id: str
    division_id: str
    kind: str
    payload: dict = field(default_factory=dict)


@dataclass
class WorkerResult:
    """What a worker returns. `notes` holds the full draft text."""

    worker_id: str
    task_id: str
    status: str  # "ok" | "failed"
    output: dict = field(default_factory=dict)
    notes: str = ""
    mock_revenue_usd: float = 0.0


class LLMProvider:
    """Minimal provider interface: complete a prompt, report health."""

    def complete(self, prompt: str) -> str:
        raise NotImplementedError

    def health(self) -> dict:
        return {"provider": self.__class__.__name__, "ok": True}


# ---------------------------------------------------------------------------
# Mock provider (default — offline, deterministic, $0)
# ---------------------------------------------------------------------------
class MockLLM(LLMProvider):
    """Deterministic mock: echoes the brief back as a labelled draft.

    The output is a scaffold, not a finished script — it states what
    the worker was asked to draft and leaves the real writing to a live
    model or a human. It never invents clients, stats, or results.
    """

    def __init__(self, seed: str = "creator-os-v1"):
        self.seed = seed
        self.calls = 0

    def complete(self, prompt: str) -> str:
        self.calls += 1
        brief = " ".join(prompt.split())
        head = brief[:400]
        return (
            "[MOCK DRAFT — no live model was called. "
            "Replace this scaffold with a real draft before shipping.]\n"
            f"Brief: {head}\n"
            "Draft outline (to be written for real):\n"
            "1. Open on the problem in the viewer's own words.\n"
            "2. One clear idea, shown — not claimed.\n"
            "3. Close with one simple ask.\n"
            "[END MOCK DRAFT]"
        )

    def health(self) -> dict:
        return {"provider": "MockLLM", "ok": True, "calls": self.calls,
                "spend_usd": 0.0}


# ---------------------------------------------------------------------------
# Live provider hook (deliberately unwired — see module docstring)
# ---------------------------------------------------------------------------
class LiveLLMProvider(LLMProvider):
    """Opt-in live-model seam. Key comes ONLY from the environment.

    Set CREATOR_OS_LLM_API_KEY in the environment (never in a file,
    never committed). The provider is NOT wired to any model here:
    complete() raises until someone adds a real provider implementation
    in this class on purpose, because this repo makes no network calls
    by design. The runner never constructs this class.
    """

    ENV_KEY = "CREATOR_OS_LLM_API_KEY"

    def __init__(self):
        key = os.environ.get(self.ENV_KEY)
        if not key:
            raise RuntimeError(
                f"Live LLM not configured: set {self.ENV_KEY} in the "
                "environment. Keys are never read from files and never "
                "committed. (The live path is also unwired by design: "
                "this repo makes no network calls.)"
            )
        self._key_present = True  # the key itself is never stored or logged

    def complete(self, prompt: str) -> str:
        raise RuntimeError(
            "Live LLM calls are not implemented in this repo (no network "
            "by design). Add a provider implementation in "
            "LiveLLMProvider.complete() if you need one, keeping the key "
            "in the environment only."
        )

    def health(self) -> dict:
        return {"provider": "LiveLLMProvider", "ok": False,
                "note": "unwired by design"}


# ---------------------------------------------------------------------------
# Worker base
# ---------------------------------------------------------------------------
class WorkerBase:
    """Template every Creator OS worker extends.

    Concrete workers override do_work() and return (text, output_dict).
    execute() wraps the result and never raises.
    """

    task_kind = ""
    requires_gate = "ok"
    default_payload: dict = {}

    def __init__(
        self,
        worker_id: str,
        business_id: str,
        division_id: str,
        display_name: str,
        llm: LLMProvider,
    ):
        self.worker_id = worker_id
        self.business_id = business_id
        self.division_id = division_id
        self.display_name = display_name
        self.llm = llm

    # -- override this in concrete workers ---------------------------------
    def do_work(self, task: Task) -> tuple[str, dict]:
        """Return (draft_text, output_dict). May use self.llm.complete()."""
        text = self.llm.complete(
            f"[{self.display_name}] execute {task.kind}: {task.payload}"
        )
        return text, {"plan": text}

    # -- base machinery (do not override) ----------------------------------
    def execute(self, task: Task) -> WorkerResult:
        try:
            notes, output = self.do_work(task)
            return WorkerResult(
                worker_id=self.worker_id,
                task_id=task.task_id,
                status="ok",
                output=output,
                mock_revenue_usd=self._parse_mock_revenue(notes),
                notes=notes,
            )
        except Exception as exc:  # never let a worker crash the run
            return WorkerResult(
                worker_id=self.worker_id,
                task_id=task.task_id,
                status="failed",
                notes=f"worker error: {exc}",
            )

    @staticmethod
    def _parse_mock_revenue(notes: str) -> float:
        """Kept for interface compatibility with the boss-ceo base.

        Mock drafts contain no dollar amounts, so this is always 0.0.
        It exists so code written against the old base keeps working.
        """
        m = re.search(r"\$(\d+(?:\.\d{1,2})?)", notes)
        return float(m.group(1)) if m else 0.0
