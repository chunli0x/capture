"""The escalation gate: deciding when an agent should buy a human judgment.

Jev is a "System One" classifier: you send a `state` plus a set of questions and
it returns typed answers with calibrated probabilities, in milliseconds, for a
fraction of an LLM call. Union uses it for exactly one thing - deciding
*whether* to escalate to a human.

## What this module structurally cannot do

Jev never produces the judgment. That is the human's job and it is the entire
product. This is enforced by the shape of the code rather than by a comment:
[RoutingAnswers] has four probability fields and no verdict field, so there is
nowhere for an answer to the actual question to live. A future edit that wanted
Jev to decide the outcome would have to change the type, which is a visible
thing to do in review.

## Swappable on purpose

The build spec asks for a thin interface, and the vendor is young - Jev
launched in September 2026. [RoutingClassifier] is the seam: any calibrated
classifier, or an LLM that reports honest confidence, can replace it without
touching the escalation rule, the endpoint, or the human feed. [FixedRouter]
is that seam's proof, and is what the tests and an offline demo run against.

## Calibration is the whole point

The thresholds below only mean something if the probabilities are calibrated -
if "0.7" really does mean seven times in ten. Jev is trained for that (TypeSafe
calls it RLCD). Swapping in a classifier whose scores are uncalibrated would
leave this code running unchanged and quietly wrong, so anything substituted
here needs its calibration checked, not just its accuracy.
"""

from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Protocol

log = logging.getLogger(__name__)

# Pinned, per the build spec. An escalation rule tuned against one model
# version is not automatically right for the next one.
DEFAULT_JEV_MODEL = "jev-1.13.0"
DEFAULT_JEV_URL = "https://api.typesafe.ai/v1/systemone"

# The four routing questions, verbatim from the integration spec so the wording
# the thresholds were chosen against is the wording actually sent.
ROUTING_QUESTIONS: dict[str, str] = {
    "needs_human": (
        "Does this outcome require a human to judge or verify, rather than the "
        "agent deciding alone?"
    ),
    "is_ambiguous": (
        "Is this outcome genuinely ambiguous - could a careful human reasonably "
        "disagree about what happened?"
    ),
    "is_risky": (
        "Does acting on this result carry risk that requires human sign-off "
        "before proceeding?"
    ),
    "agent_confidence_ok": (
        "Is the agent's stated confidence justified by the evidence?"
    ),
}

TASK_TYPES = (
    "success_failure",
    "preference",
    "physical_attestation",
    "compliance_signoff",
)


class JevError(RuntimeError):
    """The classifier could not be reached or returned something unusable."""


@dataclass(frozen=True)
class RoutingAnswers:
    """Four calibrated probabilities. Deliberately no verdict field."""

    needs_human: float
    is_ambiguous: float
    is_risky: float
    agent_confidence_ok: float
    model: str = "unknown"

    def __post_init__(self) -> None:
        for name in (
            "needs_human",
            "is_ambiguous",
            "is_risky",
            "agent_confidence_ok",
        ):
            value = getattr(self, name)
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"{name} must be a probability, got {value}")

    def as_dict(self) -> dict[str, float]:
        return {
            "needs_human": self.needs_human,
            "is_ambiguous": self.is_ambiguous,
            "is_risky": self.is_risky,
            "agent_confidence_ok": self.agent_confidence_ok,
        }


@dataclass(frozen=True)
class EscalationPolicy:
    """The thresholds from the integration spec.

    Any one of them is enough to escalate. They are a union rather than a
    conjunction because the four questions catch different failures - an
    unambiguous but risky step still needs a human, and so does an agent that
    is confidently wrong.

    `is_risky` has the lowest bar on purpose: a compliance gate is cheap to
    escalate and expensive to skip.

    `agent_confidence_ok` is the only one read as *low is bad*. It asks whether
    the agent's own confidence is justified, so a low score means the agent is
    overconfident - which is the case where nothing else would fire.
    """

    needs_human_above: float = 0.70
    is_ambiguous_above: float = 0.60
    is_risky_above: float = 0.50
    agent_confidence_ok_below: float = 0.50


@dataclass(frozen=True)
class EscalationDecision:
    escalate: bool
    reasons: list[str]
    answers: RoutingAnswers

    @property
    def summary(self) -> str:
        if not self.escalate:
            return "no human needed"
        return "escalated: " + ", ".join(self.reasons)


def decide(
    answers: RoutingAnswers, policy: EscalationPolicy | None = None
) -> EscalationDecision:
    """Apply the rule. Pure, so the thresholds can be tuned against real data."""
    policy = policy or EscalationPolicy()
    reasons: list[str] = []

    if answers.needs_human > policy.needs_human_above:
        reasons.append(f"needs_human {answers.needs_human:.2f}")
    if answers.is_ambiguous > policy.is_ambiguous_above:
        reasons.append(f"is_ambiguous {answers.is_ambiguous:.2f}")
    if answers.is_risky > policy.is_risky_above:
        reasons.append(f"is_risky {answers.is_risky:.2f}")
    if answers.agent_confidence_ok < policy.agent_confidence_ok_below:
        reasons.append(f"agent_confidence_ok {answers.agent_confidence_ok:.2f}")

    return EscalationDecision(
        escalate=bool(reasons), reasons=reasons, answers=answers
    )


