"""VLM judge behind a clean abstraction; deterministic stub is the default.

The real judge target is ChatGPT Astra (``gpt-6-astra``) on the founder's paid
ChatGPT subscription, but the exact callable endpoint is not pinned yet. Two
access options to wire once it is:

  (a) an OpenAI-compatible API endpoint, if Astra is exposed there under a
      model name — call ``POST {SEEKER_JUDGE_URL}`` with a chat-completions
      payload, model ``gpt-6-astra``, key in ``Authorization: Bearer``;
  (b) reuse the ChatGPT OAuth token already on this box (``~/.codex/auth.json``,
      used by the Codex CLI device-auth) to call Astra the way Codex does.

Both are gated behind ``SEEKER_JUDGE_URL`` + ``SEEKER_JUDGE_KEY``; until either
is set, the deterministic :class:`StubJudge` is the default and the test suite
runs with no network. The rubric is the auto-accept / auto-reject rules in
``/home/hermes/egocentric-data-spec.md`` §2.2-§2.3.

The stub is *label-and-metadata* rule-based: it has no access to decoded pixels,
so the pixel-level reject rules (blur, exposure, ground-level horizon, screen
content, watermark) are the real judge's job, not the stub's. The stub rejects
only what is machine-checkable from the submitted labels + metadata + media
properties, which keeps it deterministic and free to run in CI.
"""

from __future__ import annotations

import abc
import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Verdict:
    accepted: bool
    reason: str

    def as_dict(self) -> dict:
        return {"accepted": self.accepted, "reason": self.reason}


class Judge(abc.ABC):
    """One judgment for one submission. Synchronous and side-effect free."""

    @abc.abstractmethod
    def judge(self, kind: str, labels, secondary: dict, metadata: dict,
              duration_ms: int | None, has_media: bool) -> Verdict:
        """Return an accept/reject verdict for a labeled submission."""


class StubJudge(Judge):
    """Deterministic rule-based judge over the data-spec auto-checks.

    Reject rules (in order):
      1. no media uploaded;
      2. missing primary label (no boxes / scene / action);
      3. posture absent (v2 requires it);
      4. video (``action``) with no ego-motion — the data spec §5.3 rejects a
         locked-off static shot outright ("an image would do");
      5. ``weather`` tagged while the environment is explicitly indoor.

    Everything else accepts, mirroring the spec's auto-accept fast path (sharp
    subject, declared category present, posture present).
    """

    def judge(self, kind, labels, secondary, metadata, duration_ms, has_media) -> Verdict:
        secondary = secondary or {}
        metadata = metadata or {}

        if not has_media:
            return Verdict(False, "no media uploaded")
        if not labels:
            return Verdict(False, "missing primary label")
        if not secondary.get("postures"):
            return Verdict(False, "posture is required")
        if kind == "action" and not metadata.get("ego_motion"):
            return Verdict(False, "video has no ego-motion (static footage is rejected)")
        if metadata.get("weather") and _is_indoor(secondary.get("environment")):
            return Verdict(False, "weather tags are outdoor-only")
        return Verdict(True, "accepted by deterministic stub judge")


def _is_indoor(environment) -> bool:
    """True when the resolved environment explicitly declares ``indoor``.

    ``environment`` is a list of resolved ``{id, name, kind, group}`` dicts.
    ``indoor`` is category id 1 in the environment namespace.
    """
    for entry in environment or []:
        if isinstance(entry, dict) and entry.get("id") == 1:
            return True
    return False


class AstraJudge(Judge):
    """Real Astra (gpt-6-astra) call, gated behind SEEKER_JUDGE_URL + SEEKER_JUDGE_KEY.

    Not wired end-to-end: the exact endpoint (OpenAI-compatible API vs Codex
    OAuth device-auth) is still to be pinned. This adapter raises a clear error
    so the failure mode is loud, never a silent pass.
    """

    def __init__(self, url: str, key: str):
        self.url = url
        self.key = key

    def judge(self, kind, labels, secondary, metadata, duration_ms, has_media) -> Verdict:
        # TODO(astra): call `self.url` with model gpt-6-astra and parse the
        # verdict. Two transport options (see module docstring). Raise until
        # the endpoint is pinned so a misconfigured deployment never silently
        # accepts with a stub.
        raise RuntimeError(
            "Astra judge is configured but not wired; implement the transport "
            "for SEEKER_JUDGE_URL (OpenAI-compatible API or Codex OAuth)"
        )


def build_judge(settings=None) -> Judge:
    """Pick the judge: Astra when env flags are set, otherwise the stub."""
    url = (getattr(settings, "judge_url", "") if settings else "") or os.environ.get(
        "SEEKER_JUDGE_URL", ""
    )
    key = (getattr(settings, "judge_key", "") if settings else "") or os.environ.get(
        "SEEKER_JUDGE_KEY", ""
    )
    if url and key:
        return AstraJudge(url, key)
    return StubJudge()
