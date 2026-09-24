"""The agent-facing paywall.

The properties worth pinning: a quoted price is spendable exactly once, the
wire format is x402 V2 on Solana rather than V1 on Base, and a judgment is not
sold to an agent that did not need one.
"""

from __future__ import annotations

import base64
import json

import pytest

from tapfarm.x402 import (
    PAYMENT_REQUIRED_HEADER,
    PAYMENT_SIGNATURE_HEADER,
    SCHEME_EXACT,
    SOLANA_DEVNET,
    SOLANA_MAINNET,
    JudgeRequest,
    PaymentLedger,
    PaymentReceipt,
    PaymentRequirement,
    ReceiptError,
    decode_payment_required,
    network_for,
    parse_payment_signature,
    payment_required_header,
)


def _requirement() -> PaymentRequirement:
    return PaymentRequirement(
        scheme=SCHEME_EXACT,
        network=SOLANA_DEVNET,
        price="$0.30",
        asset="USDC",
        pay_to="EYWceKawCcE7XuxSBF7mrh19GDqVFUTCURdje2e2aB16",
        resource="/v1/judge",
        description="One human judgment",
    )


def _signature(reference: str, payer: str = "agent") -> str:
    body = {"payload": {"reference": reference, "payer": payer}}
    return base64.b64encode(json.dumps(body).encode()).decode()


class TestTheWireFormat:
    def test_the_network_is_solana_not_base(self):
        """x402 runs natively on Solana; both legs stay on one chain."""
        assert network_for("devnet").startswith("solana:")
        assert network_for("mainnet-beta") == SOLANA_MAINNET

    def test_an_unknown_cluster_defaults_to_devnet(self):
        """A misconfigured cluster must route to a test chain, not a real one."""
        assert network_for("wat") == SOLANA_DEVNET

    def test_the_header_round_trips(self):
        header = payment_required_header([_requirement()])
        decoded = decode_payment_required(header)
        assert decoded["x402Version"] == 2
        assert decoded["accepts"][0]["network"] == SOLANA_DEVNET
        assert decoded["accepts"][0]["scheme"] == SCHEME_EXACT
        assert decoded["accepts"][0]["payTo"].startswith("EYW")

    def test_v2_header_names_are_used(self):
        """Solana's guide is explicit that V1's X-PAYMENT must not be reused."""
        assert PAYMENT_REQUIRED_HEADER == "PAYMENT-REQUIRED"
        assert PAYMENT_SIGNATURE_HEADER == "PAYMENT-SIGNATURE"
        assert "X-PAYMENT" not in (PAYMENT_REQUIRED_HEADER, PAYMENT_SIGNATURE_HEADER)


class TestSingleUsePayments:
    def test_a_reference_can_be_spent_once(self):
        ledger = PaymentLedger()
        reference = ledger.issue("$0.30")
        ledger.spend(PaymentReceipt(reference, "agent", SOLANA_DEVNET))
        with pytest.raises(ReceiptError, match="already been used"):
            ledger.spend(PaymentReceipt(reference, "agent", SOLANA_DEVNET))

    def test_an_unknown_reference_is_refused(self):
        """Fails closed: an unrecognised receipt buys nothing."""
        with pytest.raises(ReceiptError, match="unknown or expired"):
            PaymentLedger().spend(PaymentReceipt("made-up", "agent", SOLANA_DEVNET))

    def test_a_reference_expires(self):
        ledger = PaymentLedger(ttl_seconds=60)
        reference = ledger.issue("$0.30", now=1_000.0)
        with pytest.raises(ReceiptError, match="expired"):
            ledger.spend(
                PaymentReceipt(reference, "agent", SOLANA_DEVNET), now=1_200.0
            )

    def test_two_references_are_distinct(self):
        ledger = PaymentLedger()
        assert ledger.issue("$0.30") != ledger.issue("$0.30")


class TestSignatureParsing:
    def test_a_well_formed_signature_is_read(self):
        receipt = parse_payment_signature(_signature("abc123", payer="bot"))
        assert receipt.reference == "abc123"
        assert receipt.payer == "bot"

    def test_a_signature_without_a_reference_is_refused(self):
        """The reference is what ties a payment to a quoted price."""
        header = base64.b64encode(json.dumps({"payload": {}}).encode()).decode()
        with pytest.raises(ReceiptError, match="no reference"):
            parse_payment_signature(header)

    def test_garbage_is_refused(self):
        with pytest.raises(ReceiptError, match="base64 JSON"):
            parse_payment_signature("not-base64-at-all!!")

    def test_a_json_array_is_refused(self):
        header = base64.b64encode(json.dumps([1, 2]).encode()).decode()
        with pytest.raises(ReceiptError, match="JSON object"):
            parse_payment_signature(header)


class TestAgreement:
    def _request(self, verdicts):
        entry = JudgeRequest(
            request_id="r1",
            task_type="success_failure",
            question="did it work?",
            choices=["yes", "no"],
            media_url=None,
            price="$0.30",
            payer="agent",
            created_at=0.0,
        )
        entry.verdicts.extend(verdicts)
        return entry

    def test_unanimous_agreement(self):
        assert self._request(["yes", "yes", "yes"]).agreement == ("yes", 3, 3)

    def test_a_majority_with_a_dissent(self):
        assert self._request(["yes", "yes", "no"]).agreement == ("yes", 2, 3)

    def test_no_judgments_yet(self):
        assert self._request([]).agreement == (None, 0, 0)

    def test_a_tie_is_broken_deterministically(self):
        """Two judges can tie; the result must not wander between calls."""
        entry = self._request(["yes", "no"])
        assert entry.agreement == entry.agreement
