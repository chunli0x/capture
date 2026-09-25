"""Referral accounting.

A referrer earns a share of **the platform's margin** on work their referees
complete. The referee's own earnings are never touched.

That distinction is the entire design. "Earn a percentage of the people you
recruit" describes both a normal referral programme and a pyramid; which one it
is depends on whose money it comes from. Skimming the referee makes a referred
contributor worse off for having been referred, and makes recruitment more
profitable than working. Paying out of our own margin makes it an acquisition
cost, which is what it actually is.

Three rules keep it that way:

- **Depth one.** A referrer earns from their direct referees only. Chains earn
  nothing beyond the first hop, so there is no downline to build - and a
  downline is what makes a pyramid a pyramid.
- **No self-referral and no cycles.** A wallet cannot refer itself, and two
  wallets cannot refer each other, which would otherwise let a pair skim our
  margin twice for the same work.
- **The referrer must have both stakes.** A slashable HUMAN bond so a referrer
  has something at risk if the people they bring in produce garbage, plus the
  SKR access stake.

## The sybil argument

Nothing here stops one person opening two wallets and referring themselves; that
is not detectable from an address. The defence is economic rather than
technical: a referral only pays when the referee *earns*, and earning requires
passing gold-standard accuracy (see `scoring.py`). A fake referee that does not
actually label correctly produces nothing to take a share of. To farm referrals
you have to do real, verified work - at which point you are a contributor and
the 2% is an ordinary acquisition cost.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Iterable

from tapfarm.config import Settings


class ReferralError(Exception):
    """Base for referral registration failures."""


class SelfReferral(ReferralError):
    pass


class AlreadyReferred(ReferralError):
    pass


class CircularReferral(ReferralError):
    pass


@dataclass(frozen=True)
class ReferralCredit:
    """One payment to a referrer, funded from the platform fee."""

    referrer: str
    referee: str
    task_value: int
    platform_fee: int
    amount: int


@dataclass
class ReferralStats:
    referees: int
    earned: int
    unclaimed: int


@dataclass
class ReferralLedger:
    """Referral graph and balances.

    In-memory for now; the interface is the part worth keeping stable when this
    moves to SQLite alongside the contributor ledger.
    """

    settings: Settings
    _referrer_of: dict[str, str] = field(default_factory=dict)
    _referees_of: dict[str, list[str]] = field(default_factory=dict)
    _earned: dict[str, int] = field(default_factory=dict)
    _unclaimed: dict[str, int] = field(default_factory=dict)

    # -- graph ---------------------------------------------------------------

    def register(self, referrer: str, referee: str) -> None:
        """Record that `referee` was brought in by `referrer`.

        Rejected rather than silently ignored, because a caller that thinks it
        registered a referral and did not will quietly under-pay someone.
        """
        if referrer == referee:
            raise SelfReferral("a contributor cannot refer themselves")
        if referee in self._referrer_of:
            raise AlreadyReferred(f"{referee} already has a referrer")
        if self._referrer_of.get(referrer) == referee:
            raise CircularReferral(
                f"{referee} already refers {referrer}; mutual referrals would "
                "skim the platform fee twice for the same work"
            )

        self._referrer_of[referee] = referrer
        self._referees_of.setdefault(referrer, []).append(referee)

    def referrer_of(self, referee: str) -> str | None:
        return self._referrer_of.get(referee)

    def referees_of(self, referrer: str) -> list[str]:
        return list(self._referees_of.get(referrer, ()))

    # -- accrual -------------------------------------------------------------

    def credit_for_task(
        self,
        referee: str,
        task_value: int,
        *,
        is_eligible: Callable[[str], bool],
    ) -> ReferralCredit | None:
        """Credit the referee's direct referrer for one paid task.

        Returns None when there is no referrer, when the referrer is not
        currently eligible, or when the computed share rounds to zero.

        Deliberately not recursive: only the direct referrer is paid, so a chain
        earns nothing past the first hop.
        """
        if task_value <= 0:
            return None

        referrer = self._referrer_of.get(referee)
        if referrer is None or not is_eligible(referrer):
            return None

        amount = self.settings.referral_reward(task_value)
        if amount <= 0:
            return None

        self._earned[referrer] = self._earned.get(referrer, 0) + amount
        self._unclaimed[referrer] = self._unclaimed.get(referrer, 0) + amount

        return ReferralCredit(
            referrer=referrer,
            referee=referee,
            task_value=task_value,
            platform_fee=self.settings.platform_fee(task_value),
            amount=amount,
        )

    # -- balances ------------------------------------------------------------

    def unclaimed(self, referrer: str) -> int:
        return self._unclaimed.get(referrer, 0)

    def claim(self, referrer: str) -> int:
        """Zero and return the unclaimed referral balance."""
        return self._unclaimed.pop(referrer, 0)

    def credit_back(self, referrer: str, amount: int) -> None:
        """Undo a claim that could not be completed.

        Lifetime `earned` is untouched because it never went down - only the
        unclaimed balance is being restored.
        """
        if amount > 0:
            self._unclaimed[referrer] = self._unclaimed.get(referrer, 0) + amount

    def stats(self, referrer: str) -> ReferralStats:
        return ReferralStats(
            referees=len(self._referees_of.get(referrer, ())),
            earned=self._earned.get(referrer, 0),
            unclaimed=self._unclaimed.get(referrer, 0),
        )

    def total_paid(self) -> int:
        return sum(self._earned.values())


def always_eligible(_contributor: str) -> bool:
    """Eligibility stub for tests and for local runs without staking wired up."""
    return True


def none_eligible(_contributor: str) -> bool:
    return False


def eligible_from(eligible: Iterable[str]) -> Callable[[str], bool]:
    allowed = set(eligible)
    return lambda contributor: contributor in allowed
