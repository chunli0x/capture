"""Reads stake positions from the chain to answer eligibility questions.

Referral eligibility depends on what a contributor has actually staked, which
lives on-chain rather than in our database. Reading it per task submission would
put an RPC round trip in the hot path of the one action a contributor repeats
hundreds of times, so positions are cached briefly.

The TTL is a deliberate trade: for a short window after someone unstakes they
may still be credited a referral they no longer qualify for. That costs us a few
basis points of our own margin and nothing else - the referee is unaffected
either way - which is a better failure than making every tap wait on an RPC.
Slashing has no such tolerance and does not go through here.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from solana.rpc.async_api import AsyncClient
from solana.rpc.commitment import Confirmed
from solders.pubkey import Pubkey

from tapfarm.stake_client import StakeAccount, parse_stake_account, stake_pda


@dataclass
class _Entry:
    expires_at: float
    account: StakeAccount | None


class StakeReader:
    """Cached read-only view of stake accounts.

    A contributor with no stake account at all caches as None, which is the
    common case early on and should not re-hit RPC on every task.
    """

    def __init__(
        self,
        rpc_url: str,
        program_id: Pubkey | None,
        *,
        ttl_seconds: float = 30.0,
    ) -> None:
        self.rpc_url = rpc_url
        self.program_id = program_id
        self.ttl_seconds = ttl_seconds
        self._cache: dict[str, _Entry] = {}

    def invalidate(self, contributor: str) -> None:
        """Drop a cached position - call after a stake or unstake lands."""
        self._cache.pop(contributor, None)

    async def position(self, contributor: str) -> StakeAccount | None:
        if self.program_id is None:
            return None

        now = time.monotonic()
        cached = self._cache.get(contributor)
        if cached is not None and cached.expires_at > now:
            return cached.account

        account = await self._fetch(contributor)
        self._cache[contributor] = _Entry(now + self.ttl_seconds, account)
        return account

    async def _fetch(self, contributor: str) -> StakeAccount | None:
        try:
            owner = Pubkey.from_string(contributor)
        except Exception:
            return None

        pda, _ = stake_pda(self.program_id, owner)
        async with AsyncClient(self.rpc_url, commitment=Confirmed) as rpc:
            info = await rpc.get_account_info(pda, commitment=Confirmed)

        if info.value is None:
            return None
        try:
            return parse_stake_account(bytes(info.value.data))
        except Exception:
            # A layout mismatch must not take down task submission; treat it as
            # "no verifiable stake" and let the caller decline the referral.
            return None

    async def is_referral_eligible(
        self, contributor: str, *, min_human_stake: int, min_skr_stake: int
    ) -> bool:
        """Both stakes required: a slashable HUMAN bond, plus the SKR access stake."""
        account = await self.position(contributor)
        if account is None:
            return False
        return account.referral_eligible(min_human_stake, min_skr_stake)
