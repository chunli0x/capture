"""Stake reader caching.

The TTL is a deliberate correctness trade (see stake_reader.py), so the caching
behaviour is worth pinning rather than leaving to inspection.
"""

from __future__ import annotations

import pytest
from solders.keypair import Keypair
from solders.pubkey import Pubkey

from tapfarm.stake_client import Position, StakeAccount
from tapfarm.stake_reader import StakeReader

PROGRAM = Pubkey.from_string("9brNsPyt6cb9yVv9kFNvN9xwd9ww41BJqiyG4DpCR1aQ")
MIN_HUMAN = 100_000
MIN_SKR = 1_000_000


def _account(human: int, skr: int) -> StakeAccount:
    return StakeAccount(
        contributor=Keypair().pubkey(),
        human=Position(amount=human, unstake_amount=0, unstake_requested_at=0),
        skr=Position(amount=skr, unstake_amount=0, unstake_requested_at=0),
        staked_at=0,
        bump=255,
    )


class _CountingReader(StakeReader):
    """Counts RPC reads so caching can be observed."""

    def __init__(self, account: StakeAccount | None, **kwargs):
        super().__init__("http://unused", PROGRAM, **kwargs)
        self.account = account
        self.fetches = 0

    async def _fetch(self, contributor: str) -> StakeAccount | None:
        self.fetches += 1
        return self.account


WHO = "6MyDMxNwbwtRjbfDLXVCG7GKtSuKHqAeS4gunLnEbHHK"


async def test_repeated_reads_hit_rpc_once(anyio_backend=None):
    reader = _CountingReader(_account(MIN_HUMAN, MIN_SKR))
    for _ in range(5):
        await reader.position(WHO)
    assert reader.fetches == 1


async def test_absent_stake_account_is_cached_too():
    """The common early case; it must not re-hit RPC on every task."""
    reader = _CountingReader(None)
    for _ in range(5):
        assert await reader.position(WHO) is None
    assert reader.fetches == 1


async def test_expiry_causes_a_refetch():
    reader = _CountingReader(_account(MIN_HUMAN, MIN_SKR), ttl_seconds=0)
    await reader.position(WHO)
    await reader.position(WHO)
    assert reader.fetches == 2


async def test_invalidate_forces_a_refetch():
    reader = _CountingReader(_account(MIN_HUMAN, MIN_SKR))
    await reader.position(WHO)
    reader.invalidate(WHO)
    await reader.position(WHO)
    assert reader.fetches == 2


async def test_no_program_configured_means_nobody_is_eligible():
    """Referrals must not silently pay out on a deployment without staking."""
    reader = StakeReader("http://unused", None)
    assert await reader.position(WHO) is None
    assert not await reader.is_referral_eligible(
        WHO, min_human_stake=MIN_HUMAN, min_skr_stake=MIN_SKR
    )


@pytest.mark.parametrize(
    "human,skr,expected",
    [
        (MIN_HUMAN, MIN_SKR, True),
        (MIN_HUMAN - 1, MIN_SKR, False),
        (MIN_HUMAN, MIN_SKR - 1, False),
        (0, 0, False),
        (MIN_HUMAN * 10, MIN_SKR * 10, True),
    ],
)
async def test_eligibility_requires_both_stakes(human, skr, expected):
    reader = _CountingReader(_account(human, skr))
    assert (
        await reader.is_referral_eligible(
            WHO, min_human_stake=MIN_HUMAN, min_skr_stake=MIN_SKR
        )
        is expected
    )


async def test_missing_stake_account_is_not_eligible():
    reader = _CountingReader(None)
    assert not await reader.is_referral_eligible(
        WHO, min_human_stake=MIN_HUMAN, min_skr_stake=MIN_SKR
    )
