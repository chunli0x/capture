"""RPC resilience: 429 backoff + automatic endpoint failover.

The public devnet RPC rate-limits under load; a single HTTP 429 must not wedge
the demo. These tests drive ``Chain.rpc`` through a fake transport and assert
the retry / failover contract without touching the network.
"""

from types import SimpleNamespace

import httpx
import pytest
from solders.keypair import Keypair

from seeker.chain import Chain, ChainUnavailable


class FakeResponse:
    def __init__(self, status_code=200, payload=None, http_error=None):
        self.status_code = status_code
        self._payload = payload
        self._http_error = http_error

    def raise_for_status(self):
        if self._http_error is not None:
            raise self._http_error

    def json(self):
        return self._payload


def make_chain(monkeypatch, fallback_url="https://fallback.example", attempts=3):
    settings = SimpleNamespace(
        program_id="5TiDwP86k95yfQWzExrPTj5qcKxED99z8pW9fN81u5SV",
        usdc_mint=str(Keypair().pubkey()),
        verifier_pubkey=str(Keypair().pubkey()),
        rpc_url="https://primary.example",
        rpc_fallback_url=fallback_url,
        rpc_attempts=attempts,
        cluster="devnet",
        min_bond=1_000_000,
    )
    chain = Chain(settings)
    monkeypatch.setattr("seeker.chain.time.sleep", lambda *_: None)
    return chain


def install_transport(monkeypatch, responses):
    """``responses`` maps url -> list of FakeResponse consumed in order."""
    calls = {url: [] for url in responses}

    def fake_post(url, **kwargs):
        calls[url].append(url)
        seq = responses[url]
        idx = len(calls[url]) - 1
        return seq[min(idx, len(seq) - 1)]

    monkeypatch.setattr("seeker.chain.httpx.post", fake_post)
    return calls


RESULT = {"result": {"ok": True}}


def test_429_retries_then_succeeds(monkeypatch):
    chain = make_chain(monkeypatch, fallback_url=None)
    calls = install_transport(monkeypatch, {
        "https://primary.example": [
            FakeResponse(status_code=429),
            FakeResponse(status_code=429),
            FakeResponse(payload=RESULT),
        ],
    })
    assert chain.rpc("getSlot", []) == {"ok": True}
    assert len(calls["https://primary.example"]) == 3


def test_fails_over_when_primary_rate_limited(monkeypatch):
    chain = make_chain(monkeypatch)
    calls = install_transport(monkeypatch, {
        "https://primary.example": [FakeResponse(status_code=429)] * 3,
        "https://fallback.example": [FakeResponse(payload=RESULT)],
    })
    assert chain.rpc("getSlot", []) == {"ok": True}
    assert len(calls["https://primary.example"]) == 3
    assert calls["https://fallback.example"] == ["https://fallback.example"]


def test_fails_over_on_transport_error(monkeypatch):
    chain = make_chain(monkeypatch)
    calls = install_transport(monkeypatch, {
        "https://primary.example": [FakeResponse(http_error=httpx.ConnectError("down"))],
        "https://fallback.example": [FakeResponse(payload=RESULT)],
    })
    assert chain.rpc("getSlot", []) == {"ok": True}
    assert calls["https://fallback.example"] == ["https://fallback.example"]


def test_fails_closed_when_all_exhausted(monkeypatch):
    chain = make_chain(monkeypatch)
    install_transport(monkeypatch, {
        "https://primary.example": [FakeResponse(status_code=429)] * 3,
        "https://fallback.example": [FakeResponse(status_code=429)] * 3,
    })
    with pytest.raises(ChainUnavailable):
        chain.rpc("getSlot", [])


def test_authoritative_error_does_not_failover(monkeypatch):
    chain = make_chain(monkeypatch)
    calls = install_transport(monkeypatch, {
        "https://primary.example": [
            FakeResponse(payload={"error": {"code": -32602, "message": "bad"}}),
        ],
        "https://fallback.example": [FakeResponse(payload=RESULT)],
    })
    with pytest.raises(ChainUnavailable):
        chain.rpc("getSlot", [])
    # A deterministic RPC rejection must not retry or fail over.
    assert len(calls["https://primary.example"]) == 1
    assert calls["https://fallback.example"] == []