class RoutingClassifier(Protocol):
    """The seam. Anything calibrated can sit here."""

    def classify(self, state: str | dict) -> RoutingAnswers: ...


@dataclass
class FixedRouter:
    """A classifier with no model behind it.

    Two jobs. It is what the tests run against, so the escalation rule can be
    exercised without a network call or a vendor account. And it is what an
    offline demo uses - clearly, rather than by pretending: `model` reads
    "fixed-router", so anything logging or displaying the decision shows that
    no classifier ran.
    """

    answers: RoutingAnswers = field(
        default_factory=lambda: RoutingAnswers(
            needs_human=0.93,
            is_ambiguous=0.71,
            is_risky=0.20,
            agent_confidence_ok=0.42,
            model="fixed-router",
        )
    )

    def classify(self, state: str | dict) -> RoutingAnswers:  # noqa: ARG002
        return self.answers


class JevClassifier:
    """Calls Jev over HTTP.

    The response shape is read defensively. TypeSafe's documented envelope
    nests answers under `answers`, while the integration spec this was written
    from shows them at the top level - the spec itself flagged that field names
    might drift. Both are accepted, and anything else raises rather than
    defaulting a missing probability to zero, because a zero would silently
    mean "definitely do not escalate" on a question nobody answered.
    """

    def __init__(
        self,
        api_key: str,
        *,
        url: str = DEFAULT_JEV_URL,
        model: str = DEFAULT_JEV_MODEL,
        timeout: float = 5.0,
    ) -> None:
        self.api_key = api_key
        self.url = url
        self.model = model
        self.timeout = timeout

    def _payload(self, state: str | dict) -> dict:
        return {
            "model": self.model,
            "state": state,
            "questions": {
                name: {"type": "noul", "instructions": text}
                for name, text in ROUTING_QUESTIONS.items()
            },
        }

    def classify(self, state: str | dict) -> RoutingAnswers:
        request = urllib.request.Request(
            self.url,
            data=json.dumps(self._payload(state)).encode(),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                body = json.loads(response.read())
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise JevError(f"jev request failed: {exc}") from exc

        return parse_jev_response(body, fallback_model=self.model)


def parse_jev_response(body: dict, *, fallback_model: str = "unknown") -> RoutingAnswers:
    """Pull the four probabilities out of whichever envelope arrived."""
    answers = body.get("answers", body)
    if not isinstance(answers, dict):
        raise JevError("jev response has no answers object")

    values: dict[str, float] = {}
    for name in ROUTING_QUESTIONS:
        entry = answers.get(name)
        if not isinstance(entry, dict) or "noul" not in entry:
            raise JevError(
                f"jev response is missing a noul for {name!r}; refusing to "
                "assume a probability for a question that was not answered"
            )
        try:
            values[name] = float(entry["noul"])
        except (TypeError, ValueError) as exc:
            raise JevError(f"jev returned a non-numeric noul for {name!r}") from exc

    return RoutingAnswers(**values, model=str(body.get("model", fallback_model)))


@dataclass(frozen=True)
class RoutingRecord:
    """One logged decision, for threshold tuning."""

    at: float
    task_type: str
    escalate: bool
    reasons: list[str]
    answers: dict[str, float]
    model: str


class RoutingLog:
    """Every routing decision, kept in memory.

    The spec asks for all decisions to be logged, and the reason is not
    auditing: the four thresholds are an explicit starting hypothesis, and the
    only way to tune them is against decisions paired with what the humans
    later said. Without the record there is nothing to tune from.

    Bounded, because an unbounded in-process list is a slow leak.
    """

    def __init__(self, capacity: int = 1000) -> None:
        self.capacity = capacity
        self._records: list[RoutingRecord] = []

    def record(self, task_type: str, decision: EscalationDecision) -> RoutingRecord:
        entry = RoutingRecord(
            at=time.time(),
            task_type=task_type,
            escalate=decision.escalate,
            reasons=list(decision.reasons),
            answers=decision.answers.as_dict(),
            model=decision.answers.model,
        )
        self._records.append(entry)
        if len(self._records) > self.capacity:
            del self._records[: len(self._records) - self.capacity]
        log.info(
            "routing %s task_type=%s model=%s",
            decision.summary,
            task_type,
            decision.answers.model,
        )
        return entry

    def recent(self, limit: int = 50) -> list[RoutingRecord]:
        return self._records[-limit:][::-1]

    @property
    def escalation_rate(self) -> float | None:
        if not self._records:
            return None
        return sum(1 for r in self._records if r.escalate) / len(self._records)
