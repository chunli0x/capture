"""The paywall an agent walks through to buy a human judgment.

x402 revives HTTP 402: a resource server answers an unpaid request with
`402 Payment Required` and a description of what it costs, the client signs a
payment and retries, and the server serves. No account, no checkout, no card -
which is the point, because the client here is a program.

## Solana, both directions

The user-flow draft describes the agent's side as "USDC on Base". It does not
have to be, and for this project it should not be: x402 runs natively on
Solana with SPL tokens, and Solana carries the clear majority of the
protocol's traffic. Keeping both legs on one chain removes a bridge from the
demo, removes a second wallet from the story, and means the payment the agent
makes and the payout the human receives are the same asset on the same chain.

Locked decision #7 only fixes the *payout* rail. This module makes the inbound
leg Solana too, and says so here rather than leaving a reader to infer it.

## V2, not V1

The V2 transport is header-based: the requirements travel in a
`PAYMENT-REQUIRED` header as base64 JSON, and the client retries with
`PAYMENT-SIGNATURE`. Solana's own guide is explicit that V1's `X-PAYMENT`
fields must not be used in a new integration, so they are not used here.

## What is real and what is simulated

The build spec allows the agent's inbound payment to be simulated for the
demo, and it is: [verify_payment] checks that a receipt is well-formed and
unspent, not that a transfer settled on chain. That is a stub with a name that
says so, and the endpoint reports it. The human's outbound USDC is the real
path and goes through the existing claim transaction.
"""

from __future__ import annotations

import base64
import json
import secrets
import threading
import time
from dataclasses import dataclass, field

# CAIP-2 chain identifiers, from Solana's x402 guide.
SOLANA_DEVNET = "solana:EtWTRABZaYq6iMfeYKouRu166VU2xqa1"
SOLANA_MAINNET = "solana:5eykt4UsFv8P8NJdTREpY1vzqKqZKvdp"

PAYMENT_REQUIRED_HEADER = "PAYMENT-REQUIRED"
PAYMENT_SIGNATURE_HEADER = "PAYMENT-SIGNATURE"

# The only scheme this server accepts: a fixed price, paid in full.
SCHEME_EXACT = "exact"


def network_for(cluster: str) -> str:
    """CAIP-2 id for a cluster name, defaulting to devnet.

    Devnet by default rather than mainnet: a misconfigured cluster string
    should route a payment to a test chain, not a real one.
    """
    return SOLANA_MAINNET if cluster in ("mainnet", "mainnet-beta") else SOLANA_DEVNET


@dataclass(frozen=True)
class PaymentRequirement:
    """What the server will accept for this resource."""

    scheme: str
    network: str
    price: str
    asset: str
    pay_to: str
    resource: str
    description: str
    mime_type: str = "application/json"
    max_timeout_seconds: int = 300

    def as_dict(self) -> dict:
        return {
            "scheme": self.scheme,
            "network": self.network,
            "price": self.price,
            "asset": self.asset,
            "payTo": self.pay_to,
            "resource": self.resource,
            "description": self.description,
            "mimeType": self.mime_type,
            "maxTimeoutSeconds": self.max_timeout_seconds,
        }


def payment_required_header(requirements: list[PaymentRequirement]) -> str:
    """Base64 JSON for the `PAYMENT-REQUIRED` header."""
    body = {"x402Version": 2, "accepts": [r.as_dict() for r in requirements]}
    return base64.b64encode(json.dumps(body).encode()).decode()


def decode_payment_required(header: str) -> dict:
    """Inverse of the above, so a test reads what a client would."""
    return json.loads(base64.b64decode(header))


@dataclass(frozen=True)
class PaymentReceipt:
    """A client's claim to have paid. Opaque to this module beyond its shape."""

    reference: str
    payer: str
    network: str


class ReceiptError(ValueError):
    """The receipt is malformed, unknown, or already spent."""


@dataclass
class _Issued:
    reference: str
    price: str
    issued_at: float
    spent: bool = False


class PaymentLedger:
    """Issues payment references and spends them exactly once.

    The single-use rule is the part worth having even in a simulated
    integration. Without it one receipt buys unlimited judgments, and the
    demo's economics - an agent paying per judgment - would be a story rather
    than a mechanism.

    In memory and thread-safe, matching the rest of this backend. A restart
    forgets outstanding references, which fails closed: an unknown reference
    is refused rather than honoured.
    """

    def __init__(self, ttl_seconds: float = 900.0) -> None:
        self.ttl_seconds = ttl_seconds
        self._lock = threading.Lock()
        self._issued: dict[str, _Issued] = {}

    def issue(self, price: str, *, now: float | None = None) -> str:
        now = time.time() if now is None else now
        reference = secrets.token_hex(16)
        with self._lock:
            self._evict(now)
            self._issued[reference] = _Issued(
                reference=reference, price=price, issued_at=now
            )
        return reference

    def spend(self, receipt: PaymentReceipt, *, now: float | None = None) -> _Issued:
        """Consume a receipt, or explain precisely why it cannot be."""
        now = time.time() if now is None else now
        with self._lock:
            entry = self._issued.get(receipt.reference)
            if entry is None:
                raise ReceiptError("unknown or expired payment reference")
            if entry.spent:
                raise ReceiptError("payment reference has already been used")
            if now - entry.issued_at > self.ttl_seconds:
                raise ReceiptError("payment reference expired; request a new price")
            entry.spent = True
            return entry

    def _evict(self, now: float) -> None:
        stale = [
            k for k, v in self._issued.items() if now - v.issued_at > self.ttl_seconds
        ]
        for key in stale:
            del self._issued[key]


def parse_payment_signature(header: str) -> PaymentReceipt:
    """Read the client's `PAYMENT-SIGNATURE` header.

    Strict about the fields it needs. A receipt missing its reference is not
    "probably fine" - it is the one field that makes a payment attributable to
    a quoted price.
    """
    try:
        body = json.loads(base64.b64decode(header))
    except Exception as exc:  # noqa: BLE001 - any decode failure is one fault
        raise ReceiptError(f"payment signature is not base64 JSON: {exc}") from exc

    if not isinstance(body, dict):
        raise ReceiptError("payment signature must be a JSON object")

    payload = body.get("payload", body)
    reference = payload.get("reference")
    if not reference:
        raise ReceiptError("payment signature has no reference")

    return PaymentReceipt(
        reference=str(reference),
        payer=str(payload.get("payer", "")),
        network=str(body.get("network", payload.get("network", ""))),
    )


@dataclass
class JudgeRequest:
    """An agent's request for a human verdict, awaiting or holding one."""

    request_id: str
    task_type: str
    question: str
    choices: list[str]
    media_url: str | None
    price: str
    payer: str
    created_at: float
    verdicts: list[str] = field(default_factory=list)
    resolved: bool = False

    @property
    def agreement(self) -> tuple[str | None, int, int]:
        """Majority answer, how many agreed, how many judged."""
        if not self.verdicts:
            return None, 0, 0
        counts: dict[str, int] = {}
        for verdict in self.verdicts:
            counts[verdict] = counts.get(verdict, 0) + 1
        best = max(counts, key=lambda k: (counts[k], k))
        return best, counts[best], len(self.verdicts)
