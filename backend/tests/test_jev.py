"""The escalation gate.

Two properties carry this module. Jev must never be able to answer the actual
question - that is the product, and the type system is what stops it. And the
rule must escalate when *any* signal fires, because the four questions catch
different failures and a conjunction would silently stop escalating the cases
only one of them sees.
"""

from __future__ import annotations

import pytest

from tapfarm.jev import (
    ROUTING_QUESTIONS,
    EscalationPolicy,
    FixedRouter,
    JevClassifier,
    JevError,
    RoutingAnswers,
    RoutingLog,
    decide,
    parse_jev_response,
)

CALM = dict(
    needs_human=0.10, is_ambiguous=0.10, is_risky=0.10, agent_confidence_ok=0.95
)


def answers(**overrides) -> RoutingAnswers:
    return RoutingAnswers(**{**CALM, **overrides})


class TestTheRuleIsAUnion:
    def test_a_calm_state_does_not_escalate(self):
        assert decide(answers()).escalate is False

    @pytest.mark.parametrize(
        "field,value",
        [
            ("needs_human", 0.71),
            ("is_ambiguous", 0.61),
            ("is_risky", 0.51),
            ("agent_confidence_ok", 0.49),
        ],
    )
    def test_any_single_signal_escalates(self, field, value):
        decision = decide(answers(**{field: value}))
        assert decision.escalate is True
        assert any(field in reason for reason in decision.reasons)

    def test_each_threshold_is_strict(self):
        """Exactly at the threshold does not fire; the spec says above."""
        assert decide(answers(needs_human=0.70)).escalate is False
        assert decide(answers(is_ambiguous=0.60)).escalate is False
        assert decide(answers(is_risky=0.50)).escalate is False
        # agent_confidence_ok is the one read as low-is-bad.
        assert decide(answers(agent_confidence_ok=0.50)).escalate is False
        assert decide(answers(agent_confidence_ok=0.499)).escalate is True

    def test_an_overconfident_agent_escalates_when_nothing_else_would(self):
        """The case the other three questions cannot see."""
        decision = decide(answers(agent_confidence_ok=0.2))
        assert decision.escalate is True
        assert decision.reasons == ["agent_confidence_ok 0.20"]

    def test_risk_has_the_lowest_bar(self):
        """Compliance is cheap to escalate and expensive to skip."""
        policy = EscalationPolicy()
        assert policy.is_risky_above < policy.is_ambiguous_above
        assert policy.is_risky_above < policy.needs_human_above

    def test_several_signals_are_all_reported(self):
        decision = decide(answers(needs_human=0.99, is_risky=0.9))
        assert len(decision.reasons) == 2
        assert "escalated" in decision.summary

    def test_the_policy_is_tunable_without_touching_the_rule(self):
        lenient = EscalationPolicy(needs_human_above=0.99)
        assert decide(answers(needs_human=0.8), lenient).escalate is False
        assert decide(answers(needs_human=0.8)).escalate is True


class TestJevCannotJudge:
    def test_routing_answers_have_no_verdict_field(self):
        """The product is the human's judgment; the router only routes.

        Pinned as a test because the tempting change - let the classifier
        answer the easy ones - would be a one-field edit, and this makes that
        edit fail here rather than ship.
        """
        fields = set(RoutingAnswers.__dataclass_fields__)
        assert fields == {
            "needs_human",
            "is_ambiguous",
            "is_risky",
            "agent_confidence_ok",
            "model",
        }
        for forbidden in ("verdict", "answer", "judgment", "choice", "label"):
            assert forbidden not in fields

    def test_only_the_four_routing_questions_are_asked(self):
        payload = JevClassifier("key")._payload("state")
        assert set(payload["questions"]) == set(ROUTING_QUESTIONS)
        assert all(q["type"] == "noul" for q in payload["questions"].values())

    def test_the_model_version_is_pinned_in_the_request(self):
        assert JevClassifier("key", model="jev-9.9.9")._payload("s")["model"] == "jev-9.9.9"


class TestResponseParsing:
    def test_the_documented_envelope_is_read(self):
        body = {
            "model": "jev-1.13.0",
            "answers": {
                name: {"type": "noul", "noul": 0.5} for name in ROUTING_QUESTIONS
            },
        }
        assert parse_jev_response(body).model == "jev-1.13.0"

    def test_the_flat_shape_from_the_spec_is_also_read(self):
        """The integration spec warned field names might drift; both work."""
        body = {name: {"type": "noul", "noul": 0.42} for name in ROUTING_QUESTIONS}
        assert parse_jev_response(body).needs_human == 0.42

    def test_a_missing_answer_raises_rather_than_defaulting_to_zero(self):
        """Zero would silently mean "definitely do not escalate"."""
        body = {"answers": {"needs_human": {"type": "noul", "noul": 0.9}}}
        with pytest.raises(JevError, match="missing a noul"):
            parse_jev_response(body)

    def test_a_non_numeric_probability_raises(self):
        body = {
            "answers": {
                name: {"type": "noul", "noul": "very likely"}
                for name in ROUTING_QUESTIONS
            }
        }
        with pytest.raises(JevError):
            parse_jev_response(body)

    def test_a_probability_outside_zero_to_one_is_refused(self):
        with pytest.raises(ValueError, match="must be a probability"):
            RoutingAnswers(1.4, 0.1, 0.1, 0.9)


class TestFallbackRouter:
    def test_it_names_itself_so_a_stub_is_never_mistaken_for_a_model(self):
        assert FixedRouter().classify("anything").model == "fixed-router"

    def test_it_satisfies_the_same_interface(self):
        assert isinstance(FixedRouter().classify({"a": 1}), RoutingAnswers)


class TestRoutingLog:
    def test_every_decision_is_recorded(self):
        log = RoutingLog()
        log.record("success_failure", decide(answers(needs_human=0.99)))
        log.record("preference", decide(answers()))
        assert len(log.recent()) == 2
        assert log.escalation_rate == 0.5

    def test_the_most_recent_decision_comes_first(self):
        log = RoutingLog()
        log.record("success_failure", decide(answers()))
        log.record("compliance_signoff", decide(answers(is_risky=0.9)))
        assert log.recent()[0].task_type == "compliance_signoff"

    def test_the_log_is_bounded(self):
        log = RoutingLog(capacity=5)
        for _ in range(50):
            log.record("preference", decide(answers()))
        assert len(log.recent(limit=100)) == 5

    def test_an_empty_log_has_no_rate_rather_than_zero(self):
        assert RoutingLog().escalation_rate is None
