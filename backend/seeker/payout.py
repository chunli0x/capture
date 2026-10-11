"""Capture v2 payout economics (devnet TEST-USDC).

Grounded in ``/home/hermes/egocentric-dataset-unit-economics.md``:

- minimal (3-primary-only) base rate, in whole US cents:
  photo $0.07, video 5-15s $0.17, video 15-30s $0.27.
- complete (6-dim) labels earn a +50% "label premium" over minimal, floored to
  the contract's headline rates: photo $0.10, video $0.25, video $0.40.
  ``7*1.5=10.5 -> 10``, ``17*1.5=25.5 -> 25``, ``27*1.5=40.5 -> 40`` — exactly
  the §3 table, and the top-tier (level 4, x1.5) results $0.15/$0.38/$0.60
  match unit-economics §5.
- the level rate multiplier multiplies on top (x1.0 .. x1.5).
- the bond is 2x payout (waived at Pathfinder, bond_multiplier 0.0).

``payout_usdc`` is returned in USDC base units (6 decimals): $0.10 == 100_000.
"""

from .leveling import rate_multiplier

USDC_DECIMALS = 6
UNITS_PER_CENT = 10 ** (USDC_DECIMALS - 2)  # 10_000

# minimal-label base rate in whole US cents.
MINIMAL_CENTS = {"photo": 7, "video_short": 17, "video_long": 27}

# complete (6-dim) labels earn this multiple over minimal.
COMPLETE_PREMIUM = 1.5

VIDEO_SHORT_MS = 15_000  # <= 15s -> the 5-15s tier
VIDEO_LONG_MS = 30_000   # 15-30s tier (canonicalizer already rejects > 30s)


def media_tier(kind: str, duration_ms: int | None) -> str:
    """Map a submission's kind + clip duration to a payout tier."""
    if kind != "action":
        return "photo"
    if duration_ms is None or duration_ms <= VIDEO_SHORT_MS:
        return "video_short"
    return "video_long"


def payout_cents(level: int, kind: str, duration_ms: int | None, complete: bool) -> int:
    """Whole US cents for an accepted submission at a given level."""
    tier = media_tier(kind, duration_ms)
    cents = MINIMAL_CENTS[tier] * (COMPLETE_PREMIUM if complete else 1.0)
    cents *= rate_multiplier(level)
    return int(cents)


def payout_units(level: int, kind: str, duration_ms: int | None, complete: bool) -> int:
    """USDC base units (micro-USDC) for an accepted submission."""
    return payout_cents(level, kind, duration_ms, complete) * UNITS_PER_CENT


def bond_units(payout_units_value: int, level: int) -> int:
    """The slashable bond denominated against this payout (2x, waived at L4)."""
    from .leveling import bond_multiplier

    return int(payout_units_value * bond_multiplier(level))
