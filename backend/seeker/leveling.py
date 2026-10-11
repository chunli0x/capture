"""Capture v2 contributor level ladder (levels 0..4).

Pinned by ``/home/hermes/clock-in/CAPTURE-V2-CONTRACT.md`` §2 and mirrored by the
Android ``Leveling.kt`` table. A level is gated by BOTH a cumulative accepted
count and a rolling acceptance-rate threshold; the highest level whose two
gates are both met is the contributor's level. Level 0 (Scout) has no rate
gate, so every contributor is at least a Scout.

The rolling acceptance rate is over the most recent ``ROLLING_WINDOW`` judged
submissions (the data spec's "last 50"), so one bad batch does not demote a
veteran but a sustained dip does. The rate is a fraction in ``[0, 1]``.
"""

from typing import Final

MAX_LEVEL: Final = 4
ROLLING_WINDOW: Final = 50

# level -> (name, accepted_threshold, rate_threshold | None, rate_multiplier,
#          bond_multiplier). bond_multiplier 0.0 == bond waived.
LEVELS: Final[list[tuple[int, str, int, float | None, float, float]]] = [
    (0, "Scout", 0, None, 1.00, 2.0),
    (1, "Regular", 25, 0.90, 1.10, 1.5),
    (2, "Veteran", 100, 0.95, 1.20, 1.0),
    (3, "Expert", 500, 0.97, 1.35, 0.5),
    (4, "Pathfinder", 2000, 0.98, 1.50, 0.0),
]


def level_for(accepted_count: int, acceptance_rate: float) -> int:
    """Highest level whose cumulative-count AND rate gates are both met."""
    level = 0
    for lv, _name, threshold, rate_gate, _rate, _bond in LEVELS:
        if accepted_count < threshold:
            continue
        if rate_gate is not None and acceptance_rate < rate_gate:
            continue
        level = lv
    return level


def rate_multiplier(level: int) -> float:
    return LEVELS[max(0, min(level, MAX_LEVEL))][4]


def bond_multiplier(level: int) -> float:
    return LEVELS[max(0, min(level, MAX_LEVEL))][5]


def level_info(accepted_count: int, acceptance_rate: float) -> dict:
    """The ``/me`` (or ``/actor``) level block, field names pinned by contract §6."""
    level = level_for(accepted_count, acceptance_rate)
    _lv, name, _threshold, _rate_gate, rate_mult, bond_mult = LEVELS[level]
    return {
        "level": level,
        "level_name": name,
        "accepted_count": accepted_count,
        "acceptance_rate": acceptance_rate,
        "rate_multiplier": rate_mult,
        "bond_multiplier": bond_mult,
    }
