"""Referral rules.

Most of these correspond to a way of turning a referral programme into a
pyramid, or of skimming the platform fee twice.
"""

from __future__ import annotations

import pytest

from tapfarm.config import Settings
from tapfarm.referrals import (
    AlreadyReferred,
    CircularReferral,
    ReferralLedger,
    SelfReferral,
    always_eligible,
    eligible_from,
    none_eligible,
)

ALICE, BOB, CAROL, DAVE = "alice", "bob", "carol", "dave"
TASK_VALUE = 10_000  # 0.01 TAP, the default reward per task


@pytest.fixture
def settings() -> Settings:
    return Settings()


@pytest.fixture
def ledger(settings) -> ReferralLedger:
    return ReferralLedger(settings=settings)


# -- graph --------------------------------------------------------------------

def test_registers_a_referral(ledger):
    ledger.register(ALICE, BOB)
    assert ledger.referrer_of(BOB) == ALICE
    assert ledger.referees_of(ALICE) == [BOB]


def test_self_referral_is_rejected(ledger):
    with pytest.raises(SelfReferral):
        ledger.register(ALICE, ALICE)


def test_a_contributor_cannot_be_referred_twice(ledger):
    """Otherwise a later referrer could steal an existing relationship."""
    ledger.register(ALICE, BOB)
    with pytest.raises(AlreadyReferred):
        ledger.register(CAROL, BOB)
    assert ledger.referrer_of(BOB) == ALICE


def test_mutual_referral_is_rejected(ledger):
    """Two wallets referring each other would skim the fee twice per task."""
    ledger.register(ALICE, BOB)
    with pytest.raises(CircularReferral):
        ledger.register(BOB, ALICE)


def test_one_referrer_can_have_many_referees(ledger):
    for referee in (BOB, CAROL, DAVE):
        ledger.register(ALICE, referee)
    assert sorted(ledger.referees_of(ALICE)) == sorted([BOB, CAROL, DAVE])
    assert ledger.stats(ALICE).referees == 3


# -- accrual ------------------------------------------------------------------

def test_referrer_earns_from_a_referee_task(ledger, settings):
    ledger.register(ALICE, BOB)
    credit = ledger.credit_for_task(BOB, TASK_VALUE, is_eligible=always_eligible)

    assert credit is not None
    assert credit.referrer == ALICE and credit.referee == BOB
    assert credit.amount == settings.referral_reward(TASK_VALUE)
    assert ledger.unclaimed(ALICE) == credit.amount


def test_the_referral_comes_out_of_the_platform_fee(ledger, settings):
    """The invariant that separates a bonus from a pyramid."""
    ledger.register(ALICE, BOB)
    credit = ledger.credit_for_task(BOB, TASK_VALUE, is_eligible=always_eligible)

    assert credit is not None
    assert credit.platform_fee == settings.platform_fee(TASK_VALUE)
    assert credit.amount <= credit.platform_fee
    # And it is a share of our margin, not of the task value.
    assert credit.amount < TASK_VALUE


def test_referral_never_exceeds_the_fee_even_if_misconfigured(settings):
    """A config edit must not be able to make us pay out more than we take."""
    greedy = settings.model_copy(update={"referral_share_of_fee_bps": 10_000})
    ledger = ReferralLedger(settings=greedy)
    ledger.register(ALICE, BOB)

    credit = ledger.credit_for_task(BOB, TASK_VALUE, is_eligible=always_eligible)
    assert credit is not None
    assert credit.amount == credit.platform_fee


def test_referee_earnings_are_untouched(ledger):
    """The ledger never returns anything that reduces the referee's reward.

    Structural: this module only ever adds to the referrer's balance. The test
    exists so the property is stated where someone would go to change it.
    """
    ledger.register(ALICE, BOB)
    ledger.credit_for_task(BOB, TASK_VALUE, is_eligible=always_eligible)
    assert ledger.unclaimed(BOB) == 0
    assert ledger.stats(BOB).earned == 0


def test_unreferred_contributor_credits_nobody(ledger):
    assert ledger.credit_for_task(BOB, TASK_VALUE, is_eligible=always_eligible) is None
    assert ledger.total_paid() == 0


def test_ineligible_referrer_earns_nothing(ledger):
    """Referral pay requires the referrer to have both stakes."""
    ledger.register(ALICE, BOB)
    assert ledger.credit_for_task(BOB, TASK_VALUE, is_eligible=none_eligible) is None
    assert ledger.unclaimed(ALICE) == 0


def test_eligibility_is_checked_per_referrer(ledger):
    ledger.register(ALICE, BOB)
    ledger.register(CAROL, DAVE)
    only_alice = eligible_from([ALICE])

    assert ledger.credit_for_task(BOB, TASK_VALUE, is_eligible=only_alice) is not None
    assert ledger.credit_for_task(DAVE, TASK_VALUE, is_eligible=only_alice) is None


def test_zero_value_task_pays_no_referral(ledger):
    """A failed gold task pays the contributor nothing, so it pays no referral."""
    ledger.register(ALICE, BOB)
    assert ledger.credit_for_task(BOB, 0, is_eligible=always_eligible) is None


def test_chains_pay_only_the_direct_referrer(ledger, settings):
    """Depth one. A downline is what makes a pyramid a pyramid."""
    ledger.register(ALICE, BOB)
    ledger.register(BOB, CAROL)

    credit = ledger.credit_for_task(CAROL, TASK_VALUE, is_eligible=always_eligible)

    assert credit is not None and credit.referrer == BOB
    assert ledger.unclaimed(BOB) == settings.referral_reward(TASK_VALUE)
    assert ledger.unclaimed(ALICE) == 0, "grandparent must earn nothing"


def test_a_long_chain_still_pays_only_one_hop(ledger):
    ledger.register(ALICE, BOB)
    ledger.register(BOB, CAROL)
    ledger.register(CAROL, DAVE)

    ledger.credit_for_task(DAVE, TASK_VALUE, is_eligible=always_eligible)

    assert ledger.unclaimed(CAROL) > 0
    assert ledger.unclaimed(BOB) == 0
    assert ledger.unclaimed(ALICE) == 0


def test_earnings_accumulate_across_referees(ledger, settings):
    ledger.register(ALICE, BOB)
    ledger.register(ALICE, CAROL)
    for referee in (BOB, CAROL, BOB):
        ledger.credit_for_task(referee, TASK_VALUE, is_eligible=always_eligible)

    assert ledger.unclaimed(ALICE) == 3 * settings.referral_reward(TASK_VALUE)


# -- claiming -----------------------------------------------------------------

def test_claim_zeroes_the_unclaimed_balance_but_keeps_lifetime_earned(ledger):
    ledger.register(ALICE, BOB)
    ledger.credit_for_task(BOB, TASK_VALUE, is_eligible=always_eligible)
    earned = ledger.stats(ALICE).earned

    assert ledger.claim(ALICE) == earned
    assert ledger.unclaimed(ALICE) == 0
    assert ledger.stats(ALICE).earned == earned, "lifetime total must survive"


def test_claiming_twice_yields_nothing_the_second_time(ledger):
    ledger.register(ALICE, BOB)
    ledger.credit_for_task(BOB, TASK_VALUE, is_eligible=always_eligible)
    ledger.claim(ALICE)
    assert ledger.claim(ALICE) == 0


def test_claiming_with_no_referrals_is_zero_not_an_error(ledger):
    assert ledger.claim(ALICE) == 0
